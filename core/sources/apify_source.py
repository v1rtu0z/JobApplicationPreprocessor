"""Apify-based job listing data source."""

from typing import Any, Iterator

import utils
from utils.apify_client import fetch_jobs_via_apify, apify_state


def _normalize_apify_item(item: dict[str, Any]) -> dict[str, Any]:
    """Convert Apify actor output to normalized job item."""
    from utils.parsing import normalize_easy_apply, normalize_posted_at

    job_title = (item.get("job_title") or item.get("title") or "").strip()
    company_name = (item.get("company") or item.get("company_name") or "").strip()
    job_url = (item.get("job_url") or item.get("url") or "").strip()
    raw_location = (item.get("location") or "").strip()
    job_description = (
        (item.get("description") or item.get("job_description") or item.get("jobDescription") or item.get("jobDescriptionText") or "")
        .strip()
    )
    posted_raw = (
        item.get("posted_at")
        or item.get("postedAt")
        or item.get("posted_date")
        or item.get("postedDate")
        or item.get("publishedAt")
        or ""
    )
    apply_details = item.get("apply_details") or {}
    easy_raw = (
        item.get("is_easy_apply")
        if "is_easy_apply" in item
        else apply_details.get("is_easy_apply")
        if isinstance(apply_details, dict) and "is_easy_apply" in apply_details
        else item.get("easy_apply")
        if "easy_apply" in item
        else None
    )
    return {
        "company_name": company_name,
        "job_title": job_title,
        "job_url": job_url,
        "location": raw_location,
        "job_description": job_description,
        "company_url": (item.get("company_url") or item.get("companyUrl") or "").strip(),
        "date_posted": normalize_posted_at(str(posted_raw) if posted_raw is not None else ""),
        "easy_apply": normalize_easy_apply(easy_raw),
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
