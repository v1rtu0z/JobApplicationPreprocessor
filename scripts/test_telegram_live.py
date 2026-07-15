#!/usr/bin/env python3
"""Live Telegram test with dummy application data.

Usage (from project root):
  python scripts/test_telegram_live.py

Requires TELEGRAM_BOT_TOKEN in .env. If TELEGRAM_CHAT_ID is not set, send /start
to your bot in Telegram first, then re-run this script.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from local_storage import JobDatabase, save_resume_local
from utils.schema import SHEET_HEADER
from utils.telegram_bot import (
    is_enabled,
    notify_ready_applications,
    resolve_chat_id,
    start_update_listener,
)


DUMMY_COMPANY = "Telegram Test Co"
DUMMY_TITLE = "Senior Dummy Engineer"
DUMMY_URL = "https://example.com/jobs/telegram-live-test"


def _minimal_pdf() -> bytes:
    return b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/MediaBox[0 0 200 200]/Parent 2 0 R>>endobj
xref
0 4
0000000000 65535 f 
0000000009 00000 n 
0000000052 00000 n 
0000000101 00000 n 
trailer<</Size 4/Root 1 0 R>>
startxref
178
%%EOF
"""


def _ensure_dummy_job(db: JobDatabase) -> int:
    for job in db.get_all_jobs():
        if job.get("Job URL") == DUMMY_URL and job.get("Company Name") == DUMMY_COMPANY:
            db.update_job(job["_id"], {
                "Telegram notified": "",
                "Applied": "FALSE",
                "Job posting expired": "FALSE",
            })
            return job["_id"]

    resume_path = save_resume_local(_minimal_pdf(), "telegram_test_resume.pdf")
    cl_text = (
        "Dear Hiring Team,\n\n"
        "This is a *live test* cover letter from the Job Application Preprocessor.\n\n"
        "If you received this message with the resume PDF attached, Telegram notifications "
        "are working correctly.\n\n"
        "Best regards,\nTest User"
    )
    row = {col: "" for col in SHEET_HEADER}
    row.update({
        "Company Name": DUMMY_COMPANY,
        "Job Title": DUMMY_TITLE,
        "Location": "Remote (test)",
        "Job URL": DUMMY_URL,
        "Fit score": "Very good fit",
        "Fit score enum": "5",
        "Tailored resume url": resume_path,
        "Tailored cover letter (to be humanized)": cl_text,
        "Applied": "FALSE",
        "Job posting expired": "FALSE",
        "Telegram notified": "",
    })
    db.add_jobs([row])
    return db.get_all_jobs()[-1]["_id"]


def main() -> int:
    if not is_enabled():
        print("TELEGRAM_BOT_TOKEN is not set in .env — add it and retry.")
        return 1

    db = JobDatabase(str(ROOT / "local_data" / "jobs.db"), SHEET_HEADER)
    start_update_listener(lambda: db)

    chat_id = resolve_chat_id()
    if not chat_id:
        print("No chat ID yet. Open Telegram, send /start to your bot, wait a few seconds...")
        for _ in range(15):
            time.sleep(2)
            chat_id = resolve_chat_id()
            if chat_id:
                break
        if not chat_id:
            print("Still no chat ID. Send /start to the bot and run this script again.")
            return 1

    job_id = _ensure_dummy_job(db)
    print(f"Prepared dummy job id={job_id}. Sending notification to chat {chat_id}...")
    sent = notify_ready_applications(db)
    print(f"Sent {sent} notification(s).")
    print("Check Telegram — you should see the job link, cover letter text, resume PDF, and cover letter PDF.")
    print("Tap the inline buttons to test DB updates (Applied / expired).")
    print("Listener runs for 120s to capture your replies...")
    time.sleep(120)
    updated = db.get_job_by_id(job_id)
    if updated:
        print(f"Final DB state: Applied={updated.get('Applied')!r}, "
              f"Job posting expired={updated.get('Job posting expired')!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
