"""LinkedIn direct scraping job listing data source."""

from typing import Any, Iterator

from utils.linkedin_crawl import scrape_multiple_pages


def _normalize_linkedin_job_obj(job_obj: Any) -> dict[str, Any] | None:
    """Convert a LinkedIn scraper job object to normalized job item."""
    job_title = (getattr(job_obj, "job_title", None) or getattr(job_obj, "title", None) or "")
    if isinstance(job_title, str):
        job_title = job_title.strip()
    else:
        job_title = ""
    company = (getattr(job_obj, "company", None) or "")
    if isinstance(company, str):
        company_name = company.strip()
    else:
        company_name = ""
    job_url = getattr(job_obj, "linkedin_url", None) or getattr(job_obj, "job_url", None) or ""
    if not isinstance(job_url, str):
        job_url = ""
    job_url = job_url.strip()
    location = (getattr(job_obj, "location", None) or "")
    if isinstance(location, str):
        location = location.strip()
    else:
        location = ""
    if not company_name or not job_title or not job_url:
        return None
    return {
        "company_name": company_name,
        "job_title": job_title,
        "job_url": job_url,
        "location": location,
        "job_description": "",  # Fetched later via JD crawl
    }


class LinkedInDataSource:
    """DataSource implementation using direct LinkedIn scraping (e.g. linkedin_scraper + Selenium)."""

    def fetch_jobs(
        self,
        search_url: str | None = None,
        params: dict[str, Any] | None = None,
        *,
        driver: Any = None,
        max_pages: int = 5,
        **kwargs: Any,
    ) -> Iterator[dict[str, Any]]:
        if not search_url or not driver:
            return
        job_listings = scrape_multiple_pages(driver, search_url, max_pages=max_pages)
        for job_obj in job_listings:
            try:
                normalized = _normalize_linkedin_job_obj(job_obj)
                if normalized:
                    yield normalized
            except Exception:
                continue

    def is_available(self) -> bool:
        """LinkedIn scraping is available if driver and URLs are provided; no global rate state here."""
        return True
