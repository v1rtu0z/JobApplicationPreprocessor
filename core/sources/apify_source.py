"""Apify-based job listing data source."""

from typing import Any, Iterator

import utils
from utils.apify_client import fetch_jobs_via_apify, apify_state


def _normalize_apify_item(item: dict[str, Any]) -> dict[str, Any]:
    """Convert Apify actor output to normalized job item."""
    job_title = (item.get("job_title") or item.get("title") or "").strip()
    company_name = (item.get("company") or item.get("company_name") or "").strip()
    job_url = (item.get("job_url") or item.get("url") or "").strip()
    raw_location = (item.get("location") or "").strip()
    job_description = (
        (item.get("description") or item.get("job_description") or item.get("jobDescription") or item.get("jobDescriptionText") or "")
        .strip()
    )
    return {
        "company_name": company_name,
        "job_title": job_title,
        "job_url": job_url,
        "location": raw_location,
        "job_description": job_description,
    }


class ApifyDataSource:
    """DataSource implementation using Apify LinkedIn jobs actor."""

    def fetch_jobs(
        self,
        search_url: str | None = None,
        params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Iterator[dict[str, Any]]:
        if not params and not search_url:
            return
        if not utils.APIFY_AVAILABLE:
            return
        items = fetch_jobs_via_apify(search_url=search_url, params=params)
        for item in items:
            try:
                normalized = _normalize_apify_item(item)
                if normalized["company_name"] and normalized["job_title"] and normalized["job_url"]:
                    yield normalized
            except Exception:
                continue

    def is_available(self) -> bool:
        return bool(apify_state.is_available())
