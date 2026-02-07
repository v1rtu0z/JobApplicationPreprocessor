"""Domain models: Job and Company with clear encapsulation."""

from __future__ import annotations

from typing import Any

from utils.schema import SHEET_HEADER

# Default empty value for any schema column
_EMPTY = ""


class Company:
    """Company value object: name, URL, and overview."""

    __slots__ = ("_name", "_url", "_overview")

    def __init__(
        self,
        name: str = _EMPTY,
        url: str = _EMPTY,
        overview: str = _EMPTY,
    ) -> None:
        self._name = (name or _EMPTY).strip()
        self._url = (url or _EMPTY).strip()
        self._overview = (overview or _EMPTY).strip()

    @property
    def name(self) -> str:
        return self._name

    @property
    def url(self) -> str:
        return self._url

    @property
    def overview(self) -> str:
        return self._overview

    def with_overview(self, overview: str) -> Company:
        return Company(name=self._name, url=self._url, overview=(overview or _EMPTY).strip())

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Company):
            return NotImplemented
        return (
            self._name == other._name
            and self._url == other._url
            and self._overview == other._overview
        )

    def __repr__(self) -> str:
        return f"Company(name={self._name!r})"


class Job:
    """
    Job domain model with full schema encapsulation.
    Converts to/from storage row dict for compatibility with existing pipeline.
    """

    __slots__ = ("_row",)

    def __init__(self, row: dict[str, str] | None = None) -> None:
        if row is None:
            row = {}
        self._row = {k: (str(v).strip() if v is not None else _EMPTY) for k, v in row.items()}
        # Ensure all schema columns exist
        for col in SHEET_HEADER:
            if col not in self._row:
                self._row[col] = _EMPTY

    # --- Identity ---
    @property
    def job_url(self) -> str:
        return self._row.get("Job URL", _EMPTY)

    @property
    def company_name(self) -> str:
        return self._row.get("Company Name", _EMPTY)

    @property
    def job_title(self) -> str:
        return self._row.get("Job Title", _EMPTY)

    def natural_key(self) -> tuple[str, str]:
        """Unique key for this job: (job_url, company_name)."""
        return (self.job_url, self.company_name)

    def job_key_str(self) -> str:
        """Legacy key string: 'Job Title @ Company Name'."""
        return f"{self.job_title} @ {self.company_name}"

    # --- Company ---
    @property
    def company(self) -> Company:
        return Company(
            name=self.company_name,
            url=self._row.get("Company URL", _EMPTY),
            overview=self._row.get("Company overview", _EMPTY),
        )

    # --- Location ---
    @property
    def location(self) -> str:
        return self._row.get("Location", _EMPTY)

    @property
    def location_priority(self) -> str:
        return self._row.get("Location Priority", _EMPTY)

    # --- Description & analysis ---
    @property
    def job_description(self) -> str:
        return self._row.get("Job Description", _EMPTY)

    @property
    def fit_score(self) -> str:
        return self._row.get("Fit score", _EMPTY)

    @property
    def fit_score_enum(self) -> str:
        return self._row.get("Fit score enum", _EMPTY)

    @property
    def job_analysis(self) -> str:
        return self._row.get("Job analysis", _EMPTY)

    @property
    def bad_analysis(self) -> bool:
        return (self._row.get("Bad analysis", _EMPTY) or _EMPTY).strip().upper() == "TRUE"

    @property
    def job_posting_expired(self) -> bool:
        return (self._row.get("Job posting expired", _EMPTY) or _EMPTY).strip().upper() == "TRUE"

    # --- Resume / cover letter ---
    @property
    def tailored_resume_url(self) -> str:
        return self._row.get("Tailored resume url", _EMPTY)

    @property
    def tailored_cover_letter(self) -> str:
        return self._row.get("Tailored cover letter (to be humanized)", _EMPTY)

    # --- Status flags ---
    @property
    def applied(self) -> bool:
        return (self._row.get("Applied", _EMPTY) or _EMPTY).strip().upper() == "TRUE"

    # --- Raw row (for incremental migration) ---
    def get(self, column: str, default: str = _EMPTY) -> str:
        return self._row.get(column, default)

    def to_row(self) -> dict[str, str]:
        """Return a full row dict with all SHEET_HEADER keys (no _id)."""
        return {col: self._row.get(col, _EMPTY) for col in SHEET_HEADER}

    def to_row_with_id(self, job_id: int | None = None) -> dict[str, Any]:
        """Row dict including _id if present or passed."""
        row = dict(self.to_row())
        if job_id is not None:
            row["_id"] = job_id
        elif "_id" in self._row:
            row["_id"] = self._row["_id"]
        return row

    def copy_with_updates(self, updates: dict[str, str]) -> Job:
        """Return a new Job with the given column updates."""
        new_row = dict(self._row)
        for k, v in updates.items():
            new_row[k] = str(v).strip() if v is not None else _EMPTY
        return Job(row=new_row)

    @classmethod
    def from_row(cls, row: dict[str, Any] | None) -> Job:
        """Build a Job from a storage row (dict with SHEET_HEADER keys, optionally _id)."""
        if not row:
            return cls(row={})
        # Strip _id for the model; it's storage-specific
        clean = {k: v for k, v in row.items() if k != "_id"}
        return cls(row=clean)

    def __repr__(self) -> str:
        return f"Job({self.job_key_str()!r})"
