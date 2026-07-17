"""Job collection from Apify, collection phase orchestration, and new-job pipeline."""

from datetime import datetime, timezone

import utils
from utils import (
    get_existing_job_keys,
    parse_location,
    get_location_priority,
    JOB_COLUMNS,
)
from utils.storage import build_repost_updates, get_expired_jobs_by_key
from config import _get_job_filters, _save_job_filters, CONFIG_FILE
from api_methods import get_search_parameters
from core import ApifyDataSource

from .constants import CHECK_SUSTAINABILITY
from .filtering import (
    _apply_keyword_filters,
    _apply_sustainability_keyword_filters,
    _normalize_job_title,
    _build_company_overview_cache,
)
from .bulk_ops import bulk_filter_collected_jobs, fetch_company_overviews
from .analysis import analyze_all_jobs
from .resumes import process_resumes_and_cover_letters


def _normalized_to_row_dict(normalized: dict, filters: dict) -> dict[str, str] | None:
    """Build a job-table row dict from a normalized job item. Returns None if should skip."""
    job_title = _normalize_job_title(normalized.get("job_title", ""))
    company_name = (normalized.get("company_name") or "").strip()
    job_url = (normalized.get("job_url") or "").strip()
    raw_location = (normalized.get("location") or "").strip()
    job_description = (normalized.get("job_description") or "").strip()
    if not (job_title and company_name and job_url):
        return None
    should_skip, _ = _apply_keyword_filters(
        job_title, company_name, raw_location, filters, job_description
    )
    if should_skip:
        return None
    should_skip_sust, _, _ = _apply_sustainability_keyword_filters(
        job_title, company_name, raw_location, '', filters
    )
    if should_skip_sust:
        return None
    clean_location = parse_location(raw_location) if raw_location else ""
    location_priority = get_location_priority(clean_location)
    row = {col: "" for col in JOB_COLUMNS}
    row.update({
        "Company Name": company_name,
        "Job Title": job_title,
        "Location": clean_location,
        "Location Priority": str(location_priority),
        "Job Description": job_description,
        "Job URL": job_url,
        "Company URL": (normalized.get("company_url") or "").strip(),
        "CO fetch attempted": "FALSE",
        "JD crawl attempted": "FALSE",
        "Bulk filtered": "FALSE",
        "Date added": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "Date posted": (normalized.get("date_posted") or "").strip(),
        "Easy apply": (normalized.get("easy_apply") or "").strip(),
    })
    return row


def _normalized_to_row_data(normalized: dict, filters: dict) -> list[str] | None:
    """Build an ordered job-table value list from a normalized job item. Returns None if should skip."""
    row = _normalized_to_row_dict(normalized, filters)
    if not row:
        return None
    return [row[col] for col in JOB_COLUMNS]


def collect_jobs_via_apify(db, search_url=None, params=None):
    """Collect jobs using ApifyDataSource. Returns list of (job_url, company_name) for new jobs.

    Active and applied (non-expired) title@company keys are skipped. When the same key matches
    an **expired** row, that row is updated in place (new URL/JD, cleared listing/pipeline
    state). Applied is left alone — it is user-scoped and must remain so when this refresh is
    shared across users.
    """
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

    existing_jobs = get_existing_job_keys(db)
    expired_by_key = get_expired_jobs_by_key(db)
    filters = _get_job_filters()
    new_rows = []
    new_job_identifiers = []
    repost_count = 0

    inputs = [{"params": params}] if params else [{"search_url": search_url}]

    for item_input in inputs:
        if not source.is_available():
            break
        url = item_input.get("search_url")
        p = item_input.get("params")
        for normalized in source.fetch_jobs(search_url=url, params=p):
            try:
                job_title = _normalize_job_title(normalized.get("job_title", ""))
                company_name = (normalized.get("company_name") or "").strip()
                job_key = f"{job_title} @ {company_name}"
                if job_key in existing_jobs:
                    continue
                row_dict = _normalized_to_row_dict(normalized, filters)
                if not row_dict:
                    continue

                old_expired = expired_by_key.get(job_key)
                if old_expired:
                    old_url = (old_expired.get("Job URL") or "").strip()
                    old_company = (old_expired.get("Company Name") or "").strip()
                    updates = build_repost_updates(old_expired, row_dict)
                    updated = db.update_job_by_key(old_url, old_company, updates)
                    if updated:
                        existing_jobs.add(job_key)
                        expired_by_key.pop(job_key, None)
                        new_job_identifiers.append((row_dict["Job URL"], row_dict["Company Name"]))
                        repost_count += 1
                        print(
                            f"Reposted job (updated expired row): {job_key} "
                            f"[{old_url} → {row_dict['Job URL']}]"
                        )
                        continue
                    # Fall through to insert if the update matched nothing (row vanished).

                new_rows.append([row_dict[col] for col in JOB_COLUMNS])
                existing_jobs.add(job_key)
                new_job_identifiers.append((row_dict["Job URL"], row_dict["Company Name"]))
                print(f"Collected job via Apify: {job_key}")
            except Exception as e:
                print(f"Unexpected error processing Apify job item: {e}")

    if new_rows:
        db.add_jobs_from_rows(new_rows)
        print(f"Successfully added {len(new_rows)} jobs.")
    if repost_count:
        print(f"Updated {repost_count} expired reposted job(s) in place.")
    if not new_rows and not repost_count:
        print("No new jobs found via Apify.")

    return new_job_identifiers


def process_collection_phase(db, resume_json, shutdown_requested, company_overview_cache=None):
    """Handle job collection from Apify and search parameter generation.

    Each search's new jobs are run through the full downstream pipeline (bulk filter, company
    overview, sustainability, analysis, resumes/cover letters) immediately, before the next
    search request is made. This keeps memory/backlog bounded, surfaces good-fit jobs to the user
    sooner, and preserves partial progress if the process is interrupted mid-cycle.

    Returns (collected_jobs, total_new_jobs, cache).
    """
    from .constants import SKIP_APIFY_COLLECTION

    if SKIP_APIFY_COLLECTION:
        print("\nSkipping Apify collection phase (SKIP_APIFY_COLLECTION=true).")
        if company_overview_cache is None:
            company_overview_cache = _build_company_overview_cache(db)
        return [], 0, company_overview_cache

    if company_overview_cache is None:
        company_overview_cache = _build_company_overview_cache(db)

    filters = _get_job_filters()
    llm_params_list = filters.get('search_parameters', [])
    collected_jobs = []
    total_new_jobs = 0
    any_apify_search_ran = False

    def _run_search_and_drain(params) -> None:
        """Collect one search's jobs, then fully process just that batch before returning."""
        nonlocal total_new_jobs, any_apify_search_ran
        if not utils.apify_jobs_search_is_cached(params=params):
            any_apify_search_ran = True
        new_jobs = collect_jobs_via_apify(db, params=params)
        if not new_jobs:
            return
        collected_jobs.extend(new_jobs)
        total_new_jobs += len(new_jobs)
        print(f"Added {len(new_jobs)} new jobs from search: {params.get('keywords', 'N/A')} in {params.get('location', 'N/A')}")
        print(f"Draining pipeline for these {len(new_jobs)} jobs before the next search...")
        process_new_jobs_pipeline(db, resume_json, new_jobs, company_overview_cache)

    if llm_params_list:
        print(f"\nUsing cached search parameters ({len(llm_params_list)} parameter sets).")
        for params in llm_params_list:
            if shutdown_requested['flag']:
                break
            _run_search_and_drain(params)

    should_regenerate_params = (
        not llm_params_list
        or (total_new_jobs == 0 and any_apify_search_ran)
    )
    if should_regenerate_params and not shutdown_requested['flag'] and utils.apify_state.is_available():
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
                _run_search_and_drain(params)
        else:
            print("Warning: Could not generate search parameters. Please check your resume and API keys.")

    return collected_jobs, total_new_jobs, company_overview_cache


def process_new_jobs_pipeline(db, resume_json, collected_jobs, company_overview_cache):
    """Process newly collected jobs through the full pipeline. Returns True if any progress."""
    progress = False
    if bulk_filter_collected_jobs(db, resume_json, target_jobs=collected_jobs, force_process=False) > 0:
        progress = True
    if CHECK_SUSTAINABILITY and fetch_company_overviews(db, company_overview_cache, target_jobs=collected_jobs) > 0:
        progress = True
    if CHECK_SUSTAINABILITY:
        print("\nValidating sustainability for new jobs...")
        if utils.validate_sustainability_for_unprocessed_jobs(db) > 0:
            progress = True
    if analyze_all_jobs(db, resume_json, target_jobs=collected_jobs) > 0:
        progress = True
    if process_resumes_and_cover_letters(db, resume_json, target_jobs=collected_jobs) > 0:
        progress = True
    return progress
