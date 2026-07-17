"""Tests for normalize_posted_at and Date posted sort priority."""

from datetime import datetime, timezone

from utils.parsing import normalize_posted_at
from utils.schema import JOB_COLUMNS
from local_storage import JobDatabase


def test_normalize_posted_at_iso():
    assert normalize_posted_at("2026-05-12") == "2026-05-12"
    assert normalize_posted_at("2026-05-12T22:43:58.494Z") == "2026-05-12"


def test_normalize_posted_at_relative():
    now = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
    assert normalize_posted_at("2 days ago", now=now) == "2026-07-15"
    assert normalize_posted_at("Reposted 1 week ago", now=now) == "2026-07-10"
    assert normalize_posted_at("Just now", now=now) == "2026-07-17"
    assert normalize_posted_at("yesterday", now=now) == "2026-07-16"
    assert normalize_posted_at("Posted 3 hours ago", now=now) == "2026-07-17"


def test_normalize_posted_at_empty_unknown():
    assert normalize_posted_at("") == ""
    assert normalize_posted_at(None) == ""
    assert normalize_posted_at("sometime last spring") == ""


def test_normalize_easy_apply():
    from utils.parsing import normalize_easy_apply
    assert normalize_easy_apply(True) == "TRUE"
    assert normalize_easy_apply(False) == "FALSE"
    assert normalize_easy_apply("yes") == "TRUE"
    assert normalize_easy_apply("") == ""


def test_date_posted_in_schema():
    assert "Date posted" in JOB_COLUMNS
    assert "Easy apply" in JOB_COLUMNS


def test_sort_by_prefers_easy_apply_then_newer_within_same_fit(tmp_path):
    db = JobDatabase(str(tmp_path / "jobs.db"), JOB_COLUMNS)
    base = {col: "" for col in JOB_COLUMNS}
    older = dict(base, **{
        "Company Name": "A",
        "Job Title": "Eng",
        "Job URL": "https://example.com/old",
        "Fit score enum": "4",
        "JD fit score": "7",
        "Location Priority": "1",
        "Date posted": "2026-01-01",
        "Easy apply": "FALSE",
    })
    newer_no_easy = dict(base, **{
        "Company Name": "B",
        "Job Title": "Eng",
        "Job URL": "https://example.com/new",
        "Fit score enum": "4",
        "JD fit score": "7",
        "Location Priority": "1",
        "Date posted": "2026-07-01",
        "Easy apply": "FALSE",
    })
    older_easy = dict(base, **{
        "Company Name": "E",
        "Job Title": "Eng",
        "Job URL": "https://example.com/easy",
        "Fit score enum": "4",
        "JD fit score": "7",
        "Location Priority": "1",
        "Date posted": "2026-02-01",
        "Easy apply": "TRUE",
    })
    better_fit = dict(base, **{
        "Company Name": "C",
        "Job Title": "Eng",
        "Job URL": "https://example.com/best",
        "Fit score enum": "5",
        "JD fit score": "9",
        "Location Priority": "1",
        "Date posted": "2025-01-01",
        "Easy apply": "FALSE",
    })
    db.add_jobs([older, newer_no_easy, older_easy, better_fit])
    db.sort_by([
        ("Fit score enum", False),
        ("Easy apply", False),
        ("Date posted", False),
        ("Location Priority", True),
    ])
    jobs = db.get_all_jobs()
    assert [j["Company Name"] for j in jobs] == ["C", "E", "B", "A"]
