"""Settings view: job_preferences.yaml, .env, and setup files."""
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml
from dotenv import dotenv_values

from config import CONFIG_FILE, _get_job_filters, _save_job_filters
from setup_server import get_app_root


def _split_lines(text: str) -> list[str]:
    if not text:
        return []
    return [ln.strip() for ln in str(text).splitlines() if ln.strip()]


def _default_job_filters() -> dict:
    """Default structure for job_preferences.yaml (mirrors config.py defaults)."""
    return {
        "job_title_skip_keywords": [],
        "job_title_skip_keywords_2": [],
        "company_skip_keywords": [],
        "location_skip_keywords": [],
        "location_priorities": {},
        "sustainability_criteria": {"positive": [], "negative": []},
        "general_settings": {"resume_theme": "engineeringclassic"},
        "search_parameters": [],
    }


def _merge_with_defaults(filters: dict) -> dict:
    base = _default_job_filters()
    if not isinstance(filters, dict):
        return base
    for k, v in base.items():
        if k not in filters:
            filters[k] = v
    if not isinstance(filters.get("sustainability_criteria"), dict):
        filters["sustainability_criteria"] = base["sustainability_criteria"]
    else:
        filters["sustainability_criteria"].setdefault("positive", [])
        filters["sustainability_criteria"].setdefault("negative", [])
    if not isinstance(filters.get("general_settings"), dict):
        filters["general_settings"] = base["general_settings"]
    else:
        filters["general_settings"].setdefault("resume_theme", "engineeringclassic")
    if not isinstance(filters.get("location_priorities"), dict):
        filters["location_priorities"] = {}
    if not isinstance(filters.get("search_parameters"), list):
        filters["search_parameters"] = []
    return filters


def _parse_bool(val, default: bool = False) -> bool:
    if val is None:
        return default
    s = str(val).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off"):
        return False
    return default


def _read_text_file(path: Path) -> str:
    try:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _write_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content or "", encoding="utf-8")


def _read_env_map(env_path: Path) -> dict[str, str]:
    """Read .env file and return key-value dict."""
    if not env_path.exists():
        return {}
    data = dotenv_values(env_path)
    out: dict[str, str] = {}
    for k, v in (data or {}).items():
        if k:
            val = "" if v is None else str(v)
            out[str(k)] = val
    return out


def _write_env_file(env_path: Path, merged: dict[str, str]) -> None:
    """Write a normalized .env with stable ordering + extra keys at end."""
    env_path.parent.mkdir(parents=True, exist_ok=True)
    header = "# Managed by the dashboard Settings page\n"
    preferred_order = [
        "USE_LOCAL_STORAGE",
        "EMAIL_ADDRESS",
        "CRAWL_LINKEDIN",
        "LINKEDIN_PASSWORD",
        "APIFY_API_TOKEN",
        "SERVER_URL",
        "API_KEY",
        "GEMINI_API_KEY",
        "BACKUP_GEMINI_API_KEY",
        "GEMINI_MODEL",
        "CHECK_SUSTAINABILITY",
        "RESUME_PDF_PATH",
    ]

    def fmt(k: str, v: str) -> str:
        s = "" if v is None else str(v)
        if s == "":
            return f"{k}="
        if any(ch in s for ch in [" ", "#", "=", "\n", '"']):
            s = s.replace("\\", "\\\\").replace('"', '\\"')
            return f'{k}="{s}"'
        return f"{k}={s}"

    lines: list[str] = [header.rstrip("\n")]
    written = set()
    for k in preferred_order:
        if k in merged:
            lines.append(fmt(k, merged.get(k, "")))
            written.add(k)
    extras = sorted([k for k in merged.keys() if k not in written])
    if extras:
        lines.append("")
        lines.append("# Extra keys")
        for k in extras:
            lines.append(fmt(k, merged.get(k, "")))
    env_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _load_rendercv_themes(app_root: Path) -> list[str]:
    """Load RenderCV theme options from app_root/rendercv_themes.txt if available."""
    default_themes = ["engineeringclassic", "moderncv", "classic", "sb2nov", "engineeringresumes"]
    themes_path = app_root / "rendercv_themes.txt"
    txt = _read_text_file(themes_path)
    themes = [t.strip() for t in txt.splitlines() if t.strip()] if txt else []
    if not themes:
        themes = default_themes
    for t in default_themes:
        if t not in themes:
            themes.append(t)
    seen = set()
    out = []
    for t in themes:
        tl = t.lower()
        if tl in seen:
            continue
        seen.add(tl)
        out.append(t)
    return out


def _coerce_location_priorities(df: pd.DataFrame) -> dict[str, int]:
    if df is None or df.empty:
        return {}
    out: dict[str, int] = {}
    for _, row in df.iterrows():
        loc = str(row.get("Location", "")).strip()
        if not loc:
            continue
        pr = row.get("Priority", "")
        try:
            pr_int = int(pr)
        except (TypeError, ValueError):
            continue
        out[loc] = pr_int
    return out


def render_settings_view() -> None:
    """Render the Settings view (tabs: .env, Keywords, Locations, Sustainability, Search params, General, Import/Export, Reset)."""
    app_root = get_app_root()
    env_path = app_root / ".env"
    env_map = _read_env_map(env_path)
    check_sustainability_enabled = _parse_bool(env_map.get("CHECK_SUSTAINABILITY"), default=False)

    st.title("Settings")
    st.caption(f"Edits here update `{env_path}` and `{CONFIG_FILE}`.")

    filters = _merge_with_defaults(_get_job_filters())

    tab_names = ["App config (.env)", "Keywords", "Locations"]
    if check_sustainability_enabled:
        tab_names.append("Sustainability")
    tab_names += ["Search parameters", "General", "Import / Export", "Reset"]
    tabs = st.tabs(tab_names)

    # ---------------- App config (.env) ----------------
    with tabs[0]:
        st.subheader("Environment configuration")
        existing = env_map

        email_existing = existing.get("EMAIL_ADDRESS", "").strip()
        server_url_existing = existing.get("SERVER_URL", "").strip()
        gemini_model_existing = existing.get("GEMINI_MODEL", "gemini-2.0-flash").strip()
        resume_pdf_path_existing = existing.get("RESUME_PDF_PATH", "").strip()
        if not resume_pdf_path_existing:
            candidate = app_root / "resume.pdf"
            if candidate.exists():
                resume_pdf_path_existing = str(candidate.resolve())

        use_local_storage_existing = _parse_bool(existing.get("USE_LOCAL_STORAGE"), default=True)
        crawl_linkedin_existing = _parse_bool(existing.get("CRAWL_LINKEDIN"), default=False)
        check_sust_existing = _parse_bool(existing.get("CHECK_SUSTAINABILITY"), default=False)

        with st.form("settings_env_form", clear_on_submit=False):
            st.markdown("### Core")
            use_local_storage = st.checkbox("Use local storage", value=use_local_storage_existing)
            email_address = st.text_input("Email address", value=email_existing)
            server_url = st.text_input("Server URL", value=server_url_existing)

            st.markdown("### LinkedIn")
            crawl_linkedin = st.checkbox("Enable LinkedIn crawling", value=crawl_linkedin_existing)
            linkedin_password_val = existing.get("LINKEDIN_PASSWORD", "") or ""
            linkedin_password = st.text_input(
                "LinkedIn password",
                value=linkedin_password_val,
                type="password",
                help="Edit to change password.",
            )

            st.markdown("### Apify")
            apify_token_val = existing.get("APIFY_API_TOKEN", "") or ""
            apify_api_token = st.text_input(
                "Apify API token",
                value=apify_token_val,
                type="password",
                help="Edit to change token.",
            )

            st.markdown("### Gemini")
            gemini_key_val = existing.get("GEMINI_API_KEY", "") or ""
            gemini_api_key = st.text_input(
                "Gemini API key",
                value=gemini_key_val,
                type="password",
                help="Edit to change key.",
            )
            backup_gemini_key_val = existing.get("BACKUP_GEMINI_API_KEY", "") or ""
            backup_gemini_api_key = st.text_input(
                "Backup Gemini API key (optional)",
                value=backup_gemini_key_val,
                type="password",
                help="Edit to change key.",
            )
            gemini_model = st.text_input("Gemini model", value=gemini_model_existing)

            st.markdown("### Features")
            check_sustainability = st.checkbox("Check sustainability", value=check_sust_existing)
            st.caption(
                "⚠️ If you prioritize financial stability or maximum job options, consider leaving this off. "
                "Sustainability filtering can reduce the number of matches; some high-paying roles may be in industries classified as non-sustainable."
            )

            st.markdown("### Resume")
            resume_pdf_path = st.text_input("RESUME_PDF_PATH", value=resume_pdf_path_existing)

            st.markdown("### Server auth")
            api_key_val = existing.get("API_KEY", "") or ""
            api_key = st.text_input(
                "API key / secret (server auth)",
                value=api_key_val,
                type="password",
                help="Edit to change key.",
            )

            submitted = st.form_submit_button("Save .env")
            if submitted:
                if not email_address.strip():
                    st.error("Email address cannot be empty.")
                else:
                    merged = dict(existing)
                    merged["USE_LOCAL_STORAGE"] = "true" if use_local_storage else "false"
                    merged["EMAIL_ADDRESS"] = email_address.strip()
                    merged["SERVER_URL"] = server_url.strip()
                    merged["CRAWL_LINKEDIN"] = "true" if crawl_linkedin else "false"
                    merged["GEMINI_MODEL"] = gemini_model.strip() or "gemini-2.0-flash"
                    merged["CHECK_SUSTAINABILITY"] = "true" if check_sustainability else "false"
                    merged["RESUME_PDF_PATH"] = resume_pdf_path.strip()
                    if linkedin_password.strip():
                        merged["LINKEDIN_PASSWORD"] = linkedin_password.strip()
                    if apify_api_token.strip():
                        merged["APIFY_API_TOKEN"] = apify_api_token.strip()
                    if gemini_api_key.strip():
                        merged["GEMINI_API_KEY"] = gemini_api_key.strip()
                    if backup_gemini_api_key.strip():
                        merged["BACKUP_GEMINI_API_KEY"] = backup_gemini_api_key.strip()
                    if api_key.strip():
                        merged["API_KEY"] = api_key.strip()
                    _write_env_file(env_path, merged)
                    st.success(f"Saved `{env_path}`. Restart the main app to ensure it reloads env vars.")

        st.divider()
        st.subheader("Files (from setup)")
        add_path = app_root / "additional_details.txt"
        add_existing = _read_text_file(add_path)
        with st.form("settings_additional_details_form", clear_on_submit=False):
            additional_details = st.text_area(
                "Additional details",
                value=add_existing,
                height=180,
                help="Optional free text used by prompts (goals, constraints, preferences).",
            )
            saved = st.form_submit_button("Save additional details")
            if saved:
                _write_text_file(add_path, additional_details.strip())
                st.success(f"Saved `{add_path}`.")

        st.caption("Upload a resume PDF to the app folder (optional).")
        uploaded_resume = st.file_uploader("Upload resume PDF", type=["pdf"], key="settings_resume_upload")
        if uploaded_resume is not None:
            try:
                resume_target = app_root / "resume.pdf"
                resume_target.write_bytes(uploaded_resume.read())
                merged = dict(_read_env_map(env_path))
                merged["RESUME_PDF_PATH"] = str(resume_target)
                _write_env_file(env_path, merged)
                st.success(f"Uploaded resume to `{resume_target}` and updated RESUME_PDF_PATH.")
            except Exception as e:
                st.error(f"Failed to save resume PDF: {e}")

    # ---------------- Keywords ----------------
    with tabs[1]:
        st.subheader("Keyword filters")
        st.caption("One entry per line. Empty lines are ignored. Duplicates are removed on save.")
        with st.form("settings_keywords_form", clear_on_submit=False):
            title_1 = st.text_area(
                "Job title skip keywords (substring match)",
                value="\n".join(filters.get("job_title_skip_keywords", []) or []),
                height=160,
            )
            title_2 = st.text_area(
                "Job title skip keywords 2 (word match)",
                value="\n".join(filters.get("job_title_skip_keywords_2", []) or []),
                height=160,
                help="These are matched against words in the job title.",
            )
            company = st.text_area(
                "Company skip keywords",
                value="\n".join(filters.get("company_skip_keywords", []) or []),
                height=160,
            )
            location = st.text_area(
                "Location skip keywords",
                value="\n".join(filters.get("location_skip_keywords", []) or []),
                height=160,
            )
            submitted = st.form_submit_button("Save keyword settings")
            if submitted:
                filters["job_title_skip_keywords"] = _split_lines(title_1)
                filters["job_title_skip_keywords_2"] = _split_lines(title_2)
                filters["company_skip_keywords"] = _split_lines(company)
                filters["location_skip_keywords"] = _split_lines(location)
                _save_job_filters(filters)
                st.success("Saved keyword settings.")

    # ---------------- Locations ----------------
    with tabs[2]:
        st.subheader("Location priorities")
        st.caption("Lower numbers are higher priority (used for sorting). Add/remove rows as needed.")
        lp = filters.get("location_priorities", {}) or {}
        editor_key = "settings_location_priorities_editor"
        if not lp or len(lp) == 0:
            lp_df = pd.DataFrame([{"Location": "", "Priority": 0}])
        else:
            lp_rows = []
            for k, v in lp.items():
                if k and str(k).strip():
                    try:
                        priority = int(v) if v is not None else 0
                        lp_rows.append({"Location": str(k).strip(), "Priority": priority})
                    except (ValueError, TypeError):
                        continue
            lp_df = pd.DataFrame(lp_rows) if lp_rows else pd.DataFrame([{"Location": "", "Priority": 0}])

        edited_df = st.data_editor(
            lp_df,
            num_rows="dynamic",
            use_container_width=True,
            key=editor_key,
            column_config={
                "Location": st.column_config.TextColumn(required=False),
                "Priority": st.column_config.NumberColumn(min_value=0, step=1),
            },
        )
        if st.button("Save location priorities", key="settings_save_location_priorities"):
            filters["location_priorities"] = _coerce_location_priorities(edited_df)
            _save_job_filters(filters)
            st.success("Saved location priorities.")

    if check_sustainability_enabled:
        sustain_tab_idx = 3
        with tabs[sustain_tab_idx]:
            st.subheader("Sustainability criteria")
            st.caption("Only shown when CHECK_SUSTAINABILITY=true.")
            st.warning(
                "**Heads up:** If you're mainly looking for financial stability or the widest set of opportunities, "
                "sustainability filtering may limit your results. You can turn it off in the *App config (.env)* tab."
            )
            crit = filters.get("sustainability_criteria", {}) or {}
            with st.form("settings_sustainability_form", clear_on_submit=False):
                pos = st.text_area(
                    "Positive criteria / keywords",
                    value="\n".join((crit.get("positive") or [])),
                    height=180,
                )
                neg = st.text_area(
                    "Negative criteria / keywords",
                    value="\n".join((crit.get("negative") or [])),
                    height=180,
                )
                submitted = st.form_submit_button("Save sustainability settings")
                if submitted:
                    filters["sustainability_criteria"] = {
                        "positive": _split_lines(pos),
                        "negative": _split_lines(neg),
                    }
                    _save_job_filters(filters)
                    st.success("Saved sustainability settings.")
        offset = 1
    else:
        offset = 0

    # ---------------- Search parameters ----------------
    with tabs[3 + offset]:
        st.subheader("Cached search parameters")
        st.caption("Edit as YAML (a list of dictionaries).")
        current_yaml = yaml.safe_dump(
            filters.get("search_parameters", []) or [], sort_keys=False, default_flow_style=False
        )
        with st.form("settings_search_params_form", clear_on_submit=False):
            search_yaml = st.text_area(
                "search_parameters (YAML)",
                value=current_yaml,
                height=320,
            )
            submitted = st.form_submit_button("Save search parameters")
            if submitted:
                try:
                    parsed = yaml.safe_load(search_yaml) if search_yaml.strip() else []
                    if parsed is None:
                        parsed = []
                    if not isinstance(parsed, list):
                        raise ValueError("Expected a YAML list for search_parameters.")
                    filters["search_parameters"] = parsed
                    _save_job_filters(filters)
                    st.success("Saved search parameters.")
                except Exception as e:
                    st.error(f"Invalid YAML: {e}")

    # ---------------- General ----------------
    with tabs[4 + offset]:
        st.subheader("General settings")
        gs = filters.get("general_settings", {}) or {}
        themes = _load_rendercv_themes(app_root)
        current_theme = str(gs.get("resume_theme", "engineeringclassic") or "engineeringclassic").strip()
        if current_theme not in themes:
            themes.insert(0, current_theme)
        try:
            theme_index = themes.index(current_theme)
        except ValueError:
            theme_index = 0
        with st.form("settings_general_form", clear_on_submit=False):
            resume_theme = st.selectbox(
                "Resume theme",
                options=themes,
                index=theme_index,
                help="Populated from `rendercv_themes.txt` in the app folder (one theme per line).",
            )
            submitted = st.form_submit_button("Save general settings")
            if submitted:
                filters["general_settings"] = {"resume_theme": resume_theme.strip() or "engineeringclassic"}
                _save_job_filters(filters)
                st.success("Saved general settings.")
        if not (app_root / "rendercv_themes.txt").exists():
            st.info("Provide the full theme list by creating `rendercv_themes.txt` in the app folder.")

    # ---------------- Import / Export ----------------
    with tabs[5 + offset]:
        st.subheader("Import / export (job_preferences.yaml)")
        st.download_button(
            label="Download YAML",
            data=yaml.safe_dump(filters, sort_keys=False, default_flow_style=False),
            file_name=CONFIG_FILE,
            mime="application/x-yaml",
            key="settings_download_yaml",
            use_container_width=True,
        )
        uploaded = st.file_uploader("Upload YAML", type=["yaml", "yml"], key="settings_upload_yaml")
        if uploaded is not None:
            try:
                raw = uploaded.read()
                text = raw.decode("utf-8", errors="replace")
                parsed = yaml.safe_load(text)
                parsed = _merge_with_defaults(parsed if isinstance(parsed, dict) else {})
                st.success("YAML loaded successfully. Review below, then apply.")
                st.code(yaml.safe_dump(parsed, sort_keys=False, default_flow_style=False), language="yaml")
                if st.button("Apply uploaded YAML (overwrite)", key="settings_apply_uploaded_yaml"):
                    _save_job_filters(parsed)
                    st.success("Applied uploaded YAML.")
            except Exception as e:
                st.error(f"Could not parse YAML: {e}")

    # ---------------- Reset ----------------
    with tabs[6 + offset]:
        st.subheader("Reset to defaults")
        st.warning("This will overwrite your current job preferences YAML.")
        if st.button("Reset job preferences to defaults", key="settings_reset_defaults"):
            _save_job_filters(_default_job_filters())
            st.success("Reset settings to defaults.")
            st.rerun()
