"""Status flag timestamps (Applied at / Expired at / Bad analysis reported at)."""

from utils.schema import (
    JOB_COLUMNS,
    STATUS_TIMESTAMP_FIELDS,
    with_status_timestamps,
)
from local_storage import JobDatabase


def test_status_timestamp_columns_in_schema():
    for ts_col in STATUS_TIMESTAMP_FIELDS.values():
        assert ts_col in JOB_COLUMNS


def test_with_status_timestamps_sets_on_true():
    updates = with_status_timestamps({"Applied": "TRUE", "Fit score": "Good fit"})
    assert updates["Applied"] == "TRUE"
    assert updates["Applied at"].endswith("Z")
    assert "Bad analysis reported at" not in updates
    assert updates["Fit score"] == "Good fit"


def test_with_status_timestamps_clears_on_false():
    updates = with_status_timestamps({
        "Bad analysis": "FALSE",
        "Job posting expired": "",
    })
    assert updates["Bad analysis reported at"] == ""
    assert updates["Expired at"] == ""


def test_update_job_stamps_applied_at(tmp_path):
    db = JobDatabase(str(tmp_path / "jobs.db"), JOB_COLUMNS)
    row = {col: "" for col in JOB_COLUMNS}
    row.update({"Company Name": "Acme", "Job Title": "Eng", "Job URL": "https://example.com/1"})
    db.add_jobs([row])
    job = db.get_all_jobs()[0]

    db.update_job(job["_id"], {"Applied": "TRUE"})
    updated = db.get_job_by_id(job["_id"])
    assert updated["Applied"] == "TRUE"
    assert updated["Applied at"].endswith("Z")

    db.update_job(job["_id"], {"Applied": "FALSE"})
    cleared = db.get_job_by_id(job["_id"])
    assert cleared["Applied"] == "FALSE"
    assert cleared["Applied at"] == ""
