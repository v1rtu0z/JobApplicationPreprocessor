"""Tests for expired-only job repost update-in-place (#06 phase 2).

Applied is user-scoped: it blocks duplicates but never triggers a shared listing refresh.
"""

import pytest

from local_storage import JobDatabase
from utils.schema import JOB_COLUMNS
from utils.storage import (
    build_repost_updates,
    get_existing_job_keys,
    get_expired_jobs_by_key,
)


@pytest.fixture
def job_db(tmp_path):
    return JobDatabase(str(tmp_path / "jobs.db"), JOB_COLUMNS)


def _base_row(**extra):
    row = {col: "" for col in JOB_COLUMNS}
    row.update({
        "Company Name": "Acme",
        "Job Title": "Lead Engineer",
        "Location": "Remote",
        "Location Priority": "1",
        "Job Description": "Old JD",
        "Job URL": "https://example.com/jobs/old",
        "Fit score": "Good fit",
        "Fit score enum": "4",
        "Job analysis": "old analysis",
        "Tailored resume url": "local_data/resumes/old.pdf",
        "Tailored cover letter (to be humanized)": "old CL",
        "Telegram notified": "TRUE",
        "Telegram app completed": "TRUE",
        "Company overview": "Acme builds widgets",
        "Sustainable company": "TRUE",
        **extra,
    })
    return row


def _patch_collection_filters(monkeypatch):
    monkeypatch.setattr("pipeline.collection._get_job_filters", lambda: {})
    monkeypatch.setattr(
        "pipeline.collection._apply_keyword_filters",
        lambda *a, **k: (False, ""),
    )
    monkeypatch.setattr(
        "pipeline.collection._apply_sustainability_keyword_filters",
        lambda *a, **k: (False, "", ""),
    )
    monkeypatch.setattr("pipeline.collection.parse_location", lambda x: x)
    monkeypatch.setattr("pipeline.collection.get_location_priority", lambda x: 1)


class TestBuildRepostUpdates:
    def test_clears_listing_state_but_not_applied(self):
        old = _base_row(**{"Job posting expired": "TRUE", "Applied": "TRUE"})
        new_fields = {
            "Job URL": "https://example.com/jobs/new",
            "Job Description": "Fresh JD",
            "Location": "Berlin",
            "Location Priority": "2",
            "Job Title": "Lead Engineer",
            "Company Name": "Acme",
            "Date added": "2026-07-16",
        }
        updates = build_repost_updates(old, new_fields)

        assert updates["Job URL"] == "https://example.com/jobs/new"
        assert updates["Job Description"] == "Fresh JD"
        assert updates["Job posting expired"] == ""
        assert "Applied" not in updates  # user-scoped — never part of shared refresh
        assert updates["Fit score"] == ""
        assert updates["Tailored resume url"] == ""
        assert updates["Telegram notified"] == ""
        assert "Company overview" not in updates


class TestGetExpiredJobsByKey:
    def test_maps_expired_only_not_applied(self, job_db):
        job_db.add_jobs([
            _base_row(**{"Job posting expired": "TRUE"}),
            _base_row(
                **{
                    "Job Title": "Other",
                    "Job URL": "https://example.com/other",
                    "Applied": "TRUE",
                }
            ),
            _base_row(
                **{
                    "Job Title": "Active",
                    "Job URL": "https://example.com/active",
                }
            ),
        ])
        by_key = get_expired_jobs_by_key(job_db)
        assert "Lead Engineer @ Acme" in by_key
        assert "Other @ Acme" not in by_key
        assert "Active @ Acme" not in by_key

    def test_prefers_higher_id_when_duplicates(self, job_db):
        job_db.add_jobs([
            _base_row(**{"Job URL": "https://example.com/a", "Job posting expired": "TRUE"}),
            _base_row(**{"Job URL": "https://example.com/b", "Job posting expired": "TRUE"}),
        ])
        by_key = get_expired_jobs_by_key(job_db)
        assert by_key["Lead Engineer @ Acme"]["Job URL"] == "https://example.com/b"


class TestCollectJobsRepost:
    def test_updates_expired_row_instead_of_inserting(self, job_db, monkeypatch):
        job_db.add_jobs([_base_row(**{"Job posting expired": "TRUE", "Applied": "TRUE"})])

        class FakeSource:
            def is_available(self):
                return True

            def fetch_jobs(self, search_url=None, params=None):
                yield {
                    "job_title": "Lead Engineer",
                    "company_name": "Acme",
                    "job_url": "https://example.com/jobs/new",
                    "location": "Berlin",
                    "job_description": "Fresh JD from repost",
                }

        monkeypatch.setattr("pipeline.collection.ApifyDataSource", FakeSource)
        _patch_collection_filters(monkeypatch)

        from pipeline.collection import collect_jobs_via_apify

        ids = collect_jobs_via_apify(job_db, params={"keywords": "Lead"})

        jobs = job_db.get_all_jobs()
        assert len(jobs) == 1
        job = jobs[0]
        assert job["Job URL"] == "https://example.com/jobs/new"
        assert job["Job Description"] == "Fresh JD from repost"
        assert job.get("Job posting expired", "") != "TRUE"
        assert job.get("Applied") == "TRUE"  # preserved — user-scoped
        assert job.get("Fit score", "") == ""
        assert job["Company overview"] == "Acme builds widgets"
        assert ids == [("https://example.com/jobs/new", "Acme")]

    def test_applied_only_blocks_without_updating(self, job_db, monkeypatch):
        job_db.add_jobs([_base_row(**{"Applied": "TRUE"})])
        assert "Lead Engineer @ Acme" in get_existing_job_keys(job_db)

        class FakeSource:
            def is_available(self):
                return True

            def fetch_jobs(self, search_url=None, params=None):
                yield {
                    "job_title": "Lead Engineer",
                    "company_name": "Acme",
                    "job_url": "https://example.com/jobs/reposted",
                    "location": "Remote",
                    "job_description": "Again",
                }

        monkeypatch.setattr("pipeline.collection.ApifyDataSource", FakeSource)
        _patch_collection_filters(monkeypatch)

        from pipeline.collection import collect_jobs_via_apify

        ids = collect_jobs_via_apify(job_db, params={"keywords": "Lead"})
        assert ids == []
        jobs = job_db.get_all_jobs()
        assert len(jobs) == 1
        assert jobs[0]["Job URL"] == "https://example.com/jobs/old"
        assert jobs[0].get("Applied") == "TRUE"

    def test_active_job_still_blocks_duplicate(self, job_db, monkeypatch):
        job_db.add_jobs([_base_row()])

        class FakeSource:
            def is_available(self):
                return True

            def fetch_jobs(self, search_url=None, params=None):
                yield {
                    "job_title": "Lead Engineer",
                    "company_name": "Acme",
                    "job_url": "https://example.com/jobs/other",
                    "location": "Remote",
                    "job_description": "Should be skipped",
                }

        monkeypatch.setattr("pipeline.collection.ApifyDataSource", FakeSource)
        monkeypatch.setattr("pipeline.collection._get_job_filters", lambda: {})

        from pipeline.collection import collect_jobs_via_apify

        ids = collect_jobs_via_apify(job_db, params={"keywords": "Lead"})
        assert ids == []
        assert len(job_db.get_all_jobs()) == 1
        assert job_db.get_all_jobs()[0]["Job URL"] == "https://example.com/jobs/old"

    def test_inserts_when_no_expired_match(self, job_db, monkeypatch):
        class FakeSource:
            def is_available(self):
                return True

            def fetch_jobs(self, search_url=None, params=None):
                yield {
                    "job_title": "Brand New",
                    "company_name": "Acme",
                    "job_url": "https://example.com/jobs/brand-new",
                    "location": "Remote",
                    "job_description": "Fresh",
                }

        monkeypatch.setattr("pipeline.collection.ApifyDataSource", FakeSource)
        _patch_collection_filters(monkeypatch)

        from pipeline.collection import collect_jobs_via_apify

        ids = collect_jobs_via_apify(job_db, params={"keywords": "New"})
        assert ids == [("https://example.com/jobs/brand-new", "Acme")]
        assert len(job_db.get_all_jobs()) == 1
