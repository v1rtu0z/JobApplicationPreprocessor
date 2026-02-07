"""JobRepository: DAO for job storage (wraps JobDatabase / sheet)."""

from typing import Any

from utils.schema import SHEET_HEADER

from .models import Job


class JobRepository:
    """
    Repository for job persistence. Wraps the existing job store (JobDatabase)
    and exposes a consistent interface. Supports both dict rows and Job models
    for incremental migration.
    """

    def __init__(self, job_store: Any) -> None:
        """
        Args:
            job_store: Object with get_all_records(), add_jobs(), update_job_by_key(), etc.
                       Typically local_storage.JobDatabase.
        """
        self._store = job_store

    @property
    def store(self) -> Any:
        """Underlying store for legacy code that needs it."""
        return self._store

    def get_all_records(self) -> list[dict[str, str]]:
        """Return all jobs as list of row dicts (no _id)."""
        return self._store.get_all_records()

    def get_all_jobs(self) -> list[Job]:
        """Return all jobs as Job domain models."""
        records = self.get_all_records()
        return [Job.from_row(r) for r in records]

    def get_existing_job_keys(self) -> set[str]:
        """Return set of 'Job Title @ Company Name' for deduplication."""
        if hasattr(self._store, "get_all_records"):
            rows = self._store.get_all_records()
        else:
            rows = self._store.get_all_jobs()
        keys = set()
        for row in rows:
            title = (row.get("Job Title") or "").strip()
            company = (row.get("Company Name") or "").strip()
            if title and company:
                keys.add(f"{title} @ {company}")
        return keys

    def add_jobs(self, jobs: list[dict[str, str]]) -> None:
        """Append jobs from row dicts (keys = SHEET_HEADER column names)."""
        if not jobs:
            return
        if hasattr(self._store, "add_jobs"):
            self._store.add_jobs(jobs)
        elif hasattr(self._store, "append_rows"):
            rows = [[job.get(col, "") for col in SHEET_HEADER] for job in jobs]
            self._store.append_rows(rows)

    def add_jobs_from_models(self, jobs: list[Job]) -> None:
        """Append jobs from domain models."""
        rows = [j.to_row() for j in jobs]
        self.add_jobs(rows)

    def update_by_key(self, job_url: str, company_name: str, updates: dict[str, str]) -> int:
        """Update one job by (job_url, company_name). Returns number of rows updated."""
        return self._store.update_job_by_key(job_url, company_name, updates)

    def update_job(self, job: Job, updates: dict[str, str]) -> int:
        """Update job by its natural key. Returns number of rows updated."""
        return self.update_by_key(job.job_url, job.company_name, updates)
