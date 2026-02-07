"""Data loading, DB updates, and file/resume helpers."""
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import dotenv_values

from local_storage import JobDatabase
from utils import SHEET_HEADER, get_user_name
from api_methods import get_resume_json
from setup_server import get_app_root


def _parse_bool_env(val, default: bool = False) -> bool:
    if val is None:
        return default
    s = str(val).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off"):
        return False
    return default


@st.cache_data(ttl=60)  # Short TTL so Settings changes are picked up
def get_check_sustainability() -> bool:
    """Return True if CHECK_SUSTAINABILITY is enabled in .env (Settings / env / yaml)."""
    env_path = Path(get_app_root()) / ".env"
    if not env_path.exists():
        return False
    data = dotenv_values(env_path)
    return _parse_bool_env(data.get("CHECK_SUSTAINABILITY"), default=False)


@st.cache_data(ttl=3600)  # Cache for 1 hour - user_name rarely changes
def get_cached_user_name():
    """Get user name from resume JSON, cached separately."""
    try:
        resume_json = get_resume_json()
        return get_user_name(resume_json)
    except Exception:
        return None


def open_file_manager(file_path: Path) -> None:
    """Open file manager at the location of the file (OS-agnostic)."""
    file_path = Path(file_path).resolve()

    if sys.platform == "win32":
        subprocess.run(["explorer", "/select,", str(file_path)])
    elif sys.platform == "darwin":
        subprocess.run(["open", "-R", str(file_path)])
    else:
        file_dir = file_path.parent
        managers = [
            ["xdg-open", str(file_dir)],
            ["nautilus", str(file_dir)],
            ["dolphin", str(file_dir)],
            ["thunar", str(file_dir)],
            ["pcmanfm", str(file_dir)],
        ]
        for manager in managers:
            try:
                subprocess.run(manager, check=True)
                break
            except (subprocess.CalledProcessError, FileNotFoundError):
                continue
        else:
            st.error(f"Could not open file manager. File location: {file_dir}")


def get_resume_path(resume_url: str) -> Path | None:
    """Convert resume URL/path to absolute Path object. Handles relative paths from local_data/resumes/."""
    if not resume_url or not resume_url.strip():
        return None

    resume_url = resume_url.strip()
    path = Path(resume_url)

    if not path.is_absolute():
        if resume_url.startswith("local_data/"):
            path = Path(".") / path
        else:
            path = Path(".") / path

    try:
        resolved = path.resolve()
        return resolved if resolved.exists() else None
    except (OSError, ValueError):
        return None


@st.cache_data(ttl=60)  # 1 minute so dashboard sees main.py JD/expiry updates soon after refresh
def load_job_data():
    """Load job data from SQLite database."""
    try:
        db_path = Path("local_data") / "jobs.db"
        if not db_path.exists():
            return None, "No job data found. Please run the main application first."

        db = JobDatabase(str(db_path), SHEET_HEADER)
        records = db.get_all_records()

        if not records:
            return None, "No jobs found in the database."

        df = pd.DataFrame(records)
        return df, None
    except Exception as e:
        return None, f"Error loading data: {str(e)}"


def update_job_field(job_url_key: str, company_key: str, field_name: str, value: str) -> int:
    """Update a single field for a job in the database."""
    db_path = Path("local_data") / "jobs.db"
    if not db_path.exists():
        return 0

    db = JobDatabase(str(db_path), SHEET_HEADER)
    return db.update_job_by_key(job_url_key, company_key, {field_name: value})


def handle_field_update(
    job_url_key: str,
    company_key: str,
    field_name: str,
    new_value: str,
    current_value: str,
    success_msg: str,
) -> None:
    """Helper to handle field updates with robust refresh logic."""
    if new_value != current_value:
        rows_affected = update_job_field(job_url_key, company_key, field_name, new_value)
        if rows_affected > 0:
            st.success(success_msg)
            if "df" in st.session_state:
                df = st.session_state.df
                mask = (df.get("Job URL", "") == job_url_key) & (
                    df.get("Company Name", "") == company_key
                )
                df.loc[mask, field_name] = new_value
                st.session_state.df = df
                if "filter_options_cache" in st.session_state:
                    del st.session_state.filter_options_cache
                if "df_hash" in st.session_state:
                    del st.session_state.df_hash
            st.cache_data.clear()
            st.rerun()
        else:
            st.error(f"Failed to update {field_name}. Record not found in database.")
            st.info(f"Debug: Company='{company_key}', URL='{job_url_key[:50]}...'")
    else:
        st.info("No changes detected.")
