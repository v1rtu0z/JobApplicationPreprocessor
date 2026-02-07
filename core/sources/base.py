"""DataSource interface: abstract contract for job listing providers."""

from abc import ABC, abstractmethod
from typing import Any, Iterator


class DataSource(ABC):
    """
    Interface for job listing data sources (Apify, LinkedIn direct, other boards).
    Implementations yield normalized job items that can be converted to Job/row format.
    """

    @abstractmethod
    def fetch_jobs(
        self,
        search_url: str | None = None,
        params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Iterator[dict[str, Any]]:
        """
        Fetch job listings from this source.

        Yields normalized items with at least:
          - company_name (str)
          - job_title (str)
          - job_url (str)
          - location (str)
          - job_description (str, may be empty)

        Args:
            search_url: Optional LinkedIn (or source-specific) search URL.
            params: Optional search parameters (e.g. keywords, location).
            **kwargs: Source-specific options.

        Yields:
            Dicts with the keys above; implementations may add more.
        """
        ...

    def is_available(self) -> bool:
        """Return True if this source can be used (e.g. not rate-limited)."""
        return True
