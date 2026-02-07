"""Factory for data sources and repository (DI-friendly)."""

from typing import Any

from .sources import DataSource, ApifyDataSource, LinkedInDataSource
from .repository import JobRepository


def create_data_source(name: str, **kwargs: Any) -> DataSource:
    """
    Create a DataSource by name. Use for DI or when switching sources without changing callers.

    Supported names: 'apify', 'linkedin'.
    """
    name_lower = (name or "").strip().lower()
    if name_lower == "apify":
        return ApifyDataSource(**kwargs)
    if name_lower == "linkedin":
        return LinkedInDataSource(**kwargs)
    raise ValueError(f"Unknown data source: {name!r}. Use 'apify' or 'linkedin'.")


def create_repository(job_store: Any) -> JobRepository:
    """Create a JobRepository wrapping the given job store (e.g. JobDatabase)."""
    return JobRepository(job_store)
