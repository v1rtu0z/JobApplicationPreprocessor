from datetime import datetime
import os
import random
import re
import subprocess
import sys
import time
import webbrowser

from api_methods import (
    get_resume_json, get_job_analysis, get_tailored_resume, get_tailored_cl,
    bulk_filter_jobs, get_search_parameters
)
from utils import (
    get_user_name, setup_spreadsheet, parse_location,
    get_location_priority, is_sustainable_company, update_cell, get_column_index,
    get_existing_jobs, parse_fit_score, html_to_markdown, SHEET_HEADER,
    setup_driver, scrape_multiple_pages, check_job_expiration,
    validate_sustainability_for_unprocessed_jobs,
    get_company_overviews_bulk_via_apify, fetch_jobs_via_apify,
    fetch_job_details_bulk_via_apify, retry_on_selenium_error, fit_score_to_enum,
    column_index_to_letter, normalize_company_name, match_job_to_apify_result
)
from config import _get_job_filters, _save_job_filters, CONFIG_FILE
import utils
from dotenv import load_dotenv

load_dotenv()

# Constants
BULK_FILTER_BATCH_SIZE = 100  # Number of jobs to process in each bulk filter batch
COMPANY_OVERVIEW_BATCH_SIZE = 1000  # Number of companies to fetch in each Apify batch
JOB_DESCRIPTION_BATCH_SIZE = 100  # Number of job descriptions to fetch in each batch
SUSTAINABILITY_CHECK_BATCH_SIZE = 10  # Number of companies to check for sustainability per batch
BULK_UPDATE_CHUNK_SIZE = 100  # Number of updates to send per batch update call

APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN")
email_address = os.getenv("EMAIL_ADDRESS")
linkedin_password = os.getenv("LINKEDIN_PASSWORD")
CHECK_SUSTAINABILITY = os.getenv("CHECK_SUSTAINABILITY", "false").lower() == "true"
CRAWL_LINKEDIN = os.getenv("CRAWL_LINKEDIN", "false").lower() == "true"

# Dashboard auto-open: Streamlit default port and delay before opening browser
DASHBOARD_URL = "http://localhost:8501"
DASHBOARD_LAUNCH_DELAY_SEC = 2.5


def _has_jobs_to_show(sheet) -> bool:
    """Return True if the sheet has at least one job (so the dashboard has something to show)."""
    try:
        rows = sheet.get_all_records()
        return bool(rows) and any(row.get("Job Title") for row in rows)
    except Exception:
        return False


def _launch_dashboard_once(sheet, launched_flag: dict) -> None:
    """If there are jobs and the dashboard has not been launched yet, start Streamlit and open the browser."""
    if launched_flag.get("launched"):
        return
    if not _has_jobs_to_show(sheet):
        return
    launched_flag["launched"] = True
    project_dir = os.path.dirname(os.path.abspath(__file__))
    dashboard_script = os.path.join(project_dir, "dashboard.py")
    if not os.path.isfile(dashboard_script):
        return
    try:
        subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", dashboard_script, "--server.headless", "true"],
            cwd=project_dir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        time.sleep(DASHBOARD_LAUNCH_DELAY_SEC)
        webbrowser.open(DASHBOARD_URL)
        print("\nDashboard opened in your browser. View and manage your job applications there.\n")
    except Exception as e:
        print(f"Could not auto-open dashboard: {e}. Run manually: streamlit run dashboard.py\n")


# --- Main Loop ---


def _apply_keyword_filters(job_title, company_name, raw_location, filters):
    """
    Apply keyword-based filters to determine if a job should be skipped.
    
    Args:
        job_title: Job title string
        company_name: Company name string
        raw_location: Location string
        filters: Dictionary containing filter keywords
        
    Returns:
        Tuple of (should_skip, skip_reason) where:
        - should_skip: bool indicating if job should be filtered
        - skip_reason: str with reason for skipping, or None if not skipped
    """
    should_skip_location = any(keyword in raw_location.lower() for keyword in filters['location_skip_keywords'])
    should_skip_title = any(keyword in job_title.lower() for keyword in filters['job_title_skip_keywords'])
    should_skip_title_2 = any(
        keyword in job_title.lower().split(' ') for keyword in filters['job_title_skip_keywords_2'])
    should_skip_company = any(keyword in normalize_company_name(company_name) for keyword in filters['company_skip_keywords'])

    if should_skip_title or should_skip_title_2:
        return True, 'Job title contains unwanted technology'
    elif should_skip_location:
        return True, 'Location not preferred'
    elif should_skip_company:
        return True, 'Company name contains unwanted keyword'
    
    return False, None


def _check_and_process_filters(job_title, company_name, raw_location, company_overview='', job_description='',
                               sheet=None):
    """
    Checks job details against skip keywords and prepares analysis data.
    
    Returns:
        Tuple of (fit_score, fit_score_enum, analysis_reason, sustainability_status, bulk_filtered)
        - fit_score: str or empty string if not filtered
        - fit_score_enum: int or empty string if not filtered
        - analysis_reason: str or empty string if not filtered
        - sustainability_status: bool or None (True/False/None)
        - bulk_filtered: str ('TRUE' or 'FALSE')
    """
    filters = _get_job_filters()

    # Apply keyword filters using shared function
    should_skip, skip_reason = _apply_keyword_filters(job_title, company_name, raw_location, filters)
    
    if should_skip:
        fit_score = 'Poor fit'
        fit_score_enum = fit_score_to_enum(fit_score)
        print(f"Skipping job due to filter: {job_title} @ {company_name}. Reason: {skip_reason}")
        return fit_score, fit_score_enum, skip_reason, None, 'TRUE'

    # Check sustainability (with sheet cache) - only if company overview is available
    is_sustainable = None
    if CHECK_SUSTAINABILITY and company_overview:
        is_sustainable = is_sustainable_company(company_name, company_overview, job_description, sheet)

    # If is_sustainable is None (insufficient data or API failure), skip sustainability filtering for now
    # The job will be processed later when data is available
    if is_sustainable is False:
        fit_score = 'Very poor fit'
        fit_score_enum = fit_score_to_enum(fit_score)
        analysis_reason = 'Unsustainable company (weapons/fossil fuels/harmful industries)'
        print(f"Skipping job due to filter: {job_title} @ {company_name}. Reason: {analysis_reason}")
        return fit_score, fit_score_enum, analysis_reason, False, 'TRUE'

    # Standardized return: empty strings for fit_score fields, None for sustainability, 'FALSE' for bulk_filtered
    return '', '', '', is_sustainable, 'FALSE'


def _normalize_job_title(job_title):
    """Cleans up the job title."""
    if not job_title or not isinstance(job_title, str):
        return ''
    job_title = job_title.strip()
    if not job_title:
        return ''
    
    lines = job_title.split('\n')
    if len(lines) == 1:
        return job_title

    # Check if lines are near-duplicates
    first_line = lines[0]
    is_duplicate = (len(set(lines)) == 1 or first_line in lines[1] or lines[1] in first_line)

    return first_line if is_duplicate else job_title


def _build_company_overview_cache(sheet):
    """
    Build a dictionary of company name -> company overview from existing sheet data.
    Uses case-insensitive matching and takes the first non-empty overview found.
    
    Returns:
        Dict mapping company_name_lower -> company_overview
    """
    all_rows = sheet.get_all_records()
    cache = {}
    for row in all_rows:
        company_name = row.get('Company Name', '').strip()
        company_overview = row.get('Company overview', '').strip()
        if company_name and company_overview:
            company_key = normalize_company_name(company_name)
            # Only add if not already in cache (first occurrence wins)
            if company_key not in cache:
                cache[company_key] = company_overview
    return cache



def collect_and_filter_jobs(driver, sheet, search_urls: list[str] = None):
    """
    Collect all jobs from search URLs, apply keyword filters, and add basic info to database.
    Returns list of (job_url, company_name) tuples for jobs that need detailed scraping.
    
    Args:
        driver: Selenium WebDriver
        sheet: Database object
        search_urls: List of LinkedIn search URLs to scrape. If None, returns empty list.
    """
    from linkedin_scraper import Job
    
    if not search_urls:
        print("No search URLs provided for LinkedIn crawling.")
        return []
    
    print("\n" + "=" * 60)
    print("COLLECTION PHASE: Gathering all jobs from search URLs")
    print("=" * 60 + "\n")

    existing_jobs = get_existing_jobs(sheet)
    filters = _get_job_filters()
    new_rows = []
    jobs_to_scrape = []  # List of (job_url, company_name) tuples

    for search_url in search_urls:
        print(f"Collecting jobs from search URL: {search_url}")
        job_listings = scrape_multiple_pages(driver, search_url, max_pages=5)
        print(f"Found {len(job_listings)} job listings")

        for job_obj in job_listings:
            try:
                # Basic validation
                if not (job_obj.job_title and job_obj.company):
                    continue

                job_title = _normalize_job_title(job_obj.job_title)
                company_name = job_obj.company.strip()
                job_url = getattr(job_obj, 'linkedin_url', None)

                if not job_url:
                    print(f"Warning: Job has no linkedin_url")
                    continue

                # Get basic location info (might be incomplete from search results)
                raw_location = getattr(job_obj, 'location', '')

                # Apply keyword filters (title and company only during collection)
                # Location filtering happens later when we have complete data
                should_skip, skip_reason = _apply_keyword_filters(job_title, company_name, raw_location, filters)
                
                if should_skip:
                    print(f"Skipping job due to title/company filter: {job_title} @ {company_name}. Reason: {skip_reason}")
                    continue

                # Check for duplicates and reprocessing logic
                job_key = f"{job_title} @ {company_name}"

                if job_key in existing_jobs:
                    # print(f"Skipping duplicate: {job_key}")
                    continue
                clean_location = parse_location(raw_location) if raw_location else ''
                location_priority = get_location_priority(clean_location)

                # Add basic job info to database (no description or company overview yet)
                row_data = [
                    company_name,  # Company Name
                    job_title,  # Job Title
                    clean_location,  # Location
                    location_priority,  # Location Priority
                    '',  # Job Description (empty - marker for needing scraping)
                    job_url,  # Job URL
                    '',  # Company url (kept for compatibility but no longer used)
                    '',  # Company overview (empty - will be filled via Apify)
                    '',  # Sustainable company
                    'FALSE', # CO fetch attempted
                    '',  # Fit score
                    '',  # Fit score enum
                    'FALSE',  # Bulk filtered (not yet checked)
                    '',  # Job analysis
                ]

                # Pad it to match SHEET_HEADER length.
                while len(row_data) < len(SHEET_HEADER):
                    row_data.append('')

                new_rows.append(row_data)
                existing_jobs.add(job_key)
                jobs_to_scrape.append((job_url, company_name))

                print(f"Collected job for detailed scraping: {job_key}")

            except Exception as e:
                print(f"Unexpected error collecting job: {getattr(job_obj, 'linkedin_url', 'Unknown URL')}. Error: {e}")
                continue

    if new_rows:
        print(f"Appending {len(new_rows)} new jobs to database...")
        sheet.append_rows(new_rows)
        print(f"Successfully added {len(new_rows)} jobs.")
    else:
        print("No new jobs found via LinkedIn crawl.")

    print(f"\nCollection phase completed. Added {len(new_rows)} new jobs. Total jobs to scrape: {len(jobs_to_scrape)}")
    return jobs_to_scrape


def bulk_filter_collected_jobs(sheet, resume_json, target_jobs=None, force_process=False):
    """
    Apply bulk LLM filtering to jobs that passed keyword filters.
    Groups jobs in batches and marks poor fits.
    Only processes jobs that haven't been bulk filtered yet.
    If target_jobs is provided, only processes those jobs (list of (job_url, company_name) tuples).
    
    If force_process is False, it will only call the LLM if there are at least 100 jobs.
    """
    print("\n" + "=" * 60)
    print("BULK FILTERING: Using LLM to filter collected jobs")
    print("=" * 60 + "\n")

    all_rows = sheet.get_all_records()

    # Collect jobs that need bulk filtering
    jobs_to_filter = []
    jobs_to_mark_filtered = []  # Jobs that just need 'Bulk filtered' = TRUE

    for row in all_rows:
        job_url = row.get('Job URL', '').strip()
        company_name = row.get('Company Name', '').strip()
        
        # If target_jobs is provided, skip if not in target
        if target_jobs is not None:
            if (job_url, company_name) not in target_jobs:
                continue

        # Skip if already bulk filtered
        if row.get('Bulk filtered') == 'TRUE':
            continue

        # Only filter jobs without a fit score
        if row.get('Fit score'):
            # Mark as bulk filtered even though it already has a score
            # (probably filtered by keywords during collection)
            jobs_to_mark_filtered.append((job_url, company_name))
            continue

        # Skip if expired, applied, or bad analysis
        if (row.get('Applied') == 'TRUE' or
                row.get('Bad analysis') == 'TRUE' or
                row.get('Job posting expired') == 'TRUE'):
            jobs_to_mark_filtered.append((job_url, company_name))
            continue

        job_title = row.get('Job Title', '').strip()
        if job_title and job_url and company_name:
            jobs_to_filter.append({
                'title': job_title,
                'job_url': job_url,
                'company': company_name
            })

    # Batch update jobs that just need 'Bulk filtered' = TRUE
    if jobs_to_mark_filtered:
        print(f"Marking {len(jobs_to_mark_filtered)} already-processed jobs as bulk filtered...")
        bulk_updates = [(job_url, company_name, {'Bulk filtered': 'TRUE'}) 
                       for job_url, company_name in jobs_to_mark_filtered]
        sheet.bulk_update_by_key(bulk_updates)

    if not jobs_to_filter:
        print("No jobs to bulk filter")
        return 0

    batch_size = BULK_FILTER_BATCH_SIZE
    
    # Only process if we have at least batch_size jobs or if forced
    if len(jobs_to_filter) < batch_size and not force_process:
        print(f"Holding {len(jobs_to_filter)} jobs for batching (need {batch_size} to call LLM)")
        return 0

    print(f"Found {len(jobs_to_filter)} jobs to bulk filter")

    total_filtered = 0
    filters_updated = False
    current_filters = _get_job_filters()

    for i in range(0, len(jobs_to_filter), batch_size):
        batch = jobs_to_filter[i:i + batch_size]
        
        # Don't process final small batch unless forced
        if len(batch) < batch_size and not force_process:
            print(f"Holding remaining {len(batch)} jobs for next batching cycle")
            break

        print(f"\nProcessing batch {i // batch_size + 1} ({len(batch)} jobs)...")

        try:
            from api_methods import bulk_filter_jobs
            # Prepare data for LLM
            llm_input = [{'title': job['title'], 'company': job['company']} for job in batch]
            
            result = bulk_filter_jobs(llm_input, resume_json, max_retries=3)
            
            filtered_titles = result.get('filtered_titles', [])
            new_filters = result.get('new_filters', {})

            # Update our YAML filters if new ones found
            if new_filters:
                for key, val in new_filters.items():
                    if key in current_filters and val:
                        # Append and deduplicate
                        existing = set(current_filters[key])
                        added = False
                        for item in val:
                            if item and item.lower() not in existing:
                                current_filters[key].append(item)
                                existing.add(item.lower())
                                added = True
                        if added:
                            filters_updated = True

            filtered_set = set(filtered_titles)

            for job in batch:
                # Always mark as bulk filtered
                updates = {'Bulk filtered': 'TRUE'}

                # Add additional updates if job was filtered
                if job['title'] in filtered_set:
                    updates.update({
                        'Fit score': 'Very poor fit',
                        'Fit score enum': str(fit_score_to_enum('Very poor fit')),
                        'Job analysis': 'Filtered by bulk analysis - wrong tech/role/domain'
                    })
                    print(f"  Filtered: {job['title']} @ {job['company']}")
                    total_filtered += 1

                sheet.update_job_by_key(job['job_url'], job['company'], updates)

            # Delay between batches 
            if i + batch_size < len(jobs_to_filter):
                time.sleep(random.uniform(2, 4))

        except Exception as e:
            print(f"Error in bulk filtering batch: {e}")
            print("Marking batch as checked and continuing with next batch...")

            # Mark the batch as checked even on error
            for job in batch:
                try:
                    sheet.update_job_by_key(job['job_url'], job['company'], {'Bulk filtered': 'TRUE'})
                except Exception as update_error:
                    print(f"Failed to mark job as filtered: {update_error}")

            continue

    if filters_updated:
        print("Saving updated filters to YAML...")
        _save_job_filters(current_filters)

    print(f"\nBulk filtering completed. Filtered {total_filtered} jobs")
    return total_filtered


def fetch_company_overviews(sheet, company_overview_cache, target_jobs=None):
    """
    Fetch company overviews for jobs that are missing them.
    Only processes jobs that don't have Poor/Very poor fit scores.
    Uses bulk Apify fetching for efficiency.
    If target_jobs is provided, only processes those jobs (list of (job_url, company_name) tuples).
    """
    import utils
    if not utils.APIFY_AVAILABLE:
        print("\nApify is currently unavailable (usage limit reached). Skipping company overview fetching.")
        return 0

    print("\n" + "=" * 60)
    print("COMPANY OVERVIEW PHASE: Fetching missing company overviews")
    print("=" * 60 + "\n")

    all_rows = sheet.get_all_records()

    # Collect companies that need fetching
    companies_to_fetch = []
    company_jobs = {}  # Map company name (lowercase) -> list of (job_url, company_name) tuples

    for row in all_rows:
        job_url = row.get('Job URL', '').strip()
        company_name = row.get('Company Name', '').strip()
        
        # If target_jobs is provided, skip if not in target
        if target_jobs is not None:
            if (job_url, company_name) not in target_jobs:
                continue

        # Skip if already has company overview
        co_val = row.get('Company overview')
        if co_val and str(co_val).strip():
            continue

        if row.get('Applied') == 'TRUE' or row.get('Bad analysis') == 'TRUE' or row.get(
                'Job posting expired') == 'TRUE':
            continue

        if not company_name or not job_url:
            continue

        # Check cache first (case-insensitive)
        company_key = normalize_company_name(company_name)
        if company_key in company_overview_cache:
            sheet.update_job_by_key(job_url, company_name, {'Company overview': company_overview_cache[company_key]})
            continue

        # Track this company for bulk fetching (use normalized key for consistency)
        if company_key not in company_jobs:
            companies_to_fetch.append(company_name)  # Use original name for Apify
            company_jobs[company_key] = []
        company_jobs[company_key].append((job_url, company_name))

    if not companies_to_fetch:
        print("No companies need overview fetching")
        return 0

    print(f"Found {len(companies_to_fetch)} unique companies to fetch")

    # Fetch in bulk
    fetched_count = 0
    batch_size = COMPANY_OVERVIEW_BATCH_SIZE

    for i in range(0, len(companies_to_fetch), batch_size):
        if not utils.APIFY_AVAILABLE:
            break
            
        batch = companies_to_fetch[i:i + batch_size]
        print(f"\nFetching batch of {len(batch)} companies...")

        # Get overviews via Apify
        overview_map = get_company_overviews_bulk_via_apify(batch)

        # First, mark all companies in the batch as attempted
        for company_name in batch:
            company_key_lower = normalize_company_name(company_name)
            if company_key_lower in company_jobs:
                for job_url, company in company_jobs[company_key_lower]:
                    sheet.update_job_by_key(job_url, company, {'CO fetch attempted': 'TRUE'})

        for company_name, overview in overview_map.items():
            # Store in cache with normalized key for case-insensitive lookup
            company_key_apify = normalize_company_name(company_name)
            company_overview_cache[company_key_apify] = overview

            # Find matching companies in tracking map (case-insensitive)
            matched = False
            
            # First try exact match
            if company_key_apify in company_jobs:
                for job_url, company in company_jobs[company_key_apify]:
                    sheet.update_job_by_key(job_url, company, {'Company overview': overview})
                    fetched_count += 1
                matched = True
            else:
                # Try substring matching as fallback
                for tracking_key, jobs_list in company_jobs.items():
                    # Check if one is a substring of another (case-insensitive)
                    if company_key_apify in tracking_key or tracking_key in company_key_apify:
                        for job_url, company in jobs_list:
                            sheet.update_job_by_key(job_url, company, {'Company overview': overview})
                            fetched_count += 1
                        matched = True
                        # Continue searching other tracking names as multiple might match
            
            if not matched:
                print(f"Warning: Company {company_name} returned from Apify but not found in tracking map")

        # Rate limiting between batches
        if i + batch_size < len(companies_to_fetch):
            time.sleep(random.uniform(2, 4))

    print(f"\nCompany overview fetching completed. Fetched {fetched_count} overviews.")
    return fetched_count



def delete_resume_local(resume_path: str):
    """
    Delete a resume from local storage.
    """
    if not resume_path:
        return

    from local_storage import delete_resume_local as delete_local
    delete_local(resume_path)


def _check_job_expiration_with_retry(driver, job_url, email_address, linkedin_password):
    """Check job expiration with retry logic on failure."""
    from linkedin_scraper import actions
    
    job_expired = check_job_expiration(driver, job_url)
    if job_expired is None:
        print(f"Error checking expiration for {job_url}. Resetting the driver and trying again...")
        driver.quit()
        del driver
        driver = setup_driver()
        actions.login(driver, email_address, linkedin_password)
        job_expired = check_job_expiration(driver, job_url)
    return job_expired, driver


def _fetch_job_data_from_linkedin(driver, job_url, needs_jd, needs_location):
    """Fetch missing job data from LinkedIn."""
    from linkedin_scraper import Job
    
    try:
        job_obj = Job(job_url, driver=driver, close_on_complete=False, scrape=False)

        @retry_on_selenium_error(max_retries=3, delay=5)
        def scrape_with_retry(job_obj):
            job_obj.scrape(close_on_complete=False)
            return job_obj.to_dict()

        job_dict = scrape_with_retry(job_obj)
        updates = {}
        
        if needs_jd:
            job_description = (
                job_dict.get('job_description', '')
                .replace('About the job\n', '')
                .replace('\nSee less', '')
                .strip()
            )
            updates['Job Description'] = job_description
            print(f"  - Fetched Job Description")

        if needs_location:
            raw_location = job_dict.get('location', '')
            clean_location = parse_location(raw_location)
            location_priority = get_location_priority(clean_location)
            updates['Location'] = clean_location
            updates['Location Priority'] = str(location_priority)
            print(f"  - Fetched Location: {clean_location}")
        
        return updates
    except Exception as e:
        print(f"Error fetching data for {job_url}: {e}")
        return None


def _should_skip_expiration_check(row, needs_jd, needs_location):
    """Check if expiration check should be skipped based on last check time."""
    last_checked = row.get('Last expiration check')
    if not last_checked:
        return False
    
    try:
        last_checked_time = datetime.fromisoformat(last_checked)
        if (datetime.now() - last_checked_time).total_seconds() < 3600 and not (needs_jd or needs_location):
            minutes_ago = int((datetime.now() - last_checked_time).total_seconds() / 60)
            print(f"Skipping expiration check (checked {minutes_ago} minutes ago): {row.get('Job Title')} @ {row.get('Company Name')}")
            return True
    except (ValueError, TypeError):
        pass  # Invalid timestamp, proceed with check
    return False


def validate_jobs_and_fetch_missing_data(driver, sheet):
    """
    Validate non-applied good-fit jobs (check expiration, apply filters).
    Also fetches missing Job Descriptions, Locations, and stores Company URLs.
    Marks expired jobs and deletes their resumes.
    """
    from linkedin_scraper import actions
    
    if not CRAWL_LINKEDIN:
        return 0
    print("\n" + "=" * 60)
    print("JOB VALIDATION: Checking expirations and fetching missing data")
    print("=" * 60 + "\n")

    all_rows = sheet.get_all_records()
    expired_count = 0
    fetched_count = 0
    not_logged_in = False

    for row in all_rows:
        if not row.get('Job Title'):
            break
        
        job_url = row.get('Job URL', '').strip()
        company_name = row.get('Company Name', '').strip()
        if not job_url or not company_name:
            continue

        fit_score = row.get('Fit score')
        if fit_score and fit_score not in ['Good fit', 'Very good fit']:
            continue

        if row.get('Applied') == 'TRUE' or row.get('Bad analysis') == 'TRUE' or row.get(
                'Job posting expired') == 'TRUE':
            continue

        needs_jd = not row.get('Job Description')
        needs_location = not row.get('Location')

        if _should_skip_expiration_check(row, needs_jd, needs_location):
            continue

        if CRAWL_LINKEDIN and not_logged_in:
            actions.login(driver, email_address, linkedin_password)
            not_logged_in = False

        print(f"Checking expiration for: {row.get('Job Title')} @ {company_name}")

        job_expired = False
        if CRAWL_LINKEDIN:
            job_expired, driver = _check_job_expiration_with_retry(driver, job_url, email_address, linkedin_password)
            not_logged_in = False

        if job_expired:
            print(f"Job has expired: {row.get('Job Title')} @ {company_name}")
            sheet.update_job_by_key(job_url, company_name, {'Job posting expired': 'TRUE'})

            resume_url = row.get('Tailored resume url')
            if resume_url:
                delete_resume_local(resume_url)

            expired_count += 1
        else:
            # Double-check filters for non-expired jobs
            job_title = row.get('Job Title', '')
            raw_location = row.get('Location', '')
            company_overview = row.get('Company overview', '')
            job_description = row.get('Job Description', '')

            fit_score_result, fit_score_enum, analysis_reason, _, bulk_filtered = _check_and_process_filters(
                job_title, company_name, raw_location, company_overview, job_description, sheet=sheet
            )

            if fit_score_result:
                updates = {
                    'Fit score': fit_score_result,
                    'Fit score enum': str(fit_score_enum),
                    'Job analysis': analysis_reason,
                    'Bulk filtered': bulk_filtered
                }
                sheet.update_job_by_key(job_url, company_name, updates)
                print(f"  - Filtered job: {analysis_reason}")

            sheet.update_job_by_key(job_url, company_name, {'Last expiration check': datetime.now().isoformat()})

        if needs_jd or needs_location:
            print(f"Fetching missing data for: {row.get('Job Title')} @ {company_name}")
            updates = _fetch_job_data_from_linkedin(driver, job_url, needs_jd, needs_location)
            if updates:
                sheet.update_job_by_key(job_url, company_name, updates)
                fetched_count += 1

    print(f"\nExpiration check completed. Found {expired_count} expired jobs. Fetched data for {fetched_count} jobs.")
    return expired_count + fetched_count


def analyze_single_job(sheet, row, resume_json) -> str | None:
    """
    Analyze a single job and update the database.
    Returns the fit score if analysis was performed, None if skipped.
    Note: Jobs filtered during scraping will already have a fit score.
    """
    if row.get('Fit score'):
        return row.get('Fit score')

    job_title = row.get('Job Title', '')
    company_name = row.get('Company Name', '')
    job_url = row.get('Job URL', '')
    
    print(f"Analyzing: {job_title} @ {company_name}")

    job_details = {
        'company_name': company_name,
        'job_title': job_title,
        'job_description': row.get('Job Description', ''),
        'location': row.get('Location', ''),
        'company_overview': row.get('Company overview', ''),
    }

    # Perform job analysis via API
    try:
        job_analysis = get_job_analysis(resume_json, job_details)
        fit_score = parse_fit_score(job_analysis)

        updates = {
            'Fit score': fit_score,
            'Fit score enum': str(fit_score_to_enum(fit_score)),
            'Job analysis': html_to_markdown(job_analysis)
        }
        sheet.update_job_by_key(job_url, company_name, updates)

        # Immediately process Very good fit jobs
        if fit_score == 'Very good fit':
            print("\n" + "*" * 60)
            print(f"🌟 GREAT FIT DETECTED! 🌟")
            print(f"Job: {job_title} @ {company_name}")
            print(f"Immediately processing resume and cover letter...")
            print("*" * 60 + "\n")
            try:
                process_cover_letter(sheet, row, resume_json)
                process_resume(sheet, row, resume_json)
            except Exception as e:
                print(f"Error immediately processing Very good fit job: {e}")
        elif fit_score in ['Good fit', 'Moderate fit']:
            print(f"Found a {fit_score}: {job_title} @ {company_name}")

        print(f"Added analysis for: {job_title} @ {company_name}")
        return fit_score

    except Exception as e:
        error_message = str(e)
        if '429' in error_message or 'Rate limit' in error_message:
            # Log and continue for rate limit errors
            print(
                f"Rate limit hit for job analysis: {row.get('Job Title')} @ {row.get('Company Name')}. Skipping for now.")
            return None


def analyze_all_jobs(sheet, resume_json, target_jobs=None):
    """
    First loop: Analyze all jobs that don't have a fit score yet.
    Returns the number of jobs analyzed.
    If target_jobs is provided, only processes those jobs (list of (job_url, company_name) tuples).
    """
    print("\n" + "=" * 60)
    print("ANALYSIS LOOP: Analyzing all unprocessed jobs")
    print("=" * 60 + "\n")

    all_rows = sheet.get_all_records()
    analyzed_count = 0
    consecutive_analysis_failure_count = 0
    skipped_reasons = {}
    # One example job (company, title) per reason so users can see which bucket a job is in
    skipped_example = {}

    # Order of checks in the pipeline: expired first (can't fetch JD), then JD, then CO, then fit score, then sustainability
    def _record_skip(reason, company_name, job_title, row_for_breakdown=None):
        skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1
        if reason not in skipped_example:
            skipped_example[reason] = (company_name or "?", job_title or "?")
        if row_for_breakdown is not None and reason == "Missing Job Description":
            if row_for_breakdown.get('Job posting expired') == 'TRUE':
                breakdown["missing_jd_also_expired"] = breakdown.get("missing_jd_also_expired", 0) + 1
            if str(row_for_breakdown.get('Sustainable company', '')).strip().upper() == 'FALSE':
                breakdown["missing_jd_unsustainable"] = breakdown.get("missing_jd_unsustainable", 0) + 1

    breakdown = {}  # extra stats for Missing JD: also_expired, unsustainable

    for row in all_rows:
        if not row.get('Job Title'):
            break

        job_url = row.get('Job URL', '').strip()
        company_name = row.get('Company Name', '').strip()
        job_title = row.get('Job Title', '').strip()

        # If target_jobs is provided, skip if not in target
        if target_jobs is not None:
            if (job_url, company_name) not in target_jobs:
                continue

        # 1. Expired first: we can't fetch JD for expired jobs, so attribute skip to expired not missing JD
        if row.get('Job posting expired') == 'TRUE':
            _record_skip("Job posting expired", company_name, job_title)
            continue

        if not row.get('Job Description'):
            _record_skip("Missing Job Description", company_name, job_title, row_for_breakdown=row)
            continue

        if not row.get('Company overview'):
            _record_skip("Missing Company overview", company_name, job_title)
            continue

        fit_score_val = (row.get('Fit score') or '').strip()
        if fit_score_val in ['Poor fit', 'Very poor fit', 'Moderate fit', 'Questionable fit']:
            _record_skip("Already has non-good fit score (poor/moderate/questionable)", company_name, job_title)
            continue
        if fit_score_val in ['Good fit', 'Very good fit'] or fit_score_val:
            continue  # already has good fit or other score; no need to re-analyze or count

        if CHECK_SUSTAINABILITY and row.get('Sustainable company', '').strip().upper() != 'TRUE':
            _record_skip("Unsustainable or pending sustainability check", company_name, job_title)
            continue

        fit_score = analyze_single_job(sheet, row, resume_json)
        if fit_score:
            analyzed_count += 1
            consecutive_analysis_failure_count = 0
        else:
            consecutive_analysis_failure_count += 1
            if consecutive_analysis_failure_count >= 5:
                print(
                    f"Skipping further analysis due to {consecutive_analysis_failure_count} consecutive analysis failures.")
                break

    # Report in pipeline order: downstream gates first, then earlier gates (expired last in report = checked first in pipeline)
    REPORT_ORDER = [
        "Unsustainable or pending sustainability check",
        "Already has non-good fit score (poor/moderate/questionable)",
        "Missing Company overview",
        "Missing Job Description",
        "Job posting expired",
    ]

    if skipped_reasons:
        print("Summary of skipped jobs in analysis (downstream gates first; pipeline checks expired before JD):")
        for reason in REPORT_ORDER:
            count = skipped_reasons.get(reason, 0)
            if count == 0:
                continue
            example = skipped_example.get(reason, (None, None))
            line = f"  - {count} jobs skipped: {reason}"
            if example[0] and example[1]:
                line += f" (e.g. {example[0]} – {example[1]})"
            if reason == "Missing Job Description" and (breakdown.get("missing_jd_also_expired") or breakdown.get("missing_jd_unsustainable")):
                parts = []
                if breakdown.get("missing_jd_also_expired"):
                    parts.append(f"{breakdown['missing_jd_also_expired']} also marked expired (pipeline bug if >0)")
                if breakdown.get("missing_jd_unsustainable"):
                    parts.append(f"{breakdown['missing_jd_unsustainable']} have Sustainable=FALSE (would be skipped later anyway)")
                if parts:
                    line += "\n      " + "; ".join(parts)
            print(line)
        for reason, count in skipped_reasons.items():
            if reason not in REPORT_ORDER:
                example = skipped_example.get(reason, (None, None))
                if example[0] and example[1]:
                    print(f"  - {count} jobs skipped: {reason} (e.g. {example[0]} – {example[1]})")
                else:
                    print(f"  - {count} jobs skipped: {reason}")

    print(f"\nAnalysis loop completed. Analyzed {analyzed_count} jobs.")
    return analyzed_count


def process_cover_letter(sheet, row, resume_json) -> bool:
    """Process cover letter generation/regeneration for a job. Returns True if work was done."""
    job_url = row.get('Job URL', '')
    company_name = row.get('Company Name', '')
    job_title = row.get('Job Title', '')
    
    job_details = {
        'company_name': company_name,
        'job_title': job_title,
        'job_description': row.get('Job Description', ''),
        'location': row.get('Location', ''),
    }

    # Handle feedback-based regeneration
    if row.get('CL feedback') and row.get('CL feedback addressed') != 'TRUE':
        print(f"Regenerating cover letter with feedback for: {job_title} @ {company_name}")
        try:
            current_cl = row.get('Tailored cover letter (to be humanized)', '')
            feedback = row.get('CL feedback')

            tailored_cl = get_tailored_cl(resume_json, job_details, current_cl, feedback)
            
            # Store full text in database
            from local_storage import save_cover_letter_local, get_local_file_path
            from utils import get_user_name
            user_name = get_user_name(resume_json).replace(' ', '_')
            company_name_safe = company_name.replace(' ', '_')
            filename = get_local_file_path(user_name, company_name_safe, 'cover_letter')
            save_cover_letter_local(tailored_cl, filename)
            
            updates = {
                'Tailored cover letter (to be humanized)': tailored_cl,
                'CL feedback addressed': 'TRUE'
            }
            sheet.update_job_by_key(job_url, company_name, updates)
            print(f"Regenerated cover letter for: {job_title}")
            return True
        except Exception as e:
            print(f"Error regenerating cover letter: {e}")
        return False

    # Generate initial cover letter
    if not row.get('Tailored cover letter (to be humanized)'):
        print(f"Generating cover letter for: {job_title} @ {company_name}")
        try:
            tailored_cl = get_tailored_cl(resume_json, job_details)
            
            # Store full text in database
            from local_storage import save_cover_letter_local, get_local_file_path
            from utils import get_user_name
            user_name = get_user_name(resume_json).replace(' ', '_')
            company_name_safe = company_name.replace(' ', '_')
            filename = get_local_file_path(user_name, company_name_safe, 'cover_letter')
            save_cover_letter_local(tailored_cl, filename)
            
            sheet.update_job_by_key(job_url, company_name, {'Tailored cover letter (to be humanized)': tailored_cl})
            print(f"Generated cover letter for: {job_title}")
            return True
        except Exception as e:
            print(f"Error generating cover letter: {e}")
    return False


def process_resume(sheet, row, resume_json) -> bool:
    """Process resume generation/regeneration for a job. Returns True if work was done."""
    job_url = row.get('Job URL', '')
    company_name = row.get('Company Name', '')
    job_title = row.get('Job Title', '')
    
    job_details = {
        'company_name': company_name,
        'job_title': job_title,
        'job_description': row.get('Job Description', ''),
        'location': row.get('Location', ''),
    }

    # Handle feedback-based regeneration
    if row.get('Resume feedback') and row.get('Resume feedback addressed') != 'TRUE':
        print(f"Regenerating resume with feedback for: {job_title} @ {company_name}")
        try:
            current_resume_json = row.get('Tailored resume json', '')
            feedback = row.get('Resume feedback')

            tailored_json_str, filename, pdf_bytes = get_tailored_resume(
                resume_json,
                job_details,
                current_resume_json,
                feedback
            )

            from local_storage import save_resume_local
            resume_path = save_resume_local(pdf_bytes, filename)

            updates = {
                'Tailored resume url': resume_path,
                'Tailored resume json': tailored_json_str,
                'Resume feedback addressed': 'TRUE'
            }
            sheet.update_job_by_key(job_url, company_name, updates)

            print(f"Regenerated resume for: {job_title}")
            return True
        except Exception as e:
            print(f"Error regenerating resume: {e}")
        return False

    # Generate initial resume
    if not row.get('Tailored resume url'):
        print(f"Generating tailored resume for: {job_title} @ {company_name}")
        try:
            tailored_json_str, filename, pdf_bytes = get_tailored_resume(resume_json, job_details)

            from local_storage import save_resume_local
            resume_path = save_resume_local(pdf_bytes, filename)

            updates = {
                'Tailored resume url': resume_path,
                'Tailored resume json': tailored_json_str
            }
            sheet.update_job_by_key(job_url, company_name, updates)

            print(f"Generated tailored resume for: {job_title}")
            return True
        except Exception as e:
            print(f"Error generating tailored resume: {e}")
    return False


def process_resumes_and_cover_letters(sheet, resume_json, target_jobs=None):
    """
    Second loop: Process resumes and cover letters for good fit jobs.
    Processes jobs in sorted order (by fit score and location priority).
    If target_jobs is provided, only processes those jobs (list of (job_url, company_name) tuples).
    """
    print("\n" + "=" * 60)
    print("PROCESSING LOOP: Generating resumes and cover letters")
    print("=" * 60 + "\n")

    all_rows = sheet.get_all_records()
    processed_count = 0

    for row in all_rows:
        if not row.get('Job Title'):
            break

        job_url = row.get('Job URL', '').strip()
        company_name = row.get('Company Name', '').strip()
        
        # If target_jobs is provided, skip if not in target
        if target_jobs is not None:
            if (job_url, company_name) not in target_jobs:
                continue

        fit_score = row.get('Fit score')

        # Skip if not a good fit
        if fit_score not in ['Good fit', 'Very good fit']:
            continue

        # Clean up if already applied, bad analysis, or expired
        job_url = row.get('Job URL', '')
        company_name = row.get('Company Name', '')
        if row.get('Applied') == 'TRUE' or row.get('Bad analysis') == 'TRUE' or row.get(
                'Job posting expired') == 'TRUE':
            resume_url = row.get('Tailored resume url')
            if resume_url:
                delete_resume_local(resume_url)
                sheet.update_job_by_key(job_url, company_name, {
                    'Tailored resume url': '',
                    'Tailored resume json': ''
                })
            continue

        # Process cover letter
        cl_done = process_cover_letter(sheet, row, resume_json)

        # Process resume
        resume_done = process_resume(sheet, row, resume_json)

        if cl_done or resume_done:
            processed_count += 1

    print(f"\nProcessing loop completed. Processed {processed_count} jobs.")
    return processed_count


def collect_jobs_via_apify(sheet, search_url=None, params=None):
    """
    Collect jobs using Apify Actor, apply keyword filters, and add basic info to database.
    Requires either search_url or params to be provided.
    Returns list of (job_url, company_name) tuples for new jobs.
    """
    import utils
    if not utils.APIFY_AVAILABLE:
        print("Apify is currently unavailable (usage limit reached). Skipping collection phase.")
        return []
    
    if not params and not search_url:
        print("No search parameters or URL provided for Apify collection.")
        return []

    print("\n" + "=" * 60)
    print("COLLECTION PHASE (Apify): Gathering jobs from LinkedIn via Apify")
    print("=" * 60 + "\n")

    existing_jobs = get_existing_jobs(sheet)
    filters = _get_job_filters()
    new_rows = []
    new_job_identifiers = []
    
    if params:
        # If specific params are provided, we just process those
        inputs = [{'params': params}]
    else:
        # If specific search_url is provided
        inputs = [{'search_url': search_url}]

    for item_input in inputs:
        if not utils.APIFY_AVAILABLE:
            break
            
        url = item_input.get('search_url')
        p = item_input.get('params')
        
        if p:
            print(f"Fetching jobs via Apify for params: {p.get('keywords')} in {p.get('location')}")
            job_items = fetch_jobs_via_apify(params=p)
        else:
            print(f"Fetching jobs for search URL via Apify: {url}")
            job_items = fetch_jobs_via_apify(search_url=url)

        for item in job_items:
            try:
                # The actor output has fields: company, job_title, job_url, location, etc.
                job_title_raw = item.get('job_title', '')
                company_name = item.get('company', '').strip()
                job_url = item.get('job_url', '')
                raw_location = item.get('location', '')

                if not (job_title_raw and company_name and job_url):
                    continue

                job_title = _normalize_job_title(job_title_raw)

                # Apply keyword filters using shared function
                should_skip, _ = _apply_keyword_filters(job_title, company_name, raw_location, filters)
                
                if should_skip:
                    print(f"Skipping job due to title/company filter: {job_title} @ {company_name}")
                    continue

                # Check for duplicates
                job_key = f"{job_title} @ {company_name}"
                if job_key in existing_jobs:
                    # print(f"Skipping duplicate: {job_key}")
                    continue

                clean_location = parse_location(raw_location) if raw_location else ''
                location_priority = get_location_priority(clean_location)

                # Extract job description from Apify if available
                # Apify may return: description, job_description, or jobDescription
                job_description = (
                    item.get('description', '') or 
                    item.get('job_description', '') or 
                    item.get('jobDescription', '') or
                    item.get('jobDescriptionText', '')
                ).strip()

                # Add basic job info to sheet
                row_data = [
                    company_name,  # Company Name
                    job_title,  # Job Title
                    clean_location,  # Location
                    location_priority,  # Location Priority
                    job_description,  # Job Description (from Apify if available, otherwise empty)
                    job_url,  # Job URL
                    '',  # Company url
                    '',  # Company overview
                    '',  # Sustainable company
                    'FALSE', # CO fetch attempted
                    '',  # Fit score
                    '',  # Fit score enum
                    'FALSE',  # Bulk filtered
                    '',  # Job analysis
                ]

                # Ensure row_data length matches SHEET_HEADER if possible, 
                # but append_row will just fill what it has.
                # SHEET_HEADER has 24 columns, we provided 13.
                # Let's pad it to match SHEET_HEADER length.
                while len(row_data) < len(SHEET_HEADER):
                    row_data.append('')

                new_rows.append(row_data)
                existing_jobs.add(job_key)
                new_job_identifiers.append((job_url, company_name))

                print(f"Collected job via Apify: {job_key}")

            except Exception as e:
                print(f"Unexpected error processing Apify job item: {item}. Error: {e}")
                continue

    if new_rows:
        print(f"Appending {len(new_rows)} new jobs to database...")
        sheet.append_rows(new_rows)
        print(f"Successfully added {len(new_rows)} jobs.")
    else:
        print("No new jobs found via Apify.")

    return new_job_identifiers


def bulk_fetch_missing_job_descriptions(sheet):
    """
    Fetch missing job descriptions in bulk using Apify.
    Triggered when there are at least 100 missing descriptions.
    """
    import utils
    if not utils.APIFY_AVAILABLE:
        return 0

    all_rows = sheet.get_all_records()
    jobs_to_fetch = []
    
    # Extract IDs from URLs for jobs missing descriptions
    for row in all_rows:
        if row.get('Applied') == 'TRUE' or row.get('Bad analysis') == 'TRUE' or row.get('Job posting expired') == 'TRUE':
            continue
            
        job_url = row.get('Job URL', '').strip()
        if not row.get('Job Description', '').strip() and job_url:
            from bulk_populate_descriptions import extract_job_id
            job_id = extract_job_id(job_url)
            if job_id:
                jobs_to_fetch.append({
                    'job_url': job_url,
                    'company': row.get('Company Name', ''),
                    'job_id': job_id,
                    'title': row.get('Job Title', '')
                })

    if len(jobs_to_fetch) < JOB_DESCRIPTION_BATCH_SIZE:
        return 0

    print(f"\nTriggering bulk job description fetch for {len(jobs_to_fetch)} jobs...")
    
    # Process in batches
    batch_size = JOB_DESCRIPTION_BATCH_SIZE
    total_updated = 0
    
    for i in range(0, len(jobs_to_fetch), batch_size):
        batch = jobs_to_fetch[i:i + batch_size]
        batch_ids = [job['job_id'] for job in batch]
        
        fetched_details = utils.fetch_job_details_bulk_via_apify(batch_ids)
        if not fetched_details:
            break
            
        for item in fetched_details:
            job_info = item.get('job_info', {})
            desc = job_info.get('description', '')
            if not desc:
                continue
            
            # Match back to batch using shared matching function
            for job in batch:
                if match_job_to_apify_result(job, item):
                    updates = {'Job Description': desc, 'CO fetch attempted': 'TRUE'}
                    comp_info = item.get('company_info', {})
                    co_desc = comp_info.get('description', '')
                    if co_desc:
                        updates['Company overview'] = co_desc
                    sheet.update_job_by_key(job['job_url'], job['company'], updates)
                    total_updated += 1
                    break
                    
    return total_updated


def setup_and_validate():
    """Perform initial setup validation and load environment variables."""
    from check_setup import check_setup
    
    load_dotenv()
    critical_vars = ['SERVER_URL', 'API_KEY', 'GEMINI_API_KEY']
    missing_vars = [v for v in critical_vars if not os.getenv(v)]
    if missing_vars:
        print(f"CRITICAL ERROR: Missing environment variables: {', '.join(missing_vars)}")
        print("Please check your .env file. Refer to .env.example and setup_guide.md.")
        return False
    return True


def setup_signal_handlers():
    """Set up signal handlers for graceful shutdown."""
    import signal
    
    shutdown_requested = {'flag': False}
    
    def signal_handler(signum, frame):
        print("\n\nShutdown signal received. Finishing current operation and exiting...")
        shutdown_requested['flag'] = True
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    if hasattr(signal, 'SIGBREAK'):
        signal.signal(signal.SIGBREAK, signal_handler)
    
    return shutdown_requested


def initialize_job_preferences():
    """Ensure job_preferences.yaml exists."""
    from config import CONFIG_FILE
    if not os.path.exists(CONFIG_FILE):
        import shutil
        example_file = 'job_preferences.yaml.example'
        if os.path.exists(example_file):
            print(f"Creating {CONFIG_FILE} from example...")
            shutil.copy(example_file, CONFIG_FILE)
        else:
            print(f"Creating default {CONFIG_FILE}...")
            filters = _get_job_filters()
            _save_job_filters(filters)


def initialize_storage(user_name: str):
    """Initialize local SQLite storage."""
    print("\n" + "!" * 60)
    print("Using local storage mode (SQLite database).")
    print("Note: To view your jobs, use the Streamlit dashboard: streamlit run dashboard.py")
    print("!" * 60 + "\n")
    from local_storage import ensure_local_directories
    ensure_local_directories()
    
    sheet = setup_spreadsheet(user_name)
    return sheet


def check_incomplete_jobs(sheet) -> bool:
    """Check if there are jobs with missing data that can be fetched."""
    all_rows = sheet.get_all_records()
    import utils
    
    for row in all_rows:
        if not row.get('Job Title') or row.get('Applied') == 'TRUE' or row.get('Bad analysis') == 'TRUE' or row.get('Job posting expired') == 'TRUE':
            continue
        
        needs_jd = not row.get('Job Description') and CRAWL_LINKEDIN
        needs_co = not row.get('Company overview') and utils.apify_state.is_available()
        
        can_get_jd = row.get('Job Description') or CRAWL_LINKEDIN
        can_get_co = row.get('Company overview') or utils.apify_state.is_available()
        needs_analysis = not row.get('Fit score') and can_get_jd and can_get_co
        
        if needs_jd or needs_co or needs_analysis:
            return True
    
    return False


def process_collection_phase(sheet, resume_json, shutdown_requested, company_overview_cache=None):
    """Handle job collection from Apify and search parameter generation.
    
    Args:
        sheet: Database object
        resume_json: Resume JSON data
        shutdown_requested: Shutdown flag dict
        company_overview_cache: Optional existing cache dict to update (avoids rebuilding)
    """
    import utils
    
    # Only rebuild cache if not provided
    # Note: Cache is maintained incrementally by fetch_company_overviews() when new overviews are fetched,
    # so we don't need to scan the database here for incremental updates
    if company_overview_cache is None:
        company_overview_cache = _build_company_overview_cache(sheet)
    
    filters = _get_job_filters()
    llm_params_list = filters.get('search_parameters', [])
    
    collected_jobs = []
    total_new_jobs = 0
    
    # Try cached search parameters first
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
    
    # Generate search parameters if none exist or no new jobs found
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
    """Process newly collected jobs through the full pipeline."""
    progress = False
    
    if bulk_filter_collected_jobs(sheet, resume_json, target_jobs=collected_jobs, force_process=False) > 0:
        progress = True
    
    if fetch_company_overviews(sheet, company_overview_cache, target_jobs=collected_jobs) > 0:
        progress = True
    
    if CHECK_SUSTAINABILITY:
        print("\nValidating sustainability for new jobs...")
        if validate_sustainability_for_unprocessed_jobs(sheet) > 0:
            progress = True
    
    if analyze_all_jobs(sheet, resume_json, target_jobs=collected_jobs) > 0:
        progress = True
    
    if process_resumes_and_cover_letters(sheet, resume_json, target_jobs=collected_jobs) > 0:
        progress = True
    
    return progress


def process_linkedin_collection(sheet, resume_json, company_overview_cache, shutdown_requested):
    """Handle LinkedIn scraping if enabled."""
    if not CRAWL_LINKEDIN:
        return False
    
    from linkedin_scraper import actions
    
    driver = setup_driver()
    actions.login(driver, email_address, linkedin_password)
    
    progress = False
    
    # Check for expired job postings
    print("\nChecking for expired job postings...")
    if validate_jobs_and_fetch_missing_data(driver, sheet) > 0:
        progress = True
    
    # Collect and filter jobs from search URLs
    print("Collecting jobs from LinkedIn search results...")
    jobs_to_scrape = collect_and_filter_jobs(driver, sheet)
    
    if jobs_to_scrape:
        progress = True
        # jobs_to_scrape is now list of (job_url, company_name) tuples
        li_jobs = jobs_to_scrape
        
        validate_jobs_and_fetch_missing_data(driver, sheet)
        bulk_filter_collected_jobs(sheet, resume_json, target_jobs=li_jobs, force_process=False)
        fetch_company_overviews(sheet, company_overview_cache, target_jobs=li_jobs)
        analyze_all_jobs(sheet, resume_json, target_jobs=li_jobs)
        process_resumes_and_cover_letters(sheet, resume_json, target_jobs=li_jobs)
    
    return progress


def _handle_sleep_logic(has_incomplete_jobs, progress_made_in_cycle, last_check_time, 
                        current_sleep_interval, base_sleep_interval, shutdown_requested):
    """Handle sleep logic with exponential backoff."""
    import time
    
    time_since_last_check = time.time() - last_check_time
    should_sleep = (not has_incomplete_jobs or (not progress_made_in_cycle and last_check_time > 0)) and time_since_last_check < current_sleep_interval
    
    if should_sleep:
        sleep_time = current_sleep_interval - time_since_last_check
        if not has_incomplete_jobs:
            print(f"All jobs complete. Sleeping for {sleep_time / 60:.1f} minutes until next check...")
        else:
            print(f"No progress made on incomplete jobs. Sleeping for {sleep_time / 60:.1f} minutes to avoid tight loop (exponential backoff: {current_sleep_interval / 3600:.1f}h)...")
        
        print("(Press Ctrl+C to interrupt and exit)")
        sleep_chunk = 5
        slept = 0
        while slept < sleep_time and not shutdown_requested['flag']:
            time.sleep(min(sleep_chunk, sleep_time - slept))
            slept += sleep_chunk
        
        # Exponential backoff
        if not progress_made_in_cycle and last_check_time > 0:
            new_interval = current_sleep_interval * 2
            if new_interval > 86400:  # Cap at 24 hours
                new_interval = 86400
            print(f"Exponential backoff: Next sleep interval will be {new_interval / 3600:.1f}h")
            return new_interval
        
        if shutdown_requested['flag']:
            print("\nShutdown requested during sleep, exiting...")
    
    return current_sleep_interval


def _run_processing_cycle(sheet, resume_json, company_overview_cache, shutdown_requested):
    """Run a single processing cycle."""
    from datetime import datetime
    
    progress_made_in_cycle = False
    
    # Bulk fetch missing job descriptions
    descriptions_fetched = bulk_fetch_missing_job_descriptions(sheet)
    if descriptions_fetched > 0:
        progress_made_in_cycle = True

    # Collection phase (pass existing cache to avoid rebuilding)
    collected_jobs, total_new_jobs, _ = process_collection_phase(
        sheet, resume_json, shutdown_requested, company_overview_cache
    )
    
    if total_new_jobs > 0:
        progress_made_in_cycle = True

    # Process new jobs
    if collected_jobs:
        print(f"\nProcessing {len(collected_jobs)} total new jobs collected in this cycle...")
        if process_new_jobs_pipeline(sheet, resume_json, collected_jobs, company_overview_cache):
            progress_made_in_cycle = True

    # Finalize: process leftover batches
    print("\nFinalizing processing cycle (processing leftover batches)...")
    if bulk_filter_collected_jobs(sheet, resume_json, force_process=True) > 0:
        progress_made_in_cycle = True
    
    # Final pass for all pending jobs
    print("\nFinal pass: Processing all pending jobs in the database...")
    if CHECK_SUSTAINABILITY:
        if validate_sustainability_for_unprocessed_jobs(sheet) > 0:
            progress_made_in_cycle = True
    if analyze_all_jobs(sheet, resume_json) > 0:
        progress_made_in_cycle = True
    if process_resumes_and_cover_letters(sheet, resume_json) > 0:
        progress_made_in_cycle = True

    # Cycle summary
    print(f"\nCycle summary:")
    print(f" - New jobs collected: {len(collected_jobs)}")
    if len(collected_jobs) > 0:
        print(f" - Analyzed and filtered new jobs.")

    # LinkedIn collection (if enabled)
    if process_linkedin_collection(sheet, resume_json, company_overview_cache, shutdown_requested):
        progress_made_in_cycle = True

    # Handle progress state
    if not progress_made_in_cycle:
        print(f"\nUseless cycle (no progress made).")
    
    # Final cleanup
    print("\nFinalizing processing cycle...")
    print("\nSorting database by fit score and location priority...")
    sheet.sort((get_column_index(sheet, 'Fit score enum'), 'des'),
               (get_column_index(sheet, 'Location Priority'), 'asc'))

    print(f"\nProcessing cycle completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    return progress_made_in_cycle


def main():
    """Main loop that runs continuously"""
    import utils
    import time
    from datetime import datetime
    
    # Setup and validation
    if not setup_and_validate():
        return
    
    shutdown_requested = setup_signal_handlers()
    
    from api_methods import get_resume_json
    resume_json = get_resume_json()
    
    initialize_job_preferences()
    
    user_name = get_user_name(resume_json)
    sheet = initialize_storage(user_name)

    last_check_time = 0
    progress_made_in_cycle = True  # Initialize as True to allow first run
    base_sleep_interval = 3600  # 1 hour
    current_sleep_interval = base_sleep_interval
    company_overview_cache = _build_company_overview_cache(sheet)
    dashboard_launched = {"launched": False}

    # Open dashboard as soon as there is something to see (e.g. jobs from a previous run)
    _launch_dashboard_once(sheet, dashboard_launched)

    while not shutdown_requested['flag']:
        try:
            current_time = time.time()
            time_since_last_check = current_time - last_check_time

            # Check if there are jobs with missing data
            has_incomplete_jobs = check_incomplete_jobs(sheet)

            # Check if there's nothing else to do
            nothing_else_to_do = not has_incomplete_jobs and not CRAWL_LINKEDIN and not utils.apify_state.is_available()
            if nothing_else_to_do:
                print("\n" + "!" * 60)
                print("NOTHING ELSE TO DO: Apify is unavailable, LinkedIn crawling is disabled, and no pending jobs found.")
                print("Stopping application.")
                print("!" * 60 + "\n")
                shutdown_requested['flag'] = True
                break

            # Sleep logic with exponential backoff
            current_sleep_interval = _handle_sleep_logic(
                has_incomplete_jobs, progress_made_in_cycle, last_check_time,
                current_sleep_interval, base_sleep_interval, shutdown_requested
            )
            
            if shutdown_requested['flag']:
                break
                
            if has_incomplete_jobs:
                print(f"Found jobs with missing data. Processing immediately...")

            # Open dashboard as soon as there is something to see (e.g. jobs added this run)
            _launch_dashboard_once(sheet, dashboard_launched)

            print(f"\n{'=' * 60}")
            print(f"Starting new processing cycle at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'=' * 60}\n")

            last_check_time = time.time()

            if shutdown_requested['flag']:
                print("\nShutdown requested, exiting main loop...")
                break
            
            # Run processing cycle
            progress_made_in_cycle = _run_processing_cycle(
                sheet, resume_json, company_overview_cache, shutdown_requested
            )
            
            if shutdown_requested['flag']:
                break

            # Handle progress state and reset sleep interval
            if not progress_made_in_cycle:
                print(f"\nUseless cycle (no progress made).")
            else:
                if current_sleep_interval != base_sleep_interval:
                    print(f"\nProgress made! Resetting sleep interval to {base_sleep_interval / 3600:.1f}h")
                current_sleep_interval = base_sleep_interval

        except KeyboardInterrupt:
            print("\n\nKeyboard interrupt received. Shutting down gracefully...")
            shutdown_requested['flag'] = True
            break
        except Exception as e:
            if shutdown_requested['flag']:
                print("\nShutdown requested, exiting...")
                break
            print(f"\n\nAn error occurred: {e}")
            import traceback
            traceback.print_exc()
            if shutdown_requested['flag']:
                break
            continue
    
    print("\nShutdown complete. Goodbye!")


if __name__ == "__main__":
    main()

# NOTE: Future enhancement - Once company info is collected for all jobs, consider implementing
# bulk LLM filtering similar to bulk_filter_collected_jobs() but for jobs that have company
# overviews. This would require tracking token size estimation based on character length to
# stay within API limits. Currently, individual job analysis handles this case.
