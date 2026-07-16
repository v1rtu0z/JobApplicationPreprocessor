"""Database setup, job lookups, and helpers."""

from pathlib import Path

from .schema import JOB_COLUMNS


def setup_database(user_name: str):
    """Set up the local SQLite job store for job data."""
    from local_storage import JobDatabase

    db_path = Path("local_data") / "jobs.db"
    db = JobDatabase(str(db_path), JOB_COLUMNS)
    print(f"Using local SQLite storage: {db_path}")
    return db


def get_existing_job_keys(job_store) -> set[str]:
    """Get set of existing job keys (job_title @ company_name) from the job store.

    Excludes **expired** rows so a repost can refresh that listing. Applied (non-expired)
    rows still occupy the key — Applied is user-scoped and must not be overwritten by a
    shared listing refresh.
    """
    all_rows = job_store.get_all_records()
    existing = set()
    for row in all_rows:
        if _is_expired_job_row(row):
            continue
        job_title = row.get('Job Title', '').strip()
        company_name = row.get('Company Name', '').strip()
        if job_title and company_name:
            existing.add(f"{job_title} @ {company_name}")
    return existing


def get_expired_jobs_by_key(job_store) -> dict[str, dict]:
    """Map ``Job Title @ Company Name`` → one expired row for in-place repost updates.

    Only expired listings are candidates: that signal is shareable across users. Applied
    alone is not — it stays on the user side of the M2M in multi-tenant designs.

    Prefer the highest ``_id`` when available so the newest expired duplicate is refreshed.
    """
    if hasattr(job_store, "get_all_jobs"):
        rows = job_store.get_all_jobs()
    else:
        rows = job_store.get_all_records()

    by_key: dict[str, dict] = {}
    for row in rows:
        if not _is_expired_job_row(row):
            continue
        job_title = (row.get("Job Title") or "").strip()
        company_name = (row.get("Company Name") or "").strip()
        if not job_title or not company_name:
            continue
        key = f"{job_title} @ {company_name}"
        prev = by_key.get(key)
        if prev is None:
            by_key[key] = row
            continue
        prev_id = prev.get("_id")
        curr_id = row.get("_id")
        if curr_id is not None and (prev_id is None or curr_id > prev_id):
            by_key[key] = row
    return by_key


# Backwards-compatible alias (expired-only; Applied is no longer treated as updatable).
get_terminal_jobs_by_key = get_expired_jobs_by_key


def build_repost_updates(old_row: dict, new_fields: dict) -> dict[str, str]:
    """Fields to write when refreshing an **expired** listing with a repost.

    Listing/pipeline fields are reset so analysis and assets re-run. ``Applied`` is
    **not** cleared — it is user-scoped (and must stay that way when this refresh is
    broadcast to all users linked to the same global job).
    """
    updates = {
        "Job URL": (new_fields.get("Job URL") or "").strip(),
        "Job Description": (new_fields.get("Job Description") or "").strip(),
        "Location": (new_fields.get("Location") or "").strip(),
        "Location Priority": str(new_fields.get("Location Priority") or ""),
        "Job Title": (new_fields.get("Job Title") or old_row.get("Job Title") or "").strip(),
        "Company Name": (new_fields.get("Company Name") or old_row.get("Company Name") or "").strip(),
        "Date added": (new_fields.get("Date added") or "").strip(),
        "Bulk filtered": "FALSE",
        "JD crawl attempted": "TRUE" if (new_fields.get("Job Description") or "").strip() else "FALSE",
        "CO fetch attempted": (old_row.get("CO fetch attempted") or "FALSE"),
        # Listing / pipeline state — safe to refresh for every user on this job
        "Fit score": "",
        "Fit score enum": "",
        "JD fit score": "",
        "JD fit reasoning": "",
        "Job analysis": "",
        "Bad analysis": "",
        "Tailored resume url": "",
        "Tailored resume json": "",
        "Resume feedback": "",
        "Resume feedback addressed": "",
        "Tailored cover letter (to be humanized)": "",
        "CL feedback": "",
        "CL feedback addressed": "",
        "Job posting expired": "",
        "Last expiration check": "",
        "Telegram notified": "",
        "Telegram app completed": "",
    }
    new_company_url = (new_fields.get("Company URL") or "").strip()
    if new_company_url:
        updates["Company URL"] = new_company_url
    return updates


def _is_expired_job_row(row: dict) -> bool:
    """True when the listing itself is expired (shareable across users)."""
    return (row.get("Job posting expired") or "").strip().upper() == "TRUE"


def _is_terminal_job_row(row: dict) -> bool:
    """Deprecated alias: historically meant expired-or-applied; now expired-only for dedup skips."""
    return _is_expired_job_row(row)


def parse_fit_score(job_analysis: str) -> str:
    """Extract fit score from job analysis text"""
    fit_levels = ['Very good fit', 'Good fit', 'Moderate fit', 'Poor fit', 'Very poor fit']
    for level in fit_levels:
        if level in job_analysis:
            return level
    return 'Questionable fit'
