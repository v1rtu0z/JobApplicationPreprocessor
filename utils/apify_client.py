"""Apify client, rate limiting, and LinkedIn data fetching via Apify."""

import os
import random
import time
from urllib.parse import urlparse, parse_qs

from apify_client import ApifyClient

from .apify_search_cache import (
    APIFY_SEARCH_CACHE_TTL_DAYS,
    days_since_fetch,
    get_cached_fetch_time,
    mark_apify_search_fetched,
    search_fingerprint,
    should_skip_apify_search,
)
from .apify_state import ApifyStateManager, apify_state
from .parsing import normalize_company_name

# Global variable to track last request time (used by rate_limit)
last_request_time = 0


class _ApifyAvailableProxy:
    """Proxy class to maintain backwards compatibility with direct assignment."""

    def __bool__(self):
        return apify_state.is_available()

    def __repr__(self):
        return str(apify_state.is_available())


APIFY_AVAILABLE = _ApifyAvailableProxy()


def rate_limit():
    """Ensure at least 1 second has passed since last request"""
    global last_request_time
    current_time = time.time()
    time_since_last = current_time - last_request_time

    if time_since_last < 1.0:
        sleep_duration = random.uniform(0.5, 1.0)
        time.sleep(sleep_duration)

    last_request_time = time.time()


def get_company_overviews_bulk_via_apify(companies):
    """Fetch company overviews via Apify (see utils.apify_company)."""
    from .apify_company import get_company_overviews_bulk_via_apify as _fetch

    return _fetch(companies)


def match_job_to_apify_result(job: dict, apify_item: dict) -> bool:
    """
    Match a job from the database to an Apify result by comparing job title and company name.
    """
    job_info = apify_item.get('job_info', {})
    comp_info = apify_item.get('company_info', {})

    item_title = job_info.get('title', '').strip().lower()
    job_title_normalized = job.get('title', '').strip().lower()

    item_company_normalized = normalize_company_name(comp_info.get('name', ''))
    job_company_normalized = normalize_company_name(job.get('company', ''))

    return job_title_normalized == item_title and job_company_normalized == item_company_normalized


def fetch_job_details_bulk_via_apify(job_ids: list[str]) -> list[dict]:
    """
    Fetch job details (including full descriptions) in bulk using Apify.
    """
    if not job_ids:
        return []

    rate_limit()
    if not APIFY_AVAILABLE:
        print("Apify is currently unavailable (usage limit reached). Skipping job detail fetch.")
        return []

    print(f"Fetching {len(job_ids)} job details via Apify in bulk...")

    token = os.getenv("APIFY_API_TOKEN")
    if not token:
        return []

    client = ApifyClient(token)

    try:
        run_input = {"job_id": job_ids}
        run = client.actor("apimaestro/linkedin-job-detail").call(run_input=run_input)
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())

        if not items:
            print(f"  No job details found on Apify")
            return []

        print(f"Successfully fetched {len(items)}/{len(job_ids)} job details")
        return items

    except Exception as e:
        error_msg = str(e)
        print(f"Error in bulk Apify job detail fetch: {error_msg}")
        if ApifyStateManager.is_monthly_limit_error(error_msg):
            apify_state.handle_error(error_msg)
        return []


def _build_apify_jobs_run_input(search_url: str = None, params: dict = None) -> dict | None:
    """Build normalized Apify actor input from search URL or parameter dict."""
    if params:
        return {
            "keywords": params.get('keywords', ''),
            "location": params.get('location', ''),
            "remote": params.get('remote', ''),
            "experienceLevel": params.get('experienceLevel', ''),
            "sort": params.get('sort', 'recent'),
            "date_posted": params.get('date_posted', 'week'),
            "easy_apply": params.get('easy_apply', ''),
            "limit": params.get('limit', 100),
            "page": params.get('page', 1),
        }

    if search_url:
        parsed_url = urlparse(search_url)
        query_params = parse_qs(parsed_url.query)

        keywords = query_params.get('keywords', [''])[0]
        location = query_params.get('geoId', [''])[0]

        remote_map = {'1': 'onsite', '2': 'remote', '3': 'hybrid'}
        f_wt = query_params.get('f_WT', [])
        if f_wt:
            first_wt = f_wt[0].split(',')[0]
            remote = remote_map.get(first_wt, "")
        else:
            remote = ""

        exp_map = {
            '1': 'internship', '2': 'entry', '3': 'associate', '4': 'mid_senior',
            '5': 'director', '6': 'executive'
        }
        f_e = query_params.get('f_E', [])
        if f_e:
            first_e = f_e[0].split(',')[0]
            experience_level = exp_map.get(first_e, "")
        else:
            experience_level = ""

        sort_map = {'R': 'relevant', 'DD': 'recent'}
        sort_val = query_params.get('sortBy', [''])[0]
        sort = sort_map.get(sort_val, "")

        date_posted_map = {'r2592000': 'month', 'r604800': 'week', 'r86400': 'day'}
        f_tpr = query_params.get('f_TPR', [''])[0]
        date_posted = date_posted_map.get(f_tpr, "")

        easy_apply = "true" if 'f_AL' in query_params else ""
        page = query_params.get('page', ['1'])[0]

        return {
            "keywords": keywords,
            "location": location,
            "remote": remote,
            "experienceLevel": experience_level,
            "sort": sort,
            "date_posted": date_posted,
            "easy_apply": easy_apply,
            "limit": 100,
            "page": page,
        }

    return None


def apify_jobs_search_is_cached(search_url: str = None, params: dict = None) -> bool:
    """Return True when this search query/result page was fetched within the TTL window."""
    run_input = _build_apify_jobs_run_input(search_url=search_url, params=params)
    return bool(run_input and should_skip_apify_search(run_input))


def fetch_jobs_via_apify(search_url: str = None, params: dict = None) -> list[dict]:
    """
    Fetch jobs from LinkedIn via Apify Actor using parameters extracted from search_url OR provided directly.
    """
    run_input = _build_apify_jobs_run_input(search_url=search_url, params=params)
    if not run_input:
        print("Error: Either search_url or params must be provided to fetch_jobs_via_apify")
        return []

    if should_skip_apify_search(run_input):
        fetched_at = get_cached_fetch_time(search_fingerprint(run_input))
        age_days = days_since_fetch(fetched_at) if fetched_at else 0
        page = run_input.get("page", 1)
        print(
            f"Skipping Apify job search (fetched {age_days:.1f} days ago, "
            f"TTL {APIFY_SEARCH_CACHE_TTL_DAYS} days): "
            f"keywords='{run_input.get('keywords')}' location='{run_input.get('location')}' page={page}"
        )
        return []

    rate_limit()
    if not APIFY_AVAILABLE:
        print("Apify is currently unavailable (usage limit reached). Skipping job fetch.")
        return []

    token = os.getenv("APIFY_API_TOKEN")
    if not token:
        return []

    print(f"Running Apify Actor for keywords: '{run_input.get('keywords')}' in location: '{run_input.get('location')}'")

    client = ApifyClient(token)
    actor_input = {key: value for key, value in run_input.items() if key != "page"}

    try:
        run = client.actor("apimaestro/linkedin-jobs-scraper-api").call(run_input=actor_input)
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())

        if not items:
            try:
                record = client.key_value_store(run["defaultKeyValueStoreId"]).get_record("OUTPUT")
                if record and 'value' in record:
                    val = record['value']
                    if isinstance(val, dict) and 'results' in val:
                        items = val['results']
            except Exception:
                pass

        if items:
            mark_apify_search_fetched(run_input)
        print(f"Fetched {len(items)} jobs from Apify.")
        return items

    except Exception as e:
        error_msg = str(e)
        print(f"Error running Apify Actor: {error_msg}")
        if ApifyStateManager.is_monthly_limit_error(error_msg):
            apify_state.handle_error(error_msg)
        return []


def get_apify_usage_summary() -> dict:
    """Return current billing-cycle usage from the Apify account API."""
    token = os.getenv("APIFY_API_TOKEN")
    if not token:
        return {}
    try:
        client = ApifyClient(token)
        usage = client.user().monthly_usage()
        plan = client.user().get().get("plan") or {}
        return {
            "total_usd": usage.get("totalUsageCreditsUsdAfterVolumeDiscount", 0),
            "cycle_start": usage.get("usageCycle", {}).get("startAt"),
            "cycle_end": usage.get("usageCycle", {}).get("endAt"),
            "monthly_credits_usd": plan.get("monthlyUsageCreditsUsd"),
            "max_monthly_usd": plan.get("maxMonthlyUsageUsd"),
            "plan_tier": plan.get("tier"),
        }
    except Exception as exc:
        print(f"Could not fetch Apify usage: {exc}")
        return {}


def format_apify_usage(summary: dict) -> str:
    if not summary:
        return "unavailable"
    total = summary.get("total_usd", 0)
    credits = summary.get("monthly_credits_usd")
    max_usd = summary.get("max_monthly_usd")
    parts = [f"${total:.4f} used this cycle"]
    if credits is not None:
        parts.append(f"${credits}/mo plan credits")
    if max_usd is not None:
        parts.append(f"${max_usd} cap")
    return " | ".join(parts)
