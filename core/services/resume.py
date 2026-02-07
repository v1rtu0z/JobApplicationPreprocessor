"""ResumeGenerationService: tailored resume and cover letter generation."""

from typing import Any

from ..repository import JobRepository


class ResumeGenerationService:
    """Service for generating tailored resumes and cover letters."""

    def __init__(self, repository: JobRepository) -> None:
        self._repo = repository

    @property
    def repository(self) -> JobRepository:
        return self._repo

    def process_cover_letter(
        self,
        job_row: dict[str, str],
        resume_json: dict[str, Any],
    ) -> bool:
        """Generate or regenerate cover letter for one job. Returns True if work was done."""
        from pipeline.resumes import process_cover_letter
        sheet = self._repo.store
        return process_cover_letter(sheet, job_row, resume_json)

    def process_resume(
        self,
        job_row: dict[str, str],
        resume_json: dict[str, Any],
    ) -> bool:
        """Generate or regenerate tailored resume for one job. Returns True if work was done."""
        from pipeline.resumes import process_resume
        sheet = self._repo.store
        return process_resume(sheet, job_row, resume_json)

    def process_resumes_and_cover_letters(
        self,
        resume_json: dict[str, Any],
        target_jobs: list[tuple[str, str]] | None = None,
    ) -> int:
        """Process resumes and cover letters for good-fit jobs. Returns count processed."""
        from pipeline.resumes import process_resumes_and_cover_letters
        sheet = self._repo.store
        return process_resumes_and_cover_letters(sheet, resume_json, target_jobs=target_jobs)
