"""JobAnalysisService: fit-score analysis via LLM (delegates to pipeline)."""

from typing import Any

from ..repository import JobRepository


class JobAnalysisService:
    """Service for analyzing job fit. Uses JobRepository for storage."""

    def __init__(self, repository: JobRepository) -> None:
        self._repo = repository

    @property
    def repository(self) -> JobRepository:
        return self._repo

    def analyze_one(self, job_row: dict[str, str], resume_json: dict[str, Any]) -> str | None:
        """
        Analyze a single job and persist fit score. Returns fit score if done, None if skipped.
        job_row: full row dict (e.g. from get_all_records).
        """
        from pipeline.analysis import analyze_single_job
        sheet = self._repo.store
        return analyze_single_job(sheet, job_row, resume_json)

    def analyze_all(
        self,
        resume_json: dict[str, Any],
        target_jobs: list[tuple[str, str]] | None = None,
    ) -> int:
        """
        Analyze all unprocessed jobs. Returns count of jobs analyzed.
        target_jobs: optional list of (job_url, company_name) to limit scope.
        """
        from pipeline.analysis import analyze_all_jobs
        sheet = self._repo.store
        return analyze_all_jobs(sheet, resume_json, target_jobs=target_jobs)
