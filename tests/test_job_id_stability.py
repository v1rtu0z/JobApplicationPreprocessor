"""Tests for JobDatabase id stability."""

from local_storage import JobDatabase
from utils.schema import JOB_COLUMNS


def test_job_ids_are_not_realigned_when_gaps_exist(tmp_path):
    db_path = tmp_path / "jobs.db"
    db = JobDatabase(str(db_path), JOB_COLUMNS)
    db.add_jobs([
        {col: "" for col in JOB_COLUMNS} | {"Company Name": "A", "Job Title": "T1", "Job URL": "u1"},
        {col: "" for col in JOB_COLUMNS} | {"Company Name": "B", "Job Title": "T2", "Job URL": "u2"},
        {col: "" for col in JOB_COLUMNS} | {"Company Name": "C", "Job Title": "T3", "Job URL": "u3"},
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
    db2 = JobDatabase(str(db_path), JOB_COLUMNS)
    remaining = db2.get_all_jobs()
    assert [j["_id"] for j in remaining] == [1, 3]
    assert remaining[1]["Company Name"] == "C"
