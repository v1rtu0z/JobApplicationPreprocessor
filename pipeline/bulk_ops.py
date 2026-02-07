"""Bulk LLM filtering, company overview fetch, and bulk JD fetch."""

import random
import time

import utils
from utils import (
    get_company_overviews_bulk_via_apify,
    fetch_job_descriptions_via_crawling,
    fetch_company_overviews_via_crawling,
    fetch_job_details_bulk_via_apify,
    match_job_to_apify_result,
    normalize_company_name,
    fit_score_to_enum,
    extract_job_id,
)
from api_methods import bulk_filter_jobs
from config import _get_job_filters, _save_job_filters, CONFIG_FILE

from .constants import (
    BULK_FILTER_BATCH_SIZE,
    COMPANY_OVERVIEW_BATCH_SIZE,
    CHECK_SUSTAINABILITY,
)

# Default dashboard filter: same as "Apply defaults" so we only fetch COs for jobs that would be visible.
DEFAULT_BAD_FIT_SCORES = ("Poor fit", "Very poor fit", "Questionable fit")


def _default_filter_job_keys(sheet) -> set:
    """Return set of (job_url, company_name) that pass the default dashboard filter."""
    all_rows = sheet.get_all_records()
    keys = set()
    for row in all_rows:
        if row.get("Applied") == "TRUE":
            continue
        if row.get("Job posting expired") == "TRUE":
            continue
        if row.get("Bad analysis") == "TRUE":
            continue
        fit = (row.get("Fit score") or "").strip()
        if fit and fit in DEFAULT_BAD_FIT_SCORES:
            continue
        if CHECK_SUSTAINABILITY and (row.get("Sustainable company") or "").strip() == "FALSE":
            continue
        job_url = (row.get("Job URL") or "").strip()
        company_name = (row.get("Company Name") or "").strip()
        if job_url and company_name:
            keys.add((job_url, company_name))
    return keys


def bulk_filter_collected_jobs(sheet, resume_json, target_jobs=None, force_process=False):
    """Apply bulk LLM filtering to jobs. Returns number of jobs filtered."""
    print("\n" + "=" * 60)
    print("BULK FILTERING: Using LLM to filter collected jobs")
    print("=" * 60 + "\n")

    all_rows = sheet.get_all_records()
    jobs_to_filter = []
    jobs_to_mark_filtered = []

    for row in all_rows:
        job_url = row.get('Job URL', '').strip()
        company_name = row.get('Company Name', '').strip()

        if target_jobs is not None:
            if (job_url, company_name) not in target_jobs:
                continue

        if row.get('Bulk filtered') == 'TRUE':
            continue

        if row.get('Fit score'):
            jobs_to_mark_filtered.append((job_url, company_name))
            continue

        if (row.get('Applied') == 'TRUE' or row.get('Bad analysis') == 'TRUE' or row.get('Job posting expired') == 'TRUE'):
            jobs_to_mark_filtered.append((job_url, company_name))
            continue

        if not row.get('Job Description') or not row.get('Company overview'):
            continue  # Can't bulk filter without JD and overview

        jobs_to_filter.append({
            'job_url': job_url,
            'company': company_name,
            'title': row.get('Job Title', ''),
            'overview': row.get('Company overview', ''),
            'description': row.get('Job Description', ''),
        })

    for job_url, company_name in jobs_to_mark_filtered:
        try:
            sheet.update_job_by_key(job_url, company_name, {'Bulk filtered': 'TRUE'})
        except Exception:
            pass

    if not jobs_to_filter and not force_process:
        print("No jobs to bulk filter")
        return 0

    if not force_process and len(jobs_to_filter) < BULK_FILTER_BATCH_SIZE:
        print(f"Only {len(jobs_to_filter)} jobs need bulk filtering (minimum {BULK_FILTER_BATCH_SIZE}). Skipping.")
        return 0

    total_filtered = 0
    batch_size = BULK_FILTER_BATCH_SIZE
    filters_updated = False
    current_filters = _get_job_filters()

    for i in range(0, len(jobs_to_filter), batch_size):
        batch = jobs_to_filter[i:i + batch_size]
        try:
            llm_input = [{'title': job['title'], 'company': job['company']} for job in batch]
            result = bulk_filter_jobs(llm_input, resume_json, max_retries=3)

            filtered_titles = result.get('filtered_titles', [])
            new_filters = result.get('new_filters', {})

            if new_filters:
                for key, val in new_filters.items():
                    if key in current_filters and val:
                        existing = set(current_filters[key])
                        for item in val:
                            if item and item.lower() not in existing:
                                current_filters[key].append(item)
                                existing.add(item.lower())
                                filters_updated = True

            filtered_set = set(filtered_titles)
            for job in batch:
                updates = {'Bulk filtered': 'TRUE'}
                if job['title'] in filtered_set:
                    updates.update({
                        'Fit score': 'Very poor fit',
                        'Fit score enum': str(fit_score_to_enum('Very poor fit')),
                        'Job analysis': 'Filtered by bulk analysis - wrong tech/role/domain'
                    })
                    print(f"  Filtered: {job['title']} @ {job['company']}")
                    total_filtered += 1
                sheet.update_job_by_key(job['job_url'], job['company'], updates)

        except Exception as e:
            print(f"Error in bulk filtering batch: {e}")
            for job in batch:
                try:
                    sheet.update_job_by_key(job['job_url'], job['company'], {'Bulk filtered': 'TRUE'})
                except Exception:
                    pass

        if i + batch_size < len(jobs_to_filter):
            time.sleep(random.uniform(2, 4))

    if filters_updated:
        _save_job_filters(current_filters)

    print(f"\nBulk filtering completed. Filtered {total_filtered} jobs")
    return total_filtered


def fetch_company_overviews(sheet, company_overview_cache, target_jobs=None):
    """Fetch company overviews: Apify first (prioritizing companies with multiple jobs), LinkedIn crawl as backup when Apify is unavailable or fails.
    Only fetches COs for jobs that pass the default dashboard filter."""
    print("\n" + "=" * 60)
    print("COMPANY OVERVIEW PHASE: Fetching missing company overviews")
    print("=" * 60 + "\n")

    default_filter_keys = _default_filter_job_keys(sheet)
    all_rows = sheet.get_all_records()
    company_jobs = {}  # company_key -> list of (job_url, company_name); use first company_name as display name

    for row in all_rows:
        job_url = row.get('Job URL', '').strip()
        company_name = row.get('Company Name', '').strip()
        if not job_url or not company_name:
            continue

        if target_jobs is not None:
            if (job_url, company_name) not in target_jobs:
                continue

        if (job_url, company_name) not in default_filter_keys:
            continue

        if row.get('Company overview') and str(row.get('Company overview')).strip():
            continue

        company_key = normalize_company_name(company_name)
        if company_key in company_overview_cache:
            sheet.update_job_by_key(job_url, company_name, {'Company overview': company_overview_cache[company_key]})
            continue

        if company_key not in company_jobs:
            company_jobs[company_key] = []
        company_jobs[company_key].append((job_url, company_name))

    if not company_jobs:
        return 0

    # Prioritize companies with more jobs (one CO benefits multiple rows)
    companies_sorted = sorted(
        company_jobs.keys(),
        key=lambda k: len(company_jobs[k]),
        reverse=True,
    )
    # Use first occurrence's company name for API/crawl (display name)
    company_names_ordered = []
    seen = set()
    for key in companies_sorted:
        first_company_name = company_jobs[key][0][1]
        if first_company_name not in seen:
            seen.add(first_company_name)
            company_names_ordered.append(first_company_name)

    print(f"Limiting to jobs visible with default dashboard filter ({len(default_filter_keys)} jobs).")
    print(f"Found {len(company_names_ordered)} unique companies missing CO (prioritizing companies with multiple jobs)")
    fetched_count = 0

    def apply_overview_to_sheet(company_name: str, overview: str):
        key = normalize_company_name(company_name)
        if key not in company_jobs:
            for k, jobs_list in company_jobs.items():
                if company_name in [j[1] for j in jobs_list]:
                    key = k
                    break
        if key not in company_jobs:
            return 0
        company_overview_cache[key] = overview
        n = 0
        for job_url, company in company_jobs[key]:
            sheet.update_job_by_key(job_url, company, {'Company overview': overview, 'CO fetch attempted': 'TRUE'})
            n += 1
        return n

    # 1) Apify first (when available)
    if utils.apify_state.is_available():
        for i in range(0, len(company_names_ordered), COMPANY_OVERVIEW_BATCH_SIZE):
            if not utils.apify_state.is_available():
                break
            batch = company_names_ordered[i:i + COMPANY_OVERVIEW_BATCH_SIZE]
            overview_map = get_company_overviews_bulk_via_apify(batch)
            for company_name, overview in overview_map.items():
                if overview:
                    n = apply_overview_to_sheet(company_name, overview)
                    fetched_count += n
            if i + COMPANY_OVERVIEW_BATCH_SIZE < len(company_names_ordered):
                time.sleep(random.uniform(2, 4))

    # Companies still missing CO (Apify didn't return for them or we didn't try Apify)
    remaining_after_apify = [
        c for c in company_names_ordered
        if normalize_company_name(c) not in company_overview_cache
    ]

    # 2) LinkedIn crawl only when Apify usage is exhausted (backup of last resort)
    if remaining_after_apify and not utils.apify_state.is_available():
        print("Apify unavailable (usage exhausted). Using LinkedIn crawl for remaining company overviews.")
        crawl_successful, crawl_failed = fetch_company_overviews_via_crawling(
            remaining_after_apify, headless=True, min_delay=12.0, max_delay=20.0
        )
        for company_name, overview in crawl_successful.items():
            n = apply_overview_to_sheet(company_name, overview)
            fetched_count += n
        for company_name in crawl_failed:
            key = normalize_company_name(company_name)
            if key in company_jobs:
                for job_url, company in company_jobs[key]:
                    sheet.update_job_by_key(job_url, company, {'CO fetch attempted': 'TRUE'})

    print(f"\nCompany overview fetching completed. Total fetched: {fetched_count} overviews.")
    return fetched_count


def bulk_fetch_missing_job_descriptions(sheet):
    """Fetch missing JDs via crawling then Apify fallback. Returns number updated."""
    from utils import fetch_job_descriptions_via_crawling

    all_rows = sheet.get_all_records()
    jobs_to_fetch = []
    good_fit_scores = {'Very good fit', 'Good fit', 'Moderate fit', ''}

    for row in all_rows:
        if row.get('Applied') == 'TRUE' or row.get('Bad analysis') == 'TRUE' or row.get('Job posting expired') == 'TRUE':
            continue
        if row.get('Sustainable company', '').strip() == 'FALSE':
            continue
        fit_score = row.get('Fit score', '').strip()
        if fit_score and fit_score not in good_fit_scores:
            continue
        if (row.get('JD crawl attempted') or '').strip() == 'TRUE':
            continue
        job_url = row.get('Job URL', '').strip()
        company = (row.get('Company Name') or '').strip()
        if not row.get('Job Description', '').strip() and job_url and company:
            jobs_to_fetch.append({
                'job_url': job_url,
                'company': company,
                'title': (row.get('Job Title') or '').strip()
            })

    if not jobs_to_fetch:
        print("  No jobs need JD fetching (all filtered out or already have JDs)")
        return 0

    _capitole_job_id = "4355288971"
    jobs_to_fetch = sorted(
        jobs_to_fetch,
        key=lambda x: _capitole_job_id in (x.get("job_url") or "").rstrip("/"),
        reverse=True,
    )

    print(f"\nFetching job descriptions for {len(jobs_to_fetch)} jobs...")

    def _persist_jd_result(result_type, job_data):
        job_url = (job_data.get('job_url') or '').strip()
        company = (job_data.get('company') or '').strip()
        if not job_url or not company:
            return
        updates = {'JD crawl attempted': 'TRUE'}
        if result_type == 'success':
            updates['Job Description'] = job_data['description']
        elif result_type == 'expired':
            updates['Job posting expired'] = 'TRUE'
        sheet.update_job_by_key(job_url, company, updates)

    try:
        successful, expired, failed = fetch_job_descriptions_via_crawling(
            jobs_to_fetch, headless=True, min_delay=5.0, max_delay=10.0, on_result=_persist_jd_result,
        )
    except KeyboardInterrupt:
        raise
    except Exception as e:
        print(f"\n  [ERROR] Crawling failed: {e}")
        import traceback
        traceback.print_exc()
        successful, expired, failed = [], [], []

    total_updated = len(successful)
    for job in expired:
        try:
            sheet.update_job_by_key(job['job_url'], job['company'], {'Job posting expired': 'TRUE'})
        except Exception:
            pass

    APIFY_MIN_BATCH_SIZE = 50
    if failed and len(failed) >= APIFY_MIN_BATCH_SIZE and utils.APIFY_AVAILABLE:
        apify_jobs = []
        for job in failed:
            job_id = extract_job_id(job['job_url'])
            if job_id:
                apify_jobs.append({**job, 'job_id': job_id})
        if apify_jobs:
            batch_ids = [j['job_id'] for j in apify_jobs]
            fetched_details = utils.fetch_job_details_bulk_via_apify(batch_ids)
            if fetched_details:
                for item in fetched_details:
                    job_info = item.get('job_info', {})
                    desc = job_info.get('description', '')
                    if not desc:
                        continue
                    for job in apify_jobs:
                        if match_job_to_apify_result(job, item):
                            updates = {'Job Description': desc}
                            comp_info = item.get('company_info', {})
                            co_desc = comp_info.get('description', '')
                            if co_desc:
                                updates['Company overview'] = co_desc
                                updates['CO fetch attempted'] = 'TRUE'
                            sheet.update_job_by_key(job['job_url'], job['company'], updates)
                            total_updated += 1
                            break

    return total_updated
