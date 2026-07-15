"""Unit tests for Telegram application notifications (mocked API)."""

from unittest.mock import MagicMock, patch

import pytest

from local_storage import JobDatabase
from utils.schema import SHEET_HEADER
from utils import telegram_bot as tg


@pytest.fixture
def job_db(tmp_path):
    return JobDatabase(str(tmp_path / "jobs.db"), SHEET_HEADER)


def _ready_job(**extra):
    row = {col: "" for col in SHEET_HEADER}
    row.update({
        "Company Name": "Acme Corp",
        "Job Title": "Python Engineer",
        "Location": "Remote",
        "Job URL": "https://example.com/jobs/1",
        "Fit score": "Very good fit",
        "Fit score enum": "5",
        "Tailored resume url": "local_data/resumes/test_resume.pdf",
        "Tailored cover letter (to be humanized)": "Dear hiring manager,\n\nI am a great fit.",
        **extra,
    })
    return row


class TestApplicationIsReady:
    def test_ready_when_good_fit_with_assets(self):
        assert tg.application_is_ready(_ready_job())

    def test_not_ready_when_already_notified(self):
        assert not tg.application_is_ready(_ready_job(**{"Telegram notified": "TRUE"}))

    def test_not_ready_for_moderate_fit(self):
        assert not tg.application_is_ready(_ready_job(**{"Fit score": "Moderate fit"}))

    def test_not_ready_when_applied(self):
        assert not tg.application_is_ready(_ready_job(**{"Applied": "TRUE"}))

    def test_not_ready_when_hidden_from_dashboard(self, monkeypatch):
        monkeypatch.setattr("pipeline.dashboard_filter.CHECK_SUSTAINABILITY", True)
        assert not tg.application_is_ready(
            _ready_job(**{"Sustainable company": "FALSE"})
        )


class TestCallbackHandling:
    def test_q1_yes_marks_applied(self, job_db, monkeypatch):
        job_db.add_jobs([_ready_job()])
        job = job_db.get_all_jobs()[0]
        calls = []

        def fake_api(method, **payload):
            calls.append((method, payload))
            return {"result": {"message_id": 99}}

        monkeypatch.setattr(tg, "_api", fake_api)
        monkeypatch.setattr(tg, "resolve_chat_id", lambda: "1")
        monkeypatch.setattr(tg, "_save_chat_id", lambda _c: None)
        monkeypatch.setattr(tg, "notify_ready_applications", MagicMock(return_value=0))
        monkeypatch.setattr(tg, "PENDING_APP_FILE", job_db.db_path.parent / "pending_app.json")

        callback = {
            "id": "cb1",
            "data": f"q1:{job['_id']}:yes",
            "message": {"chat": {"id": 1}, "message_id": 10},
        }
        tg.handle_callback_query(callback, job_db)

        updated = job_db.get_job_by_id(job["_id"])
        assert updated["Applied"] == "TRUE"
        assert updated["Telegram app completed"] == "TRUE"
        assert not any(c[0] == "sendMessage" and "expired" in c[1].get("text", "").lower() for c in calls)

    def test_q1_no_asks_expired(self, job_db, monkeypatch):
        job_db.add_jobs([_ready_job()])
        job = job_db.get_all_jobs()[0]
        calls = []

        def fake_api(method, **payload):
            calls.append((method, payload))
            return {"result": {"message_id": 99}}

        monkeypatch.setattr(tg, "_api", fake_api)
        monkeypatch.setattr(tg, "resolve_chat_id", lambda: "1")

        callback = {
            "id": "cb2",
            "data": f"q1:{job['_id']}:no",
            "message": {"chat": {"id": 1}, "message_id": 10},
        }
        tg.handle_callback_query(callback, job_db)

        updated = job_db.get_job_by_id(job["_id"])
        assert updated.get("Applied") != "TRUE"
        assert any(c[0] == "sendMessage" and "expired" in c[1].get("text", "").lower() for c in calls)

    def test_q1_bad_marks_bad_analysis(self, job_db, monkeypatch):
        job_db.add_jobs([_ready_job()])
        job = job_db.get_all_jobs()[0]
        calls = []

        def fake_api(method, **payload):
            calls.append((method, payload))
            return {"result": {"message_id": 99}}

        monkeypatch.setattr(tg, "_api", fake_api)
        monkeypatch.setattr(tg, "resolve_chat_id", lambda: "1")
        monkeypatch.setattr(tg, "notify_ready_applications", MagicMock(return_value=0))
        monkeypatch.setattr(tg, "PENDING_APP_FILE", job_db.db_path.parent / "pending_app.json")

        callback = {
            "id": "cb3",
            "data": f"q1:{job['_id']}:bad",
            "message": {"chat": {"id": 1}, "message_id": 10},
        }
        tg.handle_callback_query(callback, job_db)

        updated = job_db.get_job_by_id(job["_id"])
        assert updated["Bad analysis"] == "TRUE"
        assert updated["Telegram app completed"] == "TRUE"
        assert updated.get("Telegram notified") != "TRUE"
        assert not any(c[0] == "sendMessage" and "expired" in c[1].get("text", "").lower() for c in calls)
        assert any(c[0] == "sendMessage" and "bad analysis" in c[1].get("text", "").lower() for c in calls)

    def test_q2_yes_marks_expired(self, job_db, monkeypatch):
        job_db.add_jobs([_ready_job()])
        job = job_db.get_all_jobs()[0]

        def fake_api(method, **payload):
            return {"result": {"message_id": 100}}

        monkeypatch.setattr(tg, "_api", fake_api)
        monkeypatch.setattr(tg, "resolve_chat_id", lambda: "1")
        monkeypatch.setattr(tg, "notify_ready_applications", MagicMock(return_value=0))

        callback = {
            "id": "cb2",
            "data": f"q2:{job['_id']}:yes",
            "message": {"chat": {"id": 1}, "message_id": 11},
        }
        tg.handle_callback_query(callback, job_db)

        updated = job_db.get_job_by_id(job["_id"])
        assert updated["Job posting expired"] == "TRUE"
        assert updated["Telegram app completed"] == "TRUE"


class TestNotifyReadyApplications:
    def test_sends_and_marks_notified(self, job_db, tmp_path, monkeypatch):
        resume_path = tmp_path / "resume.pdf"
        resume_path.write_bytes(b"%PDF-1.4 test")
        row = _ready_job(**{"Tailored resume url": str(resume_path)})
        job_db.add_jobs([row])
        job = job_db.get_all_jobs()[0]

        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
        monkeypatch.setattr(tg, "resolve_chat_id", lambda: "42")
        monkeypatch.setattr(tg, "send_application_package", MagicMock(return_value=1))
        monkeypatch.setattr(tg, "PENDING_APP_FILE", tmp_path / "pending_app.json")

        sent = tg.notify_ready_applications(job_db)
        assert sent == 1
        updated = job_db.get_job_by_id(job["_id"])
        assert updated["Telegram notified"] == "TRUE"
        assert tg._load_pending_application_job_id() == job["_id"]

    def test_sends_only_one_at_a_time(self, job_db, tmp_path, monkeypatch):
        resume_path = tmp_path / "resume.pdf"
        resume_path.write_bytes(b"%PDF-1.4 test")
        job_db.add_jobs([
            _ready_job(**{"Tailored resume url": str(resume_path), "Job URL": "https://example.com/1"}),
            _ready_job(**{
                "Tailored resume url": str(resume_path),
                "Job URL": "https://example.com/2",
                "Company Name": "Beta",
            }),
        ])
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
        monkeypatch.setattr(tg, "resolve_chat_id", lambda: "42")
        send_mock = MagicMock(return_value=1)
        monkeypatch.setattr(tg, "send_application_package", send_mock)
        monkeypatch.setattr(tg, "PENDING_APP_FILE", tmp_path / "pending_app.json")

        assert tg.notify_ready_applications(job_db) == 1
        assert send_mock.call_count == 1
        assert tg.notify_ready_applications(job_db) == 0

    def test_blocks_while_application_awaiting_user(self, job_db, tmp_path, monkeypatch):
        resume_path = tmp_path / "resume.pdf"
        resume_path.write_bytes(b"%PDF-1.4 test")
        job_db.add_jobs([
            _ready_job(**{
                "Tailored resume url": str(resume_path),
                "Telegram notified": "TRUE",
            }),
            _ready_job(**{
                "Tailored resume url": str(resume_path),
                "Job URL": "https://example.com/2",
                "Company Name": "Beta",
            }),
        ])
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
        monkeypatch.setattr(tg, "resolve_chat_id", lambda: "42")
        monkeypatch.setattr(tg, "send_application_package", MagicMock(return_value=1))

        assert tg.notify_ready_applications(job_db) == 0

    def test_skips_when_disabled(self, job_db, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        assert tg.notify_ready_applications(job_db) == 0

    def test_expired_notified_job_does_not_block_queue(self, job_db, tmp_path, monkeypatch):
        """A notified job whose posting later expired (without a Telegram reply) must not
        permanently stall the one-at-a-time queue."""
        resume_path = tmp_path / "resume.pdf"
        resume_path.write_bytes(b"%PDF-1.4 test")
        job_db.add_jobs([
            _ready_job(**{
                "Tailored resume url": str(resume_path),
                "Telegram notified": "TRUE",
                "Job posting expired": "TRUE",
            }),
            _ready_job(**{
                "Tailored resume url": str(resume_path),
                "Job URL": "https://example.com/2",
                "Company Name": "Beta",
            }),
        ])
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
        monkeypatch.setattr(tg, "resolve_chat_id", lambda: "42")
        monkeypatch.setattr(tg, "send_application_package", MagicMock(return_value=1))
        monkeypatch.setattr(tg, "PENDING_APP_FILE", tmp_path / "pending_app.json")

        assert tg.notify_ready_applications(job_db) == 1

    def test_applied_notified_job_does_not_block_queue(self, job_db, tmp_path, monkeypatch):
        resume_path = tmp_path / "resume.pdf"
        resume_path.write_bytes(b"%PDF-1.4 test")
        job_db.add_jobs([
            _ready_job(**{
                "Tailored resume url": str(resume_path),
                "Telegram notified": "TRUE",
                "Applied": "TRUE",
            }),
            _ready_job(**{
                "Tailored resume url": str(resume_path),
                "Job URL": "https://example.com/2",
                "Company Name": "Beta",
            }),
        ])
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
        monkeypatch.setattr(tg, "resolve_chat_id", lambda: "42")
        monkeypatch.setattr(tg, "send_application_package", MagicMock(return_value=1))
        monkeypatch.setattr(tg, "PENDING_APP_FILE", tmp_path / "pending_app.json")

        assert tg.notify_ready_applications(job_db) == 1

    def test_bad_analysis_notified_job_does_not_block_queue(self, job_db, tmp_path, monkeypatch):
        resume_path = tmp_path / "resume.pdf"
        resume_path.write_bytes(b"%PDF-1.4 test")
        job_db.add_jobs([
            _ready_job(**{
                "Tailored resume url": str(resume_path),
                "Telegram notified": "TRUE",
                "Bad analysis": "TRUE",
            }),
            _ready_job(**{
                "Tailored resume url": str(resume_path),
                "Job URL": "https://example.com/2",
                "Company Name": "Beta",
            }),
        ])
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
        monkeypatch.setattr(tg, "resolve_chat_id", lambda: "42")
        monkeypatch.setattr(tg, "send_application_package", MagicMock(return_value=1))
        monkeypatch.setattr(tg, "PENDING_APP_FILE", tmp_path / "pending_app.json")

        assert tg.notify_ready_applications(job_db) == 1


class TestVeryGoodFitTelegramDeferred:
    def test_no_telegram_until_application_ready(self, job_db, monkeypatch):
        """Very good fit must not notify until resume + cover letter exist."""
        from pipeline.analysis import _apply_analysis_result

        row = _ready_job(**{
            "Tailored resume url": "",
            "Tailored cover letter (to be humanized)": "",
        })
        job_db.add_jobs([row])
        stored = job_db.get_all_jobs()[0]

        monkeypatch.setattr("pipeline.analysis.process_cover_letter", lambda *a, **k: False)
        monkeypatch.setattr("pipeline.analysis.process_resume", lambda *a, **k: False)
        notify_mock = MagicMock(return_value=0)
        monkeypatch.setattr("pipeline.telegram_notify.process_telegram_notifications", notify_mock)

        _apply_analysis_result(
            job_db, stored, "Very good fit", "Strong match.", {}, {"sustainability_criteria": {}}
        )
        notify_mock.assert_not_called()

    def test_telegram_when_application_ready(self, job_db, monkeypatch):
        from pipeline.analysis import _apply_analysis_result

        row = _ready_job()
        job_db.add_jobs([row])
        stored = job_db.get_all_jobs()[0]

        monkeypatch.setattr("pipeline.analysis.process_cover_letter", lambda *a, **k: True)
        monkeypatch.setattr("pipeline.analysis.process_resume", lambda *a, **k: True)
        notify_mock = MagicMock(return_value=1)
        monkeypatch.setattr("pipeline.telegram_notify.process_telegram_notifications", notify_mock)

        _apply_analysis_result(
            job_db, stored, "Very good fit", "Strong match.", {}, {"sustainability_criteria": {}}
        )
        notify_mock.assert_called_once()
