"""Unit tests for JobRepository."""

import pytest

from core.models import Job
from core.repository import JobRepository


class MockStore:
    def __init__(self):
        self.records = []
        self.updates = []

    def get_all_records(self):
        return list(self.records)

    def add_jobs(self, jobs):
        self.records.extend(jobs)

    def update_job_by_key(self, job_url, company_name, updates):
        self.updates.append((job_url, company_name, updates))
        for r in self.records:
            if r.get("Job URL") == job_url and r.get("Company Name") == company_name:
                r.update(updates)
                return 1
        return 0


class TestJobRepository:
    def test_get_all_records(self):
        store = MockStore()
        store.records = [
            {"Company Name": "A", "Job Title": "T1", "Job URL": "u1"},
            {"Company Name": "B", "Job Title": "T2", "Job URL": "u2"},
        ]
        repo = JobRepository(store)
        assert len(repo.get_all_records()) == 2

    def test_get_all_jobs(self):
        store = MockStore()
        store.records = [
            {"Company Name": "A", "Job Title": "T1", "Job URL": "u1"},
        ]
        repo = JobRepository(store)
        jobs = repo.get_all_jobs()
        assert len(jobs) == 1
        assert jobs[0].company_name == "A"
        assert jobs[0].job_title == "T1"

    def test_get_existing_job_keys(self):
        store = MockStore()
        store.records = [
            {"Company Name": "Acme", "Job Title": "Engineer", "Job URL": "u"},
        ]
        repo = JobRepository(store)
        keys = repo.get_existing_job_keys()
        assert "Engineer @ Acme" in keys

    def test_add_jobs(self):
        store = MockStore()
        repo = JobRepository(store)
        repo.add_jobs([
            {"Company Name": "A", "Job Title": "T", "Job URL": "u"},
        ])
        assert len(store.records) == 1
        assert store.records[0]["Company Name"] == "A"

    def test_update_by_key(self):
        store = MockStore()
        store.records = [{"Company Name": "A", "Job Title": "T", "Job URL": "u"}]
        repo = JobRepository(store)
        n = repo.update_by_key("u", "A", {"Fit score": "Good fit"})
        assert n == 1
        assert store.records[0].get("Fit score") == "Good fit"
