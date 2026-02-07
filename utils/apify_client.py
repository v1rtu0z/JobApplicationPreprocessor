"""Apify client, rate limiting, and LinkedIn data fetching via Apify."""

import os
import random
import time
from urllib.parse import urlparse, parse_qs

from apify_client import ApifyClient

from .parsing import normalize_company_name

# Global variable to track last request time (used by rate_limit)
last_request_time = 0


class ApifyStateManager:
    """Thread-safe manager for Apify availability state with automatic retry logic."""

    def __init__(self):
        self._available = True
        self._last_failure_time = None
        self._retry_delay = 3600  # 1 hour before retrying after failure

    def is_available(self) -> bool:
        """Check if Apify is currently available."""
        if not self._available and self._last_failure_time:
            elapsed = time.time() - self._last_failure_time
            if elapsed > self._retry_delay:
                print(f"Apify retry delay ({self._retry_delay}s) elapsed. Allowing retry...")
                self._available = True
                self._last_failure_time = None
        return self._available

    def mark_unavailable(self):
        """Mark Apify as unavailable due to rate limit or error."""
        self._available = False
        self._last_failure_time = time.time()

    def reset(self):
        """Reset state to available (useful for testing or manual intervention)."""
        self._available = True
        self._last_failure_time = None


apify_state = ApifyStateManager()


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


def get_company_overviews_bulk_via_apify(company_names: list[str]) -> dict[str, str]:
    """
    Fetch company overviews in bulk using Apify (up to 1000 companies).
    """
    if not company_names:
        return {}

    if not APIFY_AVAILABLE:
        print("Apify is currently unavailable (usage limit reached). Skipping company overview fetch.")
        return {}

    print(f"Fetching {len(company_names)} company overviews via Apify in bulk...")

    token = os.getenv("APIFY_API_TOKEN")
    if not token:
        print("APIFY_API_TOKEN not set. Skipping Apify fetch.")
        return {}

    client = ApifyClient(token)

    try:
        run_input = {
            "identifier": company_names,
            "maxResults": len(company_names)
        }

        run = client.actor("apimaestro/linkedin-company-detail").call(run_input=run_input)
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())

        if not items:
            print(f"  No company data found on Apify")
            return {}

        company_map = {}
        for item in items:
            company_name = item.get("input_identifier", "")
            if company_name:
                company_name = company_name.strip()
            description = item.get("basic_info", {}).get("description", "")
            if description:
                description = description.strip()

            if company_name and description:
                company_map[company_name] = description

        print(f"Successfully fetched {len(company_map)}/{len(company_names)} company overviews")
        return company_map

    except Exception as e:
        error_msg = str(e)
        print(f"Error in bulk Apify fetch: {error_msg}")
        if "Monthly usage hard limit exceeded" in error_msg:
            print("\n" + "!" * 60)
            print("CRITICAL: APIFY MONTHLY USAGE HARD LIMIT REACHED.")
            print("No more jobs can be fetched via Apify this month.")
            print("Disabling Apify for the remainder of this run.")
            print("!" * 60 + "\n")
            apify_state.mark_unavailable()
        return {}


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

    title_matches = (job_title_normalized in item_title or item_title in job_title_normalized)
    company_matches = (job_company_normalized == item_company_normalized or
                       job_company_normalized in item_company_normalized or
                       item_company_normalized in job_company_normalized)

    return title_matches and company_matches


def fetch_job_details_bulk_via_apify(job_ids: list[str]) -> list[dict]:
    """
    Fetch job details (including full descriptions) in bulk using Apify.
    """
    if not job_ids:
        return []

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
        if "Monthly usage hard limit exceeded" in error_msg:
            print("\n" + "!" * 60)
            print("CRITICAL: APIFY MONTHLY USAGE HARD LIMIT REACHED.")
            print("Disabling Apify for the remainder of this run.")
            print("!" * 60 + "\n")
            apify_state.mark_unavailable()
        return []


def fetch_jobs_via_apify(search_url: str = None, params: dict = None) -> list[dict]:
    """
    Fetch jobs from LinkedIn via Apify Actor using parameters extracted from search_url OR provided directly.
    """
    if not APIFY_AVAILABLE:
        print("Apify is currently unavailable (usage limit reached). Skipping job fetch.")
        return []

    token = os.getenv("APIFY_API_TOKEN")
    if not token:
        return []

    if params:
        run_input = {
            "keywords": params.get('keywords', ''),
            "location": params.get('location', ''),
            "remote": params.get('remote', ''),
            "experienceLevel": params.get('experienceLevel', ''),
            "sort": params.get('sort', 'recent'),
            "date_posted": params.get('date_posted', 'week'),
            "easy_apply": params.get('easy_apply', ''),
            "limit": params.get('limit', 100)
        }
    elif search_url:
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

        run_input = {
            "keywords": keywords,
            "location": location,
            "remote": remote,
            "experienceLevel": experience_level,
            "sort": sort,
            "date_posted": date_posted,
            "easy_apply": easy_apply,
            "limit": 100
        }
    else:
        print("Error: Either search_url or params must be provided to fetch_jobs_via_apify")
        return []

    print(f"Running Apify Actor for keywords: '{run_input.get('keywords')}' in location: '{run_input.get('location')}'")

    client = ApifyClient(token)

    try:
        run = client.actor("apimaestro/linkedin-jobs-scraper-api").call(run_input=run_input)
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

        print(f"Fetched {len(items)} jobs from Apify.")
        return items

    except Exception as e:
        error_msg = str(e)
        print(f"Error running Apify Actor: {error_msg}")
        if "Monthly usage hard limit exceeded" in error_msg:
            print("\n" + "!" * 60)
            print("CRITICAL: APIFY MONTHLY USAGE HARD LIMIT REACHED.")
            print("Disabling Apify for the remainder of this run.")
            print("!" * 60 + "\n")
            apify_state.mark_unavailable()
        return []
