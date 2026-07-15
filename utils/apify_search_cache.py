"""Persisted cache for Apify job-search queries to avoid repeat API calls."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from config import _get_job_filters, _save_job_filters

APIFY_SEARCH_CACHE_TTL_DAYS = 15
APIFY_SEARCH_CACHE_TTL = timedelta(days=APIFY_SEARCH_CACHE_TTL_DAYS)

SEARCH_INPUT_FIELDS = (
    "keywords",
    "location",
    "remote",
    "experienceLevel",
    "sort",
    "date_posted",
    "easy_apply",
    "limit",
    "page",
)


def normalize_run_input(run_input: dict) -> dict:
    """Normalize Apify job-search input for stable cache keys."""
    normalized = {}
    for field in SEARCH_INPUT_FIELDS:
        value = run_input.get(field, "")
        if value is None:
            value = ""
        if field == "limit":
            try:
                value = int(value) if str(value).strip() else 100
            except (TypeError, ValueError):
                value = 100
        elif field == "page":
            try:
                value = int(value) if str(value).strip() else 1
            except (TypeError, ValueError):
                value = 1
        else:
            value = str(value).strip()
        normalized[field] = value
    return normalized


def search_fingerprint(run_input: dict) -> str:
    """Return a stable fingerprint for an Apify job-search request."""
    payload = json.dumps(normalize_run_input(run_input), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_cached_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _prune_expired_entries(cache: dict[str, str], now: datetime | None = None) -> dict[str, str]:
    now = now or _utc_now()
    pruned = {}
    for key, fetched_at in cache.items():
        parsed = _parse_cached_timestamp(fetched_at)
        if parsed and now - parsed < APIFY_SEARCH_CACHE_TTL:
            pruned[key] = fetched_at
    return pruned


def get_search_cache() -> dict[str, str]:
    filters = _get_job_filters()
    cache = filters.get("apify_search_cache") or {}
    if not isinstance(cache, dict):
        return {}
    return _prune_expired_entries(cache)


def get_cached_fetch_time(fingerprint: str) -> datetime | None:
    return _parse_cached_timestamp(get_search_cache().get(fingerprint, ""))


def should_skip_apify_search(run_input: dict, now: datetime | None = None) -> bool:
    """Return True when this search was fetched within the TTL window."""
    now = now or _utc_now()
    fetched_at = get_cached_fetch_time(search_fingerprint(run_input))
    if not fetched_at:
        return False
    return now - fetched_at < APIFY_SEARCH_CACHE_TTL


def mark_apify_search_fetched(run_input: dict, fetched_at: datetime | None = None) -> None:
    """Record a successful Apify job-search fetch for this query/result page."""
    fetched_at = fetched_at or _utc_now()
    fingerprint = search_fingerprint(run_input)
    filters = _get_job_filters()
    cache = filters.get("apify_search_cache") or {}
    if not isinstance(cache, dict):
        cache = {}
    cache[fingerprint] = fetched_at.isoformat().replace("+00:00", "Z")
    filters["apify_search_cache"] = _prune_expired_entries(cache, fetched_at)
    _save_job_filters(filters)


def days_since_fetch(fetched_at: datetime, now: datetime | None = None) -> float:
    now = now or _utc_now()
    return (now - fetched_at).total_seconds() / 86400
