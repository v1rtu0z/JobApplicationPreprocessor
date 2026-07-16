"""Tests for JobDatabase id stability."""

from local_storage import JobDatabase
from utils.schema import SHEET_HEADER


def test_job_ids_are_not_realigned_when_gaps_exist(tmp_path):
    db_path = tmp_path / "jobs.db"
    db = JobDatabase(str(db_path), SHEET_HEADER)
    db.add_jobs([
        {col: "" for col in SHEET_HEADER} | {"Company Name": "A", "Job Title": "T1", "Job URL": "u1"},
        {col: "" for col in SHEET_HEADER} | {"Company Name": "B", "Job Title": "T2", "Job URL": "u2"},
        {col: "" for col in SHEET_HEADER} | {"Company Name": "C", "Job Title": "T3", "Job URL": "u3"},
    ])
    jobs = db.get_all_jobs()
    assert [j["_id"] for j in jobs] == [1, 2, 3]

    # Delete middle row to create an id gap (same as expired/cleanup deletes).
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.execute("DELETE FROM jobs WHERE id = 2")
    conn.commit()
    conn.close()

    # Re-open: previously this renumbered ids and broke Telegram callbacks.
    db2 = JobDatabase(str(db_path), SHEET_HEADER)
    remaining = db2.get_all_jobs()
    assert [j["_id"] for j in remaining] == [1, 3]
    assert remaining[1]["Company Name"] == "C"
