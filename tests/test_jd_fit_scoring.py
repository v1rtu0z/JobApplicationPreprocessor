"""Tests for JD-only fit scoring when automation is idle."""

import pytest

from local_storage import JobDatabase
from pipeline.jd_fit_scoring import (
    is_automation_idle,
    jobs_need_jd_fit_scoring,
    manual_co_work_pending,
    score_jobs_by_jd_fit,
    should_run_jd_only_fit_scoring,
)
from utils.schema import SHEET_HEADER


@pytest.fixture
def job_db(tmp_path):
    return JobDatabase(str(tmp_path / "jobs.db"), SHEET_HEADER)


def _job(**kwargs):
    row = {col: "" for col in SHEET_HEADER}
    row.update({
        "Company Name": "Acme",
        "Job Title": "Engineer",
        "Job URL": "https://example.com/1",
        "Job Description": "Python backend role with Django.",
    })
    row.update(kwargs)
    return row


class TestJdFitScoringIdleDetection:
    def test_jobs_need_jd_fit_scoring_when_blocked_without_co(self, job_db, monkeypatch):
        monkeypatch.setattr("pipeline.jd_fit_scoring.CHECK_SUSTAINABILITY", True)
        job_db.add_jobs([_job()])

        assert jobs_need_jd_fit_scoring(job_db) is True

    def test_should_run_when_automation_idle_and_co_manual_next(self, job_db, monkeypatch):
        monkeypatch.setattr("pipeline.jd_fit_scoring.CHECK_SUSTAINABILITY", True)
        monkeypatch.setattr("pipeline.jd_fit_scoring.CRAWL_LINKEDIN", False)
        monkeypatch.setattr("utils.apify_client.apify_state.is_available", lambda: False)
        job_db.add_jobs([_job()])

        assert is_automation_idle(job_db) is True
        assert should_run_jd_only_fit_scoring(job_db) is True
        assert manual_co_work_pending(job_db) is True

    def test_should_not_run_when_full_analysis_actionable(self, job_db, monkeypatch):
        monkeypatch.setattr("pipeline.jd_fit_scoring.CHECK_SUSTAINABILITY", False)
        job_db.add_jobs([_job()])

        assert should_run_jd_only_fit_scoring(job_db) is False

    def test_should_not_run_when_co_fetch_still_actionable(self, job_db, monkeypatch):
        monkeypatch.setattr("pipeline.jd_fit_scoring.CHECK_SUSTAINABILITY", True)
        monkeypatch.setattr("pipeline.jd_fit_scoring.CRAWL_LINKEDIN", False)
        monkeypatch.setattr("utils.apify_client.apify_state.is_available", lambda: True)
        job_db.add_jobs([_job()])

        assert should_run_jd_only_fit_scoring(job_db) is False

    def test_skips_jobs_already_jd_scored(self, job_db, monkeypatch):
        monkeypatch.setattr("pipeline.jd_fit_scoring.CHECK_SUSTAINABILITY", True)
        job_db.add_jobs([_job(**{"JD fit score": "8"})])

        assert jobs_need_jd_fit_scoring(job_db) is False

    def test_nan_jd_fit_score_still_needs_scoring(self, job_db, monkeypatch):
        monkeypatch.setattr("pipeline.jd_fit_scoring.CHECK_SUSTAINABILITY", True)
        job_db.add_jobs([_job(**{"JD fit score": "nan"})])

        assert jobs_need_jd_fit_scoring(job_db) is True


class TestJdFitScoringExecution:
    def test_score_jobs_persists_jd_fit_fields(self, job_db, monkeypatch):
        monkeypatch.setattr("pipeline.jd_fit_scoring.CHECK_SUSTAINABILITY", True)
        monkeypatch.setattr("pipeline.jd_fit_scoring.acquire_gemini_slot", lambda: None)
        job_db.add_jobs([
            _job(),
            _job(
                **{
                    "Company Name": "Beta",
                    "Job Title": "Developer",
                    "Job URL": "https://example.com/2",
                }
            ),
        ])
        monkeypatch.setattr(
            "pipeline.jd_fit_scoring.score_jobs_by_jd_batch",
            lambda resume_json, jobs: [
                {"job_id": "Engineer @ Acme", "jd_fit_score": 9, "reasoning": "Strong match"},
                {"job_id": "Developer @ Beta", "jd_fit_score": 6, "reasoning": "Decent overlap"},
            ],
        )

        count = score_jobs_by_jd_fit(job_db, resume_json={})

        assert count == 2
        rows = {r["Job URL"]: r for r in job_db.get_all_records()}
        assert rows["https://example.com/1"]["JD fit score"] == "9"
        assert rows["https://example.com/2"]["JD fit score"] == "6"

    def test_continues_after_failed_batch(self, job_db, monkeypatch):
        monkeypatch.setattr("pipeline.jd_fit_scoring.CHECK_SUSTAINABILITY", True)
        monkeypatch.setattr("pipeline.jd_fit_scoring.acquire_gemini_slot", lambda: None)
        monkeypatch.setattr("pipeline.jd_fit_scoring.JD_FIT_BATCH_SIZE", 1)
        monkeypatch.setattr("pipeline.jd_fit_scoring.JD_FIT_BATCH_MAX_RETRIES", 1)
        job_db.add_jobs([
            _job(**{"Job URL": "https://example.com/1"}),
            _job(
                **{
                    "Company Name": "Beta",
                    "Job Title": "Developer",
                    "Job URL": "https://example.com/2",
                }
            ),
        ])

        responses = iter([[], [{"job_id": "Developer @ Beta", "jd_fit_score": 7, "reasoning": "ok"}]])

        def flaky_batch(resume_json, jobs):
            return next(responses)

        monkeypatch.setattr("pipeline.jd_fit_scoring.score_jobs_by_jd_batch", flaky_batch)

        count = score_jobs_by_jd_fit(job_db, resume_json={})

        assert count == 1
        rows = {r["Job URL"]: r for r in job_db.get_all_records()}
        assert rows["https://example.com/1"].get("JD fit score", "") == ""
        assert rows["https://example.com/2"]["JD fit score"] == "7"
