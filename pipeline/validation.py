"""Job expiration check, missing data fetch, and validation loop."""

from datetime import datetime

import utils
from utils import (
    check_job_expiration,
    get_location_priority,
    parse_location,
    retry_on_selenium_error,
    setup_driver,
)

from .constants import CRAWL_LINKEDIN, email_address, linkedin_password
from .filtering import _check_and_process_filters
from .resumes import delete_resume_local


def _check_job_expiration_with_retry(driver, job_url, email_address_val, linkedin_password_val):
    """Check job expiration with retry logic on failure."""
    from linkedin_scraper import actions

    job_expired = check_job_expiration(driver, job_url)
    if job_expired is None:
        print(f"Error checking expiration for {job_url}. Resetting the driver and trying again...")
        driver.quit()
        del driver
        driver = setup_driver()
        actions.login(driver, email_address_val, linkedin_password_val)
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
            print("  - Fetched Job Description")

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
        pass
    return False


def validate_jobs_and_fetch_missing_data(driver, sheet):
    """Validate non-applied good-fit jobs (expiration, filters), fetch missing JD/location. Returns count."""
    if not CRAWL_LINKEDIN:
        return 0

    from linkedin_scraper import actions

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

        if row.get('Applied') == 'TRUE' or row.get('Bad analysis') == 'TRUE' or row.get('Job posting expired') == 'TRUE':
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
