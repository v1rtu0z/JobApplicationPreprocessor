"""Tests for Telegram manual company overview prompts."""

import json

import pytest

from local_storage import JobDatabase
from utils.schema import SHEET_HEADER
from utils import telegram_bot as tg


@pytest.fixture
def job_db(tmp_path, monkeypatch):
    db = JobDatabase(str(tmp_path / "jobs.db"), SHEET_HEADER)
    pending = tmp_path / "pending.json"
    skipped = tmp_path / "skipped.json"
    monkeypatch.setattr(tg, "PENDING_CO_FILE", pending)
    monkeypatch.setattr(tg, "SKIPPED_CO_FILE", skipped)
    monkeypatch.setattr(tg, "CHECK_SUSTAINABILITY", True)
    return db


def _co_job(company, title, url, jd_fit="8", **extra):
    row = {col: "" for col in SHEET_HEADER}
    row.update({
        "Company Name": company,
        "Job Title": title,
        "Job URL": url,
        "Job Description": "Build things.",
        "JD fit score": jd_fit,
        "Location Priority": "1",
        **extra,
    })
    return row


class TestCommandsHint:
    def test_includes_requested_commands(self):
        hint = tg._commands_hint("skipco", "status")
        assert "/skipco" in hint
        assert "/status" in hint
        assert "Commands" in hint


class TestManualCoSelection:
    def test_picks_highest_jd_fit_first(self, job_db):
        job_db.add_jobs([
            _co_job("Low Co", "Role A", "https://example.com/a", jd_fit="5"),
            _co_job("High Co", "Role B", "https://example.com/b", jd_fit="9"),
        ])
        nxt = tg._get_next_manual_co_job(job_db)
        assert nxt["Company Name"] == "High Co"

    def test_skips_jobs_with_overview(self, job_db):
        job_db.add_jobs([
            _co_job("Done Co", "Role", "https://example.com/d", **{"Company overview": "Already have it."}),
            _co_job("Need Co", "Role", "https://example.com/n"),
        ])
        nxt = tg._get_next_manual_co_job(job_db)
        assert nxt["Company Name"] == "Need Co"

    def test_skips_jobs_hidden_from_dashboard(self, job_db, monkeypatch):
        monkeypatch.setattr("pipeline.dashboard_filter.CHECK_SUSTAINABILITY", True)
        job_db.add_jobs([
            _co_job(
                "Hidden Co",
                "Role",
                "https://example.com/h",
                jd_fit="9",
                **{"Sustainable company": "FALSE"},
            ),
            _co_job("Visible Co", "Role", "https://example.com/v", jd_fit="5"),
        ])
        nxt = tg._get_next_manual_co_job(job_db)
        assert nxt["Company Name"] == "Visible Co"


class TestManualCoPromptFlow:
    def test_prompt_sets_pending(self, job_db, monkeypatch):
        job_db.add_jobs([_co_job("Acme", "Engineer", "https://example.com/1")])
        job = job_db.get_all_jobs()[0]
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
        monkeypatch.setattr(tg, "resolve_chat_id", lambda: "42")
        monkeypatch.setattr(tg, "_api", lambda *a, **k: {"result": {"message_id": 1}})

        assert tg.prompt_manual_co_if_needed(job_db) is True
        assert tg._load_pending_co_job_id() == job["_id"]

    def test_does_not_prompt_while_pending(self, job_db, monkeypatch):
        job_db.add_jobs([
            _co_job("Acme", "Engineer", "https://example.com/1"),
            _co_job("Beta", "Dev", "https://example.com/2", jd_fit="9"),
        ])
        jobs = job_db.get_all_jobs()
        tg._set_pending_co_job_id(jobs[0]["_id"])
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
        monkeypatch.setattr(tg, "resolve_chat_id", lambda: "42")

        assert tg.prompt_manual_co_if_needed(job_db) is False

    def test_co_reply_saves_overview(self, job_db, monkeypatch):
        job_db.add_jobs([_co_job("Acme", "Engineer", "https://example.com/1")])
        job = job_db.get_all_jobs()[0]
        tg._set_pending_co_job_id(job["_id"])
        monkeypatch.setattr(tg, "_api", lambda *a, **k: {})

        overview = "A" * tg.MIN_CO_REPLY_LENGTH
        tg._handle_co_text_reply(42, job_db, job["_id"], overview)

        updated = job_db.get_job_by_id(job["_id"])
        assert updated["Company overview"] == overview
        assert tg._load_pending_co_job_id() is None

    def test_skipco_skips_job(self, job_db, monkeypatch):
        job_db.add_jobs([_co_job("Acme", "Engineer", "https://example.com/1")])
        job = job_db.get_all_jobs()[0]
        tg._set_pending_co_job_id(job["_id"])
        sent = []
        monkeypatch.setattr(tg, "_api", lambda method, **k: sent.append((method, k)) or {})

        tg._handle_skip_co_prompt(42, job_db)
        assert tg._load_pending_co_job_id() is None
        assert job["_id"] in tg._load_skipped_co_job_ids()
        nxt = tg._get_next_manual_co_job(job_db)
        assert nxt is None

        assert sent[0][0] == "sendMessage"
        assert "expired" in sent[0][1]["text"].lower()
        assert sent[0][1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"].startswith("qco:")

    def test_skipco_expired_callback_marks_job(self, job_db, monkeypatch):
        job_db.add_jobs([_co_job("Acme", "Engineer", "https://example.com/1")])
        job = job_db.get_all_jobs()[0]
        tg._skip_co_job_id(job["_id"])
        monkeypatch.setattr(tg, "_api", lambda *a, **k: {})
        monkeypatch.setattr(tg, "_authorized_chat", lambda chat_id: True)
        monkeypatch.setattr(tg, "prompt_manual_co_if_needed", lambda db: False)

        tg.handle_callback_query(
            {
                "id": "cb1",
                "data": f"qco:{job['_id']}:yes",
                "message": {"chat": {"id": 42}, "message_id": 99},
            },
            job_db,
        )
        updated = job_db.get_job_by_id(job["_id"])
        assert updated["Job posting expired"] == "TRUE"
