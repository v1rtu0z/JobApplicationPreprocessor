"""Job collection from LinkedIn/Apify, collection phase orchestration, and new-job pipeline."""

import utils
from utils import (
    get_existing_job_keys,
    parse_location,
    get_location_priority,
    setup_driver,
    SHEET_HEADER,
)
from config import _get_job_filters, _save_job_filters, CONFIG_FILE
from api_methods import get_search_parameters
from core import ApifyDataSource, LinkedInDataSource

from .constants import CHECK_SUSTAINABILITY, email_address, linkedin_password
from .filtering import (
    _apply_keyword_filters,
    _apply_sustainability_keyword_filters,
    _normalize_job_title,
    _build_company_overview_cache,
)
from .bulk_ops import bulk_filter_collected_jobs, fetch_company_overviews
from .analysis import analyze_all_jobs
from .resumes import process_resumes_and_cover_letters
from .validation import validate_jobs_and_fetch_missing_data


def _normalized_to_row_data(normalized: dict, filters: dict) -> list[str] | None:
    """Build SHEET_HEADER row list from a normalized job item. Returns None if should skip."""
    job_title = _normalize_job_title(normalized.get("job_title", ""))
    company_name = (normalized.get("company_name") or "").strip()
    job_url = (normalized.get("job_url") or "").strip()
    raw_location = (normalized.get("location") or "").strip()
    job_description = (normalized.get("job_description") or "").strip()
    if not (job_title and company_name and job_url):
        return None
    should_skip, _ = _apply_keyword_filters(job_title, company_name, raw_location, filters)
    if should_skip:
        return None
    should_skip_sust, _, _ = _apply_sustainability_keyword_filters(
        job_title, company_name, raw_location, '', filters
    )
    if should_skip_sust:
        return None
    clean_location = parse_location(raw_location) if raw_location else ""
    location_priority = get_location_priority(clean_location)
    row_data = [
        company_name, job_title, clean_location, str(location_priority),
        job_description, job_url, "", "", "", "", "FALSE", "FALSE",
        "", "", "FALSE", "",
    ]
    while len(row_data) < len(SHEET_HEADER):
        row_data.append("")
    return row_data


def collect_and_filter_jobs(driver, sheet, search_urls: list = None):
    """Collect jobs from LinkedIn search URLs via LinkedInDataSource, apply filters, add to DB. Returns list of (job_url, company_name)."""
    if not search_urls:
        print("No search URLs provided for LinkedIn crawling.")
        return []

    print("\n" + "=" * 60)
    print("COLLECTION PHASE: Gathering all jobs from search URLs")
    print("=" * 60 + "\n")

    existing_jobs = get_existing_job_keys(sheet)
    filters = _get_job_filters()
    new_rows = []
    jobs_to_scrape = []
    source = LinkedInDataSource()

    for search_url in search_urls:
        print(f"Collecting jobs from search URL: {search_url}")
        count = 0
        for normalized in source.fetch_jobs(search_url=search_url, driver=driver, max_pages=5):
            try:
                job_key = f"{_normalize_job_title(normalized.get('job_title', ''))} @ {(normalized.get('company_name') or '').strip()}"
                if job_key in existing_jobs:
                    continue
                row_data = _normalized_to_row_data(normalized, filters)
                if not row_data:
                    continue
                new_rows.append(row_data)
                existing_jobs.add(job_key)
                jobs_to_scrape.append((row_data[5], row_data[0]))  # Job URL, Company Name
                count += 1
                print(f"Collected job for detailed scraping: {job_key}")
            except Exception as e:
                print(f"Unexpected error collecting job: {e}")
        print(f"Found {count} job listings")

    if new_rows:
        sheet.append_rows(new_rows)
        print(f"Successfully added {len(new_rows)} jobs.")
    else:
        print("No new jobs found via LinkedIn crawl.")

    print(f"\nCollection phase completed. Added {len(new_rows)} new jobs. Total jobs to scrape: {len(jobs_to_scrape)}")
    return jobs_to_scrape


def collect_jobs_via_apify(sheet, search_url=None, params=None):
    """Collect jobs using ApifyDataSource. Returns list of (job_url, company_name) for new jobs."""
    source = ApifyDataSource()
    if not source.is_available():
        print("Apify is currently unavailable (usage limit reached). Skipping collection phase.")
        return []

    if not params and not search_url:
        print("No search parameters or URL provided for Apify collection.")
        return []

    print("\n" + "=" * 60)
    print("COLLECTION PHASE (Apify): Gathering jobs from LinkedIn via Apify")
    print("=" * 60 + "\n")

    existing_jobs = get_existing_job_keys(sheet)
    filters = _get_job_filters()
    new_rows = []
    new_job_identifiers = []

    inputs = [{"params": params}] if params else [{"search_url": search_url}]

    for item_input in inputs:
        if not source.is_available():
            break
        url = item_input.get("search_url")
        p = item_input.get("params")
        for normalized in source.fetch_jobs(search_url=url, params=p):
            try:
                job_key = f"{_normalize_job_title(normalized.get('job_title', ''))} @ {(normalized.get('company_name') or '').strip()}"
                if job_key in existing_jobs:
                    continue
                row_data = _normalized_to_row_data(normalized, filters)
                if not row_data:
                    continue
                new_rows.append(row_data)
                existing_jobs.add(job_key)
                new_job_identifiers.append((row_data[5], row_data[0]))  # Job URL, Company Name
                print(f"Collected job via Apify: {job_key}")
            except Exception as e:
                print(f"Unexpected error processing Apify job item: {e}")

    if new_rows:
        sheet.append_rows(new_rows)
        print(f"Successfully added {len(new_rows)} jobs.")
    else:
        print("No new jobs found via Apify.")

    return new_job_identifiers


def process_collection_phase(sheet, resume_json, shutdown_requested, company_overview_cache=None):
    """Handle job collection from Apify and search parameter generation. Returns (collected_jobs, total_new_jobs, cache)."""
    if company_overview_cache is None:
        company_overview_cache = _build_company_overview_cache(sheet)

    filters = _get_job_filters()
    llm_params_list = filters.get('search_parameters', [])
    collected_jobs = []
    total_new_jobs = 0

    if llm_params_list:
        print(f"\nUsing cached search parameters ({len(llm_params_list)} parameter sets).")
        for params in llm_params_list:
            if shutdown_requested['flag']:
                break
            new_jobs = collect_jobs_via_apify(sheet, params=params)
            if new_jobs:
                collected_jobs.extend(new_jobs)
                total_new_jobs += len(new_jobs)
                print(f"Added {len(new_jobs)} new jobs from search: {params.get('keywords', 'N/A')} in {params.get('location', 'N/A')}")

    if (not llm_params_list or total_new_jobs == 0) and not shutdown_requested['flag'] and utils.apify_state.is_available():
        if not llm_params_list:
            print("\nNo cached search parameters found. Generating search parameters from resume...")
        else:
            print("\nNo new jobs found with existing search parameters. Regenerating search parameters...")

        llm_params_list = get_search_parameters(resume_json)

        if llm_params_list:
            print(f"Generated {len(llm_params_list)} new search parameter sets.")
            filters['search_parameters'] = llm_params_list
            _save_job_filters(filters)
            print(f"Saved new search parameters to {CONFIG_FILE}")

            for params in llm_params_list:
                if shutdown_requested['flag']:
                    break
                new_jobs = collect_jobs_via_apify(sheet, params=params)
                if new_jobs:
                    collected_jobs.extend(new_jobs)
                    total_new_jobs += len(new_jobs)
                    print(f"Added {len(new_jobs)} new jobs from search: {params.get('keywords', 'N/A')} in {params.get('location', 'N/A')}")
        else:
            print("Warning: Could not generate search parameters. Please check your resume and API keys.")

    return collected_jobs, total_new_jobs, company_overview_cache


def process_new_jobs_pipeline(sheet, resume_json, collected_jobs, company_overview_cache):
    """Process newly collected jobs through the full pipeline. Returns True if any progress."""
    progress = False
    if bulk_filter_collected_jobs(sheet, resume_json, target_jobs=collected_jobs, force_process=False) > 0:
        progress = True
    if fetch_company_overviews(sheet, company_overview_cache, target_jobs=collected_jobs) > 0:
        progress = True
    if CHECK_SUSTAINABILITY:
        print("\nValidating sustainability for new jobs...")
        if utils.validate_sustainability_for_unprocessed_jobs(sheet) > 0:
            progress = True
    if analyze_all_jobs(sheet, resume_json, target_jobs=collected_jobs) > 0:
        progress = True
    if process_resumes_and_cover_letters(sheet, resume_json, target_jobs=collected_jobs) > 0:
        progress = True
    return progress


def process_linkedin_collection(sheet, resume_json, company_overview_cache, shutdown_requested):
    """Handle LinkedIn scraping if enabled. Returns True if any progress."""
    from .constants import CRAWL_LINKEDIN
    if not CRAWL_LINKEDIN:
        return False

    from linkedin_scraper import actions

    driver = setup_driver()
    actions.login(driver, email_address, linkedin_password)
    progress = False

    print("\nChecking for expired job postings...")
    if validation.validate_jobs_and_fetch_missing_data(driver, sheet) > 0:
        progress = True

    print("Collecting jobs from LinkedIn search results...")
    jobs_to_scrape = collect_and_filter_jobs(driver, sheet)

    if jobs_to_scrape:
        progress = True
        validate_jobs_and_fetch_missing_data(driver, sheet)
        bulk_filter_collected_jobs(sheet, resume_json, target_jobs=jobs_to_scrape, force_process=False)
        fetch_company_overviews(sheet, company_overview_cache, target_jobs=jobs_to_scrape)
        analyze_all_jobs(sheet, resume_json, target_jobs=jobs_to_scrape)
        process_resumes_and_cover_letters(sheet, resume_json, target_jobs=jobs_to_scrape)

    return progress
