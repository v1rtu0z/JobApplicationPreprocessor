"""Database/sheet setup, job lookups, and legacy helpers."""

from pathlib import Path
from typing import Any

from .linkedin_crawl import check_job_expiration
from .schema import SHEET_HEADER


def setup_driver():
    """Initialize and return a headless Chrome driver"""
    from selenium.webdriver.chrome.options import Options
    from selenium import webdriver

    options = Options()
    return webdriver.Chrome(options=options)


def setup_database(user_name: str):
    """Set up the local SQLite job store (SQLite database) for job data."""
    from local_storage import JobDatabase

    db_path = Path("local_data") / "jobs.db"
    db = JobDatabase(str(db_path), SHEET_HEADER)
    print(f"Using local SQLite storage: {db_path}")
    return db


def setup_spreadsheet(user_name: str):
    """Legacy alias for setup_database(). Prefer setup_database for new code."""
    return setup_database(user_name)


def get_existing_job_keys(job_store) -> set[str]:
    """Get set of existing job keys (job_title @ company_name) from the job store.
    job_store: JobDatabase or any object with get_all_records() returning list of dicts.
    """
    all_rows = job_store.get_all_records()
    existing = set()
    for row in all_rows:
        job_title = row.get('Job Title', '').strip()
        company_name = row.get('Company Name', '').strip()
        if job_title and company_name:
            existing.add(f"{job_title} @ {company_name}")
    return existing


def get_existing_jobs(sheet):
    """Legacy alias for get_existing_job_keys(). Prefer get_existing_job_keys for new code."""
    return get_existing_job_keys(sheet)


def parse_fit_score(job_analysis: str) -> str:
    """Extract fit score from job analysis text"""
    fit_levels = ['Very good fit', 'Good fit', 'Moderate fit', 'Poor fit', 'Very poor fit']
    for level in fit_levels:
        if level in job_analysis:
            return level
    return 'Questionable fit'


def update_cell(db, job_url: str, company_name: str, column_name: str, value: str):
    """Helper to update a job field by job URL and company name"""
    if not job_url or not company_name:
        return
    db.update_job_by_key(job_url, company_name, {column_name: value})


def get_column_index(job_store, column_name: str) -> int | Any:
    """Legacy helper: returns 1-based column index. job_store must have get_headers() or row_values(1)."""
    if hasattr(job_store, 'get_headers'):
        header = job_store.get_headers()
    else:
        header = job_store.row_values(1)
    return header.index(column_name) + 1
