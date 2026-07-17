"""Telegram bot notifications for ready job applications (Good / Very good fit).

Sends job link, resume PDF, cover letter text + PDF, then asks whether the user
applied and whether the posting expired. Updates the local jobs DB from replies.

Requires TELEGRAM_BOT_TOKEN in .env. Chat ID from TELEGRAM_CHAT_ID or the first
/start message (stored in local_data/telegram_chat_id.txt).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import requests

from dashboard.cover_letter_pdf import cover_letter_text_to_pdf_bytes, safe_cover_letter_pdf_filename
from pipeline.constants import CHECK_SUSTAINABILITY
from pipeline.dashboard_filter import row_passes_default_dashboard_filter
from utils.jd_fit import format_jd_fit_score

GOOD_FIT_SCORES = frozenset({"Good fit", "Very good fit"})
TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
CHAT_ID_FILE = Path("local_data/telegram_chat_id.txt")
PENDING_CO_FILE = Path("local_data/telegram_pending_co.json")
PENDING_APP_FILE = Path("local_data/telegram_pending_application.json")
SKIPPED_CO_FILE = Path("local_data/telegram_co_skipped.json")
MAX_MESSAGE_LEN = 4096
MIN_CO_REPLY_LENGTH = 80
POLL_INTERVAL_SECONDS = 2.0

# (command, short description) — shown in action prompts
_BOT_COMMANDS: dict[str, str] = {
    "status": "queue summary (applications & company overviews)",
    "skipco": "skip company overview and mark whether posting expired",
}


def _commands_hint(*command_keys: str) -> str:
    """Footer listing slash commands relevant to the current prompt."""
    lines = ["", "<b>Commands</b>"]
    for key in command_keys:
        cmd = f"/{key}"
        desc = _BOT_COMMANDS.get(key, "")
        lines.append(f"{cmd} — {desc}" if desc else cmd)
    return "\n".join(lines)


def _all_commands_hint() -> str:
    return _commands_hint("status", "skipco")

_listener_thread: threading.Thread | None = None
_listener_stop = threading.Event()
_db_factory: Callable | None = None
_chat_mismatch_warned = False


def _escape_html(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _token() -> str | None:
    return (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip() or None


def is_enabled() -> bool:
    return bool(_token())


def send_test_message(text: str | None = None) -> str:
    """Send a plain text ping to the configured chat. Returns the chat id used.

    Raises RuntimeError if the bot token or chat id is missing, or if Telegram
    rejects the request.
    """
    if not is_enabled():
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set. Save it in Settings and try again.")
    chat_id = resolve_chat_id()
    if not chat_id:
        raise RuntimeError(
            "No Telegram chat ID yet. Save TELEGRAM_CHAT_ID, or open your bot and send /start, "
            "then try again."
        )
    body = (text or "").strip() or (
        "Telegram test from Job Application Preprocessor Settings.\n"
        "If you see this, bot token and chat ID are working."
    )
    _api("sendMessage", chat_id=chat_id, text=body, disable_web_page_preview=True)
    return str(chat_id)


def resolve_chat_id() -> str | None:
    global _chat_mismatch_warned
    file_chat = None
    if CHAT_ID_FILE.is_file():
        stored = CHAT_ID_FILE.read_text(encoding="utf-8").strip()
        if stored:
            file_chat = stored

    env_chat = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if env_chat and file_chat and env_chat != file_chat:
        if not _chat_mismatch_warned:
            print(
                "Telegram: TELEGRAM_CHAT_ID in .env does not match the chat linked via /start; "
                "using the /start chat. Update .env with your user chat ID (not the bot's ID)."
            )
            _chat_mismatch_warned = True
        return file_chat
    if env_chat:
        return env_chat
    return file_chat


def _save_chat_id(chat_id: str) -> None:
    CHAT_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
    CHAT_ID_FILE.write_text(str(chat_id), encoding="utf-8")


def _sanitize_error(message: str) -> str:
    token = _token() or ""
    if token:
        message = message.replace(token, "[REDACTED]")
    return message


def _api(method: str, **payload) -> dict:
    token = _token()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
    url = TELEGRAM_API.format(token=token, method=method)
    resp = requests.post(url, json=payload, timeout=60)
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if not resp.ok or not data.get("ok"):
        desc = data.get("description") or f"HTTP {resp.status_code}"
        raise RuntimeError(_sanitize_error(desc))
    return data


def _api_multipart(method: str, data: dict, files: dict) -> dict:
    token = _token()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
    url = TELEGRAM_API.format(token=token, method=method)
    resp = requests.post(url, data=data, files=files, timeout=120)
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if not resp.ok or not body.get("ok"):
        desc = body.get("description") or f"HTTP {resp.status_code}"
        raise RuntimeError(_sanitize_error(desc))
    return body


def application_is_ready(row: dict) -> bool:
    if not row_passes_default_dashboard_filter(row):
        return False
    fit = (row.get("Fit score") or "").strip()
    if fit not in GOOD_FIT_SCORES:
        return False
    if (row.get("Applied") or "").strip().upper() == "TRUE":
        return False
    if (row.get("Job posting expired") or "").strip().upper() == "TRUE":
        return False
    if (row.get("Bad analysis") or "").strip().upper() == "TRUE":
        return False
    if not (row.get("Tailored resume url") or "").strip():
        return False
    if not (row.get("Tailored cover letter (to be humanized)") or "").strip():
        return False
    if (row.get("Telegram notified") or "").strip().upper() == "TRUE":
        return False
    return True


def _application_awaiting_user(db) -> bool:
    """True when a sent application is still waiting for apply + expired answers.

    A job whose outcome became known some other way (e.g. expiry detected by the JD crawl,
    or Applied set directly in the dashboard) is treated as resolved even without an explicit
    "Telegram app completed" flag, so a missed/unanswered prompt can't permanently stall the
    one-at-a-time notification queue.
    """
    for row in db.get_all_jobs():
        if (row.get("Telegram notified") or "").upper() != "TRUE":
            continue
        if (row.get("Telegram app completed") or "").upper() == "TRUE":
            continue
        if (row.get("Job posting expired") or "").upper() == "TRUE":
            continue
        if (row.get("Applied") or "").upper() == "TRUE":
            continue
        if (row.get("Bad analysis") or "").upper() == "TRUE":
            continue
        return True
    return False


def _get_next_ready_application(db) -> dict | None:
    db.sort_by([
        ("Fit score enum", False),
        ("JD fit score", False),
        ("Easy apply", False),
        ("Date posted", False),
        ("Location Priority", True),
    ])
    for row in db.get_all_jobs():
        if application_is_ready(row):
            return row
    return None


def _load_pending_application_job_id() -> int | None:
    data = _load_json_file(PENDING_APP_FILE)
    job_id = data.get("job_id")
    return int(job_id) if job_id is not None else None


def _set_pending_application_job_id(job_id: int) -> None:
    _save_json_file(
        PENDING_APP_FILE,
        {"job_id": job_id, "sent_at": datetime.now(timezone.utc).isoformat()},
    )


def _clear_pending_application_job_id() -> None:
    if PENDING_APP_FILE.is_file():
        try:
            PENDING_APP_FILE.unlink()
        except OSError:
            pass


def _job_link_footer(row: dict) -> str:
    """HTML footer with job link — appended to every text message so the link stays visible."""
    job_url = (row.get("Job URL") or "").strip()
    if not job_url:
        return ""
    return f'\n\n🔗 <a href="{_escape_html(job_url)}">Job posting</a>'


def _build_summary_text(row: dict) -> str:
    company = _escape_html(row.get("Company Name", "").strip())
    title = _escape_html(row.get("Job Title", "").strip())
    location = _escape_html(row.get("Location", "").strip())
    fit = _escape_html(row.get("Fit score", "").strip())
    lines = [
        "📋 <b>Application ready</b>",
        "",
        f"🏢 <b>{company}</b>",
        f"💼 {title}",
    ]
    if location:
        lines.append(f"📍 {location}")
    if fit:
        lines.append(f"⭐ {fit}")
    return "\n".join(lines) + _job_link_footer(row)


def _split_text(text: str, limit: int = MAX_MESSAGE_LEN, reserve: int = 0) -> list[str]:
    effective = max(200, limit - reserve)
    if len(text) <= effective:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        chunks.append(text[start : start + effective])
        start += effective
    return chunks


def _job_fingerprint(row: dict) -> str:
    """Short stable id for Telegram callbacks (survives accidental DB id remapping)."""
    raw = "\n".join(
        [
            (row.get("Job URL") or "").strip(),
            (row.get("Company Name") or "").strip(),
            (row.get("Job Title") or "").strip(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]


def _find_job_by_fingerprint(db, fingerprint: str) -> dict | None:
    for row in db.get_all_jobs():
        if _job_fingerprint(row) == fingerprint:
            return row
    return None


def _apply_prompt_keyboard(job_id: int, fingerprint: str) -> dict:
    return {
        "inline_keyboard": [
            [{"text": "Yes, I applied", "callback_data": f"q1:{job_id}:{fingerprint}:yes"}],
            [
                {"text": "Not yet", "callback_data": f"q1:{job_id}:{fingerprint}:no"},
                {"text": "Bad analysis", "callback_data": f"q1:{job_id}:{fingerprint}:bad"},
            ],
        ]
    }


def _apply_prompt_text(footer: str) -> str:
    return "Did you apply to this job? (use the buttons below)" + footer


def _send_apply_prompt(chat_id: str, row: dict) -> int | None:
    """Send the apply prompt with inline buttons as a standalone text message."""
    job_id = row.get("_id")
    if job_id is None:
        raise RuntimeError("Job row missing _id for Telegram apply prompt")

    footer = _job_link_footer(row)
    text = _apply_prompt_text(footer)
    keyboard = _apply_prompt_keyboard(job_id, _job_fingerprint(row))

    prompt = _api(
        "sendMessage",
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    return prompt["result"]["message_id"]


def _read_resume_bytes(resume_path: str) -> bytes | None:
    path = Path(resume_path)
    if not path.is_file() and resume_path.startswith("local_data/"):
        path = Path(".") / resume_path
    if not path.is_file():
        return None
    return path.read_bytes()


def send_application_package(chat_id: str, row: dict) -> int | None:
    """Send summary, cover letter text, resume PDF, and cover letter PDF. Returns prompt message_id."""
    job_id = row.get("_id")
    if job_id is None:
        raise RuntimeError("Job row missing _id for Telegram application package")

    summary = _build_summary_text(row)
    _api("sendMessage", chat_id=chat_id, text=summary, parse_mode="HTML", disable_web_page_preview=False)

    cl_text = row.get("Tailored cover letter (to be humanized)", "").strip()
    from utils.cover_letter_format import normalize_cover_letter_body

    cl_text = normalize_cover_letter_body(cl_text)
    footer = _job_link_footer(row)
    apply_caption = _apply_prompt_text(footer).lstrip("\n")
    keyboard = _apply_prompt_keyboard(job_id, _job_fingerprint(row))

    if cl_text:
        header = "📝 <b>Cover letter</b>\n\n"
        chunks = _split_text(header + _escape_html(cl_text), reserve=len(footer) + 4)
        for i, chunk in enumerate(chunks):
            if i == len(chunks) - 1:
                chunk = chunk + footer
            _api("sendMessage", chat_id=chat_id, text=chunk, parse_mode="HTML")

    company = row.get("Company Name", "")
    title = row.get("Job Title", "")
    resume_path = row.get("Tailored resume url", "")
    resume_bytes = _read_resume_bytes(resume_path)
    link_only_caption = footer.lstrip("\n") if footer else None

    if resume_bytes and cl_text:
        resume_name = Path(resume_path).name or "resume.pdf"
        data = {"chat_id": chat_id}
        if link_only_caption:
            data["caption"] = link_only_caption
            data["parse_mode"] = "HTML"
        _api_multipart(
            "sendDocument",
            data,
            {"document": (resume_name, resume_bytes, "application/pdf")},
        )

        cl_pdf_name = safe_cover_letter_pdf_filename(company, title)
        cl_pdf_bytes = cover_letter_text_to_pdf_bytes(cl_text)
        data = {
            "chat_id": chat_id,
            "caption": apply_caption,
            "parse_mode": "HTML",
            "reply_markup": json.dumps(keyboard),
        }
        result = _api_multipart(
            "sendDocument",
            data,
            {"document": (cl_pdf_name, cl_pdf_bytes, "application/pdf")},
        )
        return result.get("result", {}).get("message_id")

    if resume_bytes:
        resume_name = Path(resume_path).name or "resume.pdf"
        data = {
            "chat_id": chat_id,
            "caption": apply_caption,
            "parse_mode": "HTML",
            "reply_markup": json.dumps(keyboard),
        }
        result = _api_multipart(
            "sendDocument",
            data,
            {"document": (resume_name, resume_bytes, "application/pdf")},
        )
        return result.get("result", {}).get("message_id")

    return _send_apply_prompt(chat_id, row)


def _expired_keyboard(job_id: int, fingerprint: str, *, stage: str = "q2") -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "Yes, expired", "callback_data": f"{stage}:{job_id}:{fingerprint}:yes"},
                {"text": "Still active", "callback_data": f"{stage}:{job_id}:{fingerprint}:no"},
            ]
        ]
    }


def _authorized_chat(chat_id: str | int) -> bool:
    allowed = resolve_chat_id()
    if not allowed:
        return True
    return str(chat_id) == str(allowed)


def _parse_callback(data: str) -> tuple[str, int, str, str | None] | None:
    """Parse callback_data into (stage, job_id, answer, fingerprint).

    New format: ``q1:{id}:{fingerprint}:{answer}``
    Legacy format (pre-fingerprint): ``q1:{id}:{answer}``
    """
    parts = (data or "").split(":")
    if len(parts) == 3:
        stage, job_id_s, answer = parts
        fingerprint = None
    elif len(parts) == 4:
        stage, job_id_s, fingerprint, answer = parts
    else:
        return None
    if stage not in {"q1", "q2", "qco"}:
        return None
    try:
        job_id = int(job_id_s)
    except ValueError:
        return None
    answer = answer.lower()
    if stage == "q1" and answer not in {"yes", "no", "bad"}:
        return None
    if stage in {"q2", "qco"} and answer not in {"yes", "no"}:
        return None
    if fingerprint is not None and (len(fingerprint) != 8 or any(c not in "0123456789abcdef" for c in fingerprint)):
        return None
    return stage, job_id, answer, fingerprint


def _resolve_callback_job(db, job_id: int, fingerprint: str | None) -> dict | None:
    """Load the job for a callback, recovering via fingerprint if ids were remapped."""
    job = db.get_job_by_id(job_id)
    if fingerprint is None:
        return job
    if job is not None and _job_fingerprint(job) == fingerprint:
        return job
    return _find_job_by_fingerprint(db, fingerprint)


def _advance_application_queue(db, chat_id: str | int) -> None:
    """Send the next ready application once the current one is fully resolved."""
    if not _application_awaiting_user(db):
        if notify_ready_applications(db) > 0:
            _api(
                "sendMessage",
                chat_id=chat_id,
                text="Next application is ready above — take your time with one at a time.",
            )


def _complete_application_prompt(chat_id: str | int, message_id: int | None, label: str) -> None:
    if not message_id:
        return
    text = f"Did you apply? → {label}"
    # Apply buttons sit on either a text prompt or a cover-letter PDF caption.
    for method, payload in (
        ("editMessageText", {"text": text}),
        ("editMessageCaption", {"caption": text}),
        ("editMessageReplyMarkup", {"reply_markup": json.dumps({"inline_keyboard": []})}),
    ):
        try:
            _api(method, chat_id=chat_id, message_id=message_id, **payload)
            return
        except Exception:
            continue


def handle_callback_query(callback_query: dict, db) -> None:
    chat = callback_query.get("message", {}).get("chat", {})
    chat_id = chat.get("id")
    if chat_id is None or not _authorized_chat(chat_id):
        return

    data = callback_query.get("data", "")
    parsed = _parse_callback(data)
    callback_id = callback_query.get("id")
    if not parsed:
        if callback_id:
            _api("answerCallbackQuery", callback_query_id=callback_id, text="Unknown action")
        return

    stage, job_id, answer, fingerprint = parsed
    job = _resolve_callback_job(db, job_id, fingerprint)
    if not job:
        if callback_id:
            _api(
                "answerCallbackQuery",
                callback_query_id=callback_id,
                text="Job not found — wait for a fresh notification",
            )
        return

    job_id = int(job["_id"])
    yes = answer == "yes"
    company = job.get("Company Name", "")
    title = job.get("Job Title", "")
    fingerprint = _job_fingerprint(job)

    if stage == "q1":
        msg = callback_query.get("message", {})
        msg_id = msg.get("message_id")

        if answer == "yes":
            db.update_job(job_id, {"Applied": "TRUE", "Telegram app completed": "TRUE"})
            if callback_id:
                _api("answerCallbackQuery", callback_query_id=callback_id, text="Marked as applied.")
            _complete_application_prompt(chat_id, msg_id, "Yes")
            if _load_pending_application_job_id() == job_id:
                _clear_pending_application_job_id()
            _api(
                "sendMessage",
                chat_id=chat_id,
                text=(
                    f"✅ Marked <b>{_escape_html(company)} — {_escape_html(title)}</b> as applied."
                    + _job_link_footer(job)
                ),
                parse_mode="HTML",
            )
            _advance_application_queue(db, chat_id)
            return

        if answer == "bad":
            db.update_job(job_id, {
                "Bad analysis": "TRUE",
                "Telegram app completed": "TRUE",
                "Telegram notified": "",
            })
            if callback_id:
                _api("answerCallbackQuery", callback_query_id=callback_id, text="Marked as bad analysis.")
            _complete_application_prompt(chat_id, msg_id, "Bad analysis")
            if _load_pending_application_job_id() == job_id:
                _clear_pending_application_job_id()
            _api(
                "sendMessage",
                chat_id=chat_id,
                text=(
                    f"⚠️ Marked <b>{_escape_html(company)} — {_escape_html(title)}</b> as "
                    "<b>bad analysis</b>. The fit score will be re-run on the next pipeline cycle."
                    + _job_link_footer(job)
                ),
                parse_mode="HTML",
            )
            _advance_application_queue(db, chat_id)
            return

        if callback_id:
            _api("answerCallbackQuery", callback_query_id=callback_id, text="Noted — not applied yet.")
        _complete_application_prompt(chat_id, msg_id, "Not yet")

        _api(
            "sendMessage",
            chat_id=chat_id,
            text=(
                f"Is the job posting for <b>{_escape_html(company)} — "
                f"{_escape_html(title)}</b> expired? (use the buttons below)"
                + _job_link_footer(job)
            ),
            parse_mode="HTML",
            reply_markup=_expired_keyboard(job_id, fingerprint),
        )
        return

    if stage == "qco":
        updates = {}
        if yes:
            updates["Job posting expired"] = "TRUE"
        db.update_job(job_id, updates)
        if callback_id:
            expired_label = "Marked as expired." if yes else "Noted — still active."
            _api("answerCallbackQuery", callback_query_id=callback_id, text=expired_label)

        msg = callback_query.get("message", {})
        if msg.get("message_id"):
            try:
                _api(
                    "editMessageText",
                    chat_id=chat_id,
                    message_id=msg["message_id"],
                    text=f"Posting expired? → {'Yes' if yes else 'Still active'}",
                )
            except Exception:
                pass

        detail = " (expired ✓)" if yes else ""
        _api(
            "sendMessage",
            chat_id=chat_id,
            text=(
                f"✅ Skipped company overview for <b>{_escape_html(company)} — "
                f"{_escape_html(title)}</b>{detail}. I'll prompt for the next job soon."
                + _commands_hint("status")
            ),
            parse_mode="HTML",
        )
        prompt_manual_co_if_needed(db)
        return

    updates = {}
    if yes:
        updates["Job posting expired"] = "TRUE"
    updates["Telegram app completed"] = "TRUE"
    db.update_job(job_id, updates)
    if _load_pending_application_job_id() == job_id:
        _clear_pending_application_job_id()
    if callback_id:
        expired_label = "Marked as expired." if yes else "Noted — still active."
        _api("answerCallbackQuery", callback_query_id=callback_id, text=expired_label)

    msg = callback_query.get("message", {})
    if msg.get("message_id"):
        try:
            _api(
                "editMessageText",
                chat_id=chat_id,
                message_id=msg["message_id"],
                text=f"Posting expired? → {'Yes' if yes else 'Still active'}",
            )
        except Exception:
            pass

    summary_bits = []
    refreshed = db.get_job_by_id(job_id) or {}
    if refreshed.get("Applied") == "TRUE":
        summary_bits.append("applied ✓")
    if refreshed.get("Job posting expired") == "TRUE":
        summary_bits.append("expired ✓")
    detail = f" ({', '.join(summary_bits)})" if summary_bits else ""
    _api(
        "sendMessage",
        chat_id=chat_id,
        text=(
            f"✅ Updated <b>{_escape_html(company)} — {_escape_html(title)}</b>{detail} in the database."
            + _job_link_footer(refreshed)
        ),
        parse_mode="HTML",
    )
    if not _application_awaiting_user(db):
        _advance_application_queue(db, chat_id)
    else:
        awaiting = sum(
            1
            for j in db.get_all_jobs()
            if (j.get("Telegram notified") or "").upper() == "TRUE"
            and (j.get("Telegram app completed") or "").upper() != "TRUE"
        )
        if awaiting:
            print(f"Telegram: {awaiting} application(s) still awaiting your response.")


def handle_incoming_message(message: dict, db) -> None:
    chat_id = message.get("chat", {}).get("id")
    text = (message.get("text") or "").strip()
    if chat_id is None:
        return

    if text.startswith("/start"):
        _save_chat_id(str(chat_id))
        _api(
            "sendMessage",
            chat_id=chat_id,
            text=(
                "Job Application Preprocessor bot is connected.\n\n"
                f"Your chat ID: <code>{chat_id}</code>\n"
                "Add this to .env as TELEGRAM_CHAT_ID (your ID, not the bot's).\n\n"
                "You'll receive notifications when a Good or Very good fit application "
                "is ready (resume + cover letter). I send <b>one at a time</b> — tap "
                "<b>Yes, I applied</b> when done, <b>Not yet</b> if you still plan to apply "
                "(I'll ask whether the posting is still active), or <b>Bad analysis</b> if "
                "the fit score was wrong and you won't apply. "
                "Each message includes the job link at the bottom.\n\n"
                "When a job needs a company overview from LinkedIn, I'll ask for one "
                "job at a time (highest JD fit first). Reply with the About text, "
                "or use /skipco to skip and say whether the posting is expired."
                + _all_commands_hint()
            ),
            parse_mode="HTML",
        )
        return

    if not _authorized_chat(chat_id):
        return

    if text.startswith("/skipco"):
        _handle_skip_co_prompt(chat_id, db)
        return

    if text.startswith("/status"):
        jobs = db.get_all_jobs()
        ready = sum(1 for j in jobs if application_is_ready(j))
        notified = sum(1 for j in jobs if (j.get("Telegram notified") or "").upper() == "TRUE")
        awaiting_app = sum(
            1
            for j in jobs
            if (j.get("Telegram notified") or "").upper() == "TRUE"
            and (j.get("Telegram app completed") or "").upper() != "TRUE"
        )
        pending_co = _load_pending_co_job_id()
        co_needed = sum(1 for j in jobs if _job_needs_manual_co(j))
        _api(
            "sendMessage",
            chat_id=chat_id,
            text=(
                f"Applications ready to send: {ready}\n"
                f"Already sent via Telegram: {notified}\n"
                f"Awaiting your apply/expired answers: {awaiting_app}\n"
                f"Jobs needing company overview: {co_needed}\n"
                f"Awaiting your CO reply: {'yes' if pending_co else 'no'}"
                + (_commands_hint("skipco") if pending_co else "")
            ),
            parse_mode="HTML",
        )
        return

    if text.startswith("/"):
        _api(
            "sendMessage",
            chat_id=chat_id,
            text="Unknown command." + _all_commands_hint(),
            parse_mode="HTML",
        )
        return

    pending_job_id = _load_pending_co_job_id()
    if pending_job_id is not None:
        _handle_co_text_reply(chat_id, db, pending_job_id, text)


def notify_ready_applications(db) -> int:
    """Send one Telegram notification for the next ready application (if none awaiting response)."""
    if not is_enabled():
        return 0

    chat_id = resolve_chat_id()
    if not chat_id:
        print("Telegram: no chat ID yet — send /start to your bot from Telegram.")
        return 0

    if _application_awaiting_user(db):
        return 0

    row = _get_next_ready_application(db)
    if not row:
        return 0

    company = row.get("Company Name", "")
    title = row.get("Job Title", "")
    try:
        send_application_package(chat_id, row)
        db.update_job(row["_id"], {"Telegram notified": "TRUE"})
        _set_pending_application_job_id(row["_id"])
        print(f"Telegram: sent application package for {title} @ {company}")
        return 1
    except Exception as e:
        print(f"Telegram: failed to notify {title} @ {company}: {e}")
        return 0


def _poll_updates(db, offset: int | None) -> int | None:
    payload: dict = {"timeout": 30, "allowed_updates": ["message", "callback_query"]}
    if offset is not None:
        payload["offset"] = offset
    token = _token()
    if not token:
        return offset
    url = TELEGRAM_API.format(token=token, method="getUpdates")
    try:
        resp = requests.post(url, json=payload, timeout=35)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"Telegram listener error: {e}")
        return offset

    if not data.get("ok"):
        print(f"Telegram listener error: {data.get('description', 'unknown')}")
        return offset

    for update in data.get("result", []):
        offset = update["update_id"] + 1
        if "callback_query" in update:
            try:
                handle_callback_query(update["callback_query"], db)
            except Exception as e:
                print(f"Telegram callback error: {e}")
        elif "message" in update:
            try:
                handle_incoming_message(update["message"], db)
            except Exception as e:
                print(f"Telegram message error: {e}")
    return offset


def _listener_loop(db_factory: Callable) -> None:
    offset: int | None = None
    while not _listener_stop.is_set():
        db = db_factory()
        offset = _poll_updates(db, offset)
        if _listener_stop.wait(POLL_INTERVAL_SECONDS):
            break


def start_update_listener(db_factory: Callable) -> None:
    """Start a daemon thread that handles /start and inline-button replies."""
    global _listener_thread, _db_factory
    if not is_enabled():
        return
    if _listener_thread and _listener_thread.is_alive():
        return
    _db_factory = db_factory
    _listener_stop.clear()
    _listener_thread = threading.Thread(
        target=_listener_loop,
        args=(db_factory,),
        name="telegram-update-listener",
        daemon=True,
    )
    _listener_thread.start()
    print("Telegram: update listener started (handles /start and application replies).")


def stop_update_listener() -> None:
    _listener_stop.set()


# ---------------------------------------------------------------------------
# Manual company overview prompts (one job at a time, highest JD fit first)
# ---------------------------------------------------------------------------


def _job_needs_manual_co(row: dict) -> bool:
    if not CHECK_SUSTAINABILITY:
        return False
    if not row_passes_default_dashboard_filter(row):
        return False
    if not row.get("Job Title"):
        return False
    if row.get("Applied") == "TRUE" or row.get("Job posting expired") == "TRUE":
        return False
    if not (row.get("Job Description") or "").strip():
        return False
    if (row.get("Fit score") or "").strip():
        return False
    return not (row.get("Company overview") or "").strip()


def _load_json_file(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_json_file(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _load_pending_co_job_id() -> int | None:
    data = _load_json_file(PENDING_CO_FILE)
    job_id = data.get("job_id")
    return int(job_id) if job_id is not None else None


def _set_pending_co_job_id(job_id: int) -> None:
    _save_json_file(
        PENDING_CO_FILE,
        {"job_id": job_id, "prompted_at": datetime.now(timezone.utc).isoformat()},
    )


def _clear_pending_co_job_id() -> None:
    if PENDING_CO_FILE.is_file():
        try:
            PENDING_CO_FILE.unlink()
        except OSError:
            pass


def _load_skipped_co_job_ids() -> set[int]:
    data = _load_json_file(SKIPPED_CO_FILE)
    return {int(x) for x in data.get("skipped_job_ids", [])}


def _skip_co_job_id(job_id: int) -> None:
    skipped = _load_skipped_co_job_ids()
    skipped.add(job_id)
    _save_json_file(SKIPPED_CO_FILE, {"skipped_job_ids": sorted(skipped)})


def _get_next_manual_co_job(db) -> dict | None:
    db.sort_by([
        ("JD fit score", False),
        ("Fit score enum", False),
        ("Easy apply", False),
        ("Date posted", False),
        ("Location Priority", True),
    ])
    skipped = _load_skipped_co_job_ids()
    for row in db.get_all_jobs():
        if row["_id"] in skipped:
            continue
        if _job_needs_manual_co(row):
            return row
    return None


def _build_co_prompt_text(row: dict) -> str:
    company = _escape_html(row.get("Company Name", "").strip())
    title = _escape_html(row.get("Job Title", "").strip())
    location = _escape_html(row.get("Location", "").strip())
    jd_fit = format_jd_fit_score(row.get("JD fit score"))
    job_url = (row.get("Job URL") or "").strip()
    company_url = (row.get("Company URL") or "").strip()

    lines = [
        "🏢 <b>Company overview needed</b>",
        "",
        f"<b>{company}</b> — {title}",
    ]
    if location:
        lines.append(f"📍 {location}")
    if jd_fit:
        lines.append(f"⭐ JD fit score: {jd_fit}/10")
    if job_url:
        lines.append(f'🔗 <a href="{_escape_html(job_url)}">Job posting</a>')
    if company_url:
        lines.append(f'🏛 <a href="{_escape_html(company_url)}">Company page</a>')

    lines.extend([
        "",
        "Open the company on LinkedIn (from the job or company link), copy the "
        "<b>About</b> section, and reply here with the text.",
        _commands_hint("skipco", "status"),
    ])
    return "\n".join(lines)


def prompt_manual_co_if_needed(db) -> bool:
    """Prompt for one manual company overview if none is awaiting a reply."""
    if not is_enabled() or not CHECK_SUSTAINABILITY:
        return False

    chat_id = resolve_chat_id()
    if not chat_id:
        return False

    pending_id = _load_pending_co_job_id()
    if pending_id is not None:
        pending_job = db.get_job_by_id(pending_id)
        if pending_job and _job_needs_manual_co(pending_job):
            return False
        _clear_pending_co_job_id()

    job = _get_next_manual_co_job(db)
    if not job:
        return False

    try:
        _api("sendMessage", chat_id=chat_id, text=_build_co_prompt_text(job), parse_mode="HTML")
        _set_pending_co_job_id(job["_id"])
        print(
            f"Telegram: requested company overview for {job.get('Job Title')} "
            f"@ {job.get('Company Name')} (JD fit {format_jd_fit_score(job.get('JD fit score')) or '?'})"
        )
        return True
    except Exception as e:
        print(f"Telegram: failed to prompt for company overview: {e}")
        return False


def _handle_co_text_reply(chat_id: str | int, db, job_id: int, text: str) -> None:
    if len(text.strip()) < MIN_CO_REPLY_LENGTH:
        _api(
            "sendMessage",
            chat_id=chat_id,
            text=(
                f"That looks too short for a company overview (minimum {MIN_CO_REPLY_LENGTH} "
                "characters). Please paste the full LinkedIn About section."
                + _commands_hint("skipco", "status")
            ),
            parse_mode="HTML",
        )
        return

    job = db.get_job_by_id(job_id)
    if not job or not _job_needs_manual_co(job):
        _clear_pending_co_job_id()
        _api("sendMessage", chat_id=chat_id, text="That company overview request is no longer needed.")
        return

    db.update_job(job_id, {"Company overview": text.strip()})
    _clear_pending_co_job_id()
    company = job.get("Company Name", "")
    title = job.get("Job Title", "")
    _api(
        "sendMessage",
        chat_id=chat_id,
        text=(
            f"✅ Saved company overview for <b>{_escape_html(company)} — "
            f"{_escape_html(title)}</b>. Analysis will run on the next pipeline cycle."
        ),
        parse_mode="HTML",
    )
    print(f"Telegram: saved company overview for {title} @ {company}")


def _handle_skip_co_prompt(chat_id: str | int, db) -> None:
    pending_id = _load_pending_co_job_id()
    if pending_id is None:
        _api(
            "sendMessage",
            chat_id=chat_id,
            text="No company overview request is pending." + _commands_hint("status"),
            parse_mode="HTML",
        )
        return

    job = db.get_job_by_id(pending_id)
    _skip_co_job_id(pending_id)
    _clear_pending_co_job_id()
    if not job:
        _api(
            "sendMessage",
            chat_id=chat_id,
            text="Skipped. I'll prompt for the next job soon." + _commands_hint("status"),
            parse_mode="HTML",
        )
        return

    company = _escape_html(job.get("Company Name", ""))
    title = _escape_html(job.get("Job Title", ""))
    _api(
        "sendMessage",
        chat_id=chat_id,
        text=(
            f"Skipped company overview for <b>{company} — {title}</b>.\n\n"
            "Is the job posting expired? (use the buttons below)"
        ),
        parse_mode="HTML",
        reply_markup=_expired_keyboard(pending_id, _job_fingerprint(job), stage="qco"),
    )

