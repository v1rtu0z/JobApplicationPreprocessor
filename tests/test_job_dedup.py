"""Tests for job collection dedup keys."""

from core.repository import JobRepository
from utils.storage import get_existing_job_keys


class MockStore:
    def __init__(self, records):
        self.records = list(records)

    def get_all_records(self):
        return list(self.records)


class TestGetExistingJobKeys:
    def test_includes_active_jobs(self):
        store = MockStore([
            {"Job Title": "Engineer", "Company Name": "Acme", "Job URL": "u1"},
        ])
        assert "Engineer @ Acme" in get_existing_job_keys(store)

    def test_excludes_expired_jobs(self):
        store = MockStore([
            {
                "Job Title": "Engineer",
                "Company Name": "Acme",
                "Job URL": "u1",
                "Job posting expired": "TRUE",
            },
        ])
        assert get_existing_job_keys(store) == set()

    def test_includes_applied_jobs(self):
        """Applied is user-scoped — still occupies the dedup key (no shared overwrite)."""
        store = MockStore([
            {
                "Job Title": "Engineer",
                "Company Name": "Acme",
                "Job URL": "u1",
                "Applied": "TRUE",
            },
        ])
        assert get_existing_job_keys(store) == {"Engineer @ Acme"}

    def test_repository_matches_storage_helper(self):
        store = MockStore([
            {"Job Title": "Active", "Company Name": "Co", "Job URL": "a"},
            {
                "Job Title": "Expired",
                "Company Name": "Co",
                "Job URL": "b",
                "Job posting expired": "TRUE",
            },
            {
                "Job Title": "Applied Role",
                "Company Name": "Co",
                "Job URL": "c",
                "Applied": "TRUE",
            },
        ])
        repo = JobRepository(store)
        assert repo.get_existing_job_keys() == get_existing_job_keys(store)
        assert repo.get_existing_job_keys() == {"Active @ Co", "Applied Role @ Co"}
