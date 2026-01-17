from datetime import datetime

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from api_methods import *
from utils import *
from utils import retry_on_selenium_error

load_dotenv()

APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN")
email_address = os.getenv("EMAIL_ADDRESS")
linkedin_password = os.getenv("LINKEDIN_PASSWORD")
CHECK_SUSTAINABILITY = os.getenv("CHECK_SUSTAINABILITY", "false").lower() == "true"
CRAWL_LINKEDIN = os.getenv("CRAWL_LINKEDIN", "false").lower() == "true"
USE_LOCAL_STORAGE = os.getenv("USE_LOCAL_STORAGE", "false").lower() == "true"


# --- Helper Methods for Refactoring (Implementations are placeholders) ---

def _get_job_filters():
    """Returns the job filtering keywords."""
    return {
        'job_title_skip_keywords': [
            'azure', 'java', 'react', 'fullstack', 'full stack', 'full-stack', 'frontend', 'front end', 'front-end',
            'customer support', 'recruiter', 'flutter', 'go', '.net', 'writer', 'ios', 'android', 'mobile',
            'mobile app', 'manager', 'wordpress', 'payroll', 'account executive', 'sales', 'sales manager',
            'c#', 'vue.js', 'node.js', 'dot net', 'accountant', 'web design', 'web3'
        ],
        'job_title_skip_keywords_2': [
            'sap'
        ],
        'company_skip_keywords': ['deel', 'allcore s.p.A.'],
        'location_skip_keywords': [
            'czechia', 'poland', 'hungary', 'romania', 'slovakia', 'malta', 'lithuania', 'latvia', 'belgium'
        ]
    }


def _check_and_process_filters(job_title, company_name, raw_location, company_overview='', job_description='',
                               sheet=None):
    from linkedin_scraper import Job
    """Checks job details against skip keywords and prepares analysis data."""
    filters = _get_job_filters()

    should_skip_location = any(keyword in raw_location.lower() for keyword in filters['location_skip_keywords'])
    should_skip_title = any(keyword in job_title.lower() for keyword in filters['job_title_skip_keywords'])
    should_skip_title_2 = any(
        keyword in job_title.lower().split(' ') for keyword in filters['job_title_skip_keywords_2'])
    should_skip_company = any(keyword in company_name.lower() for keyword in filters['company_skip_keywords'])

    if should_skip_title or should_skip_title_2 or should_skip_company or should_skip_location:
        fit_score = 'Poor fit'
        fit_score_enum = fit_score_to_enum(fit_score)
        analysis_reason = (
            'Job title contains unwanted technology' if should_skip_title
            else 'Location not preferred' if should_skip_location
            else 'Company name contains unwanted keyword'
        )
        print(f"Skipping job due to filter: {job_title} @ {company_name}. Reason: {analysis_reason}")
        return fit_score, fit_score_enum, analysis_reason, '', 'TRUE'  # Added bulk filtered flag

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
        return fit_score, fit_score_enum, analysis_reason, '', 'TRUE'  # Added bulk filtered flag

    return '', '', '', None, 'FALSE'  # Added bulk filtered flag


def _normalize_job_title(job_title):
    """Cleans up the job title."""
    lines = job_title.split('\n')
    if len(lines) == 1:
        return job_title.strip()

    # Check if lines are near-duplicates
    first_line = lines[0]
    is_duplicate = (len(set(lines)) == 1 or first_line in lines[1] or lines[1] in first_line)

    return first_line if is_duplicate else job_title.strip()


def _build_company_overview_cache(sheet):
    """Build a dictionary of company name -> company overview from existing sheet data"""
    all_rows = sheet.get_all_records()
    cache = {}
    for row in all_rows:
        company_name = row.get('Company Name', '').strip()
        company_overview = row.get('Company overview', '').strip()
        if company_name and company_overview and company_name not in cache:
            cache[company_name] = company_overview
    return cache


def collect_and_filter_jobs(driver, sheet):
    from linkedin_scraper import Job
    """
    Collect all jobs from search URLs, apply keyword filters, and add basic info to sheet.
    Returns list of job URLs that need detailed scraping.
    """
    print("\n" + "=" * 60)
    print("COLLECTION PHASE: Gathering all jobs from search URLs")
    print("=" * 60 + "\n")

    existing_jobs = get_existing_jobs(sheet)
    filters = _get_job_filters()
    new_rows = []
    jobs_to_scrape = []  # List of (job_url, row_index) tuples

    for search_url in SEARCH_URLS:
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

                # Apply keyword filters (title and company only, skip location for now)
                should_skip_title = any(keyword in job_title.lower() for keyword in filters['job_title_skip_keywords'])
                should_skip_title_2 = any(
                    keyword in job_title.lower().split(' ') for keyword in filters['job_title_skip_keywords_2'])
                should_skip_company = any(
                    keyword in company_name.lower() for keyword in filters['company_skip_keywords'])

                if should_skip_title or should_skip_title_2 or should_skip_company:
                    print(f"Skipping job due to title/company filter: {job_title} @ {company_name}")
                    continue

                # Check for duplicates and reprocessing logic
                job_key = f"{job_title} @ {company_name}"

                if job_key in existing_jobs:
                    # print(f"Skipping duplicate: {job_key}")
                    continue

                # Get basic location info (might be incomplete from search results)
                raw_location = getattr(job_obj, 'location', '')
                clean_location = parse_location(raw_location) if raw_location else ''
                location_priority = get_location_priority(clean_location)

                # Add basic job info to sheet (no description or company overview yet)
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

                print(f"Collected job for detailed scraping: {job_key}")

            except Exception as e:
                print(f"Unexpected error collecting job: {getattr(job_obj, 'linkedin_url', 'Unknown URL')}. Error: {e}")
                continue

    if new_rows:
        print(f"Appending {len(new_rows)} new jobs to sheet...")
        # Get the row index of the first newly added job
        all_rows_count = len(sheet.get_all_records())
        start_row_idx = all_rows_count + 2  # +1 for header, +1 for first new row

        sheet.append_rows(new_rows)
        
        # Build jobs_to_scrape list with correct row indices
        for i, row in enumerate(new_rows):
            job_url = row[5] # Job URL is at index 5
            jobs_to_scrape.append((job_url, start_row_idx + i))
        
        print(f"Successfully added {len(new_rows)} jobs.")
    else:
        print("No new jobs found via LinkedIn crawl.")

    print(f"\nCollection phase completed. Added {len(new_rows)} new jobs. Total jobs to scrape: {len(jobs_to_scrape)}")
    return jobs_to_scrape


def bulk_filter_collected_jobs(sheet, resume_json):
    """
    Apply bulk LLM filtering to jobs that passed keyword filters.
    Groups jobs in batches and marks poor fits.
    Only processes jobs that haven't been bulk filtered yet.
    """
    print("\n" + "=" * 60)
    print("BULK FILTERING: Using LLM to filter collected jobs")
    print("=" * 60 + "\n")

    all_rows = sheet.get_all_records()

    # Collect jobs that need bulk filtering
    jobs_to_filter = []
    jobs_to_mark_filtered = []  # Jobs that just need 'Bulk filtered' = TRUE

    for idx, row in enumerate(all_rows, start=2):
        # Skip if already bulk filtered
        if row.get('Bulk filtered') == 'TRUE':
            continue

        # Only filter jobs without a fit score
        if row.get('Fit score'):
            # Mark as bulk filtered even though it already has a score
            # (probably filtered by keywords during collection)
            jobs_to_mark_filtered.append(idx)
            continue

        # Skip if expired, applied, or bad analysis
        if (row.get('Applied') == 'TRUE' or
                row.get('Bad analysis') == 'TRUE' or
                row.get('Job posting expired') == 'TRUE'):
            jobs_to_mark_filtered.append(idx)
            continue

        job_title = row.get('Job Title', '').strip()
        if job_title:
            jobs_to_filter.append({
                'title': job_title,
                'row_idx': idx,
                'company': row.get('Company Name', '')
            })

    # Batch update jobs that just need 'Bulk filtered' = TRUE
    if jobs_to_mark_filtered:
        print(f"Marking {len(jobs_to_mark_filtered)} already-processed jobs as bulk filtered...")
        bulk_filtered_col_letter = gspread.utils.rowcol_to_a1(1, get_column_index(sheet, 'Bulk filtered'))[0]

        updates = []
        for row_idx in jobs_to_mark_filtered:
            updates.append({
                'range': f'{bulk_filtered_col_letter}{row_idx}',
                'values': [['TRUE']]
            })

        # Update in chunks of 100 to avoid hitting limits
        chunk_size = 100
        for i in range(0, len(updates), chunk_size):
            chunk = updates[i:i + chunk_size]
            sheet.batch_update(chunk, value_input_option='USER_ENTERED')
            time.sleep(1)  # Rate limiting

    if not jobs_to_filter:
        print("No jobs to bulk filter")
        return 0

    print(f"Found {len(jobs_to_filter)} jobs to bulk filter")

    batch_size = 100
    total_filtered = 0

    for i in range(0, len(jobs_to_filter), batch_size):
        batch = jobs_to_filter[i:i + batch_size]
        batch_titles = [job['title'] for job in batch]

        print(f"\nProcessing batch {i // batch_size + 1} ({len(batch)} jobs)...")

        try:
            from api_methods import bulk_filter_jobs
            filtered_titles = bulk_filter_jobs(batch_titles, resume_json, max_retries=3)

            # Get column letters once
            bulk_filtered_col = gspread.utils.rowcol_to_a1(1, get_column_index(sheet, 'Bulk filtered'))[0]
            fit_score_col = gspread.utils.rowcol_to_a1(1, get_column_index(sheet, 'Fit score'))[0]
            fit_score_enum_col = gspread.utils.rowcol_to_a1(1, get_column_index(sheet, 'Fit score enum'))[0]
            job_analysis_col = gspread.utils.rowcol_to_a1(1, get_column_index(sheet, 'Job analysis'))[0]

            # Prepare bulk updates
            bulk_updates = []
            filtered_set = set(filtered_titles)

            for job in batch:
                row_idx = job['row_idx']

                # Always mark as bulk filtered
                bulk_updates.append({
                    'range': f'{bulk_filtered_col}{row_idx}',
                    'values': [['TRUE']]
                })

                # Add additional updates if job was filtered
                if job['title'] in filtered_set:
                    bulk_updates.extend([
                        {
                            'range': f'{fit_score_col}{row_idx}',
                            'values': [['Very poor fit']]
                        },
                        {
                            'range': f'{fit_score_enum_col}{row_idx}',
                            'values': [[fit_score_to_enum('Very poor fit')]]
                        },
                        {
                            'range': f'{job_analysis_col}{row_idx}',
                            'values': [['Filtered by bulk analysis - wrong tech/role/domain']]
                        }
                    ])
                    print(f"  Filtered: {job['title']} @ {job['company']}")
                    total_filtered += 1

            # Execute bulk update in one call
            if bulk_updates:
                sheet.batch_update(bulk_updates, value_input_option='USER_ENTERED')

            # Delay between batches 
            if i + batch_size < len(jobs_to_filter):
                time.sleep(random.uniform(2, 4))

        except Exception as e:
            print(f"Error in bulk filtering batch: {e}")
            print("Marking batch as checked and continuing with next batch...")

            # Mark the batch as checked even on error - single batch update
            error_updates = []
            bulk_filtered_col = gspread.utils.rowcol_to_a1(1, get_column_index(sheet, 'Bulk filtered'))[0]
            for job in batch:
                error_updates.append({
                    'range': f'{bulk_filtered_col}{job["row_idx"]}',
                    'values': [['TRUE']]
                })

            if error_updates:
                try:
                    sheet.batch_update(error_updates, value_input_option='USER_ENTERED')
                except Exception as update_error:
                    print(f"Failed to mark batch as filtered: {update_error}")

            continue

    print(f"\nBulk filtering completed. Filtered {total_filtered}/{len(jobs_to_filter)} jobs")
    return total_filtered


def fetch_company_overviews(sheet, company_overview_cache):
    """
    Fetch company overviews for jobs that are missing them.
    Only processes jobs that don't have Poor/Very poor fit scores.
    Uses bulk Apify fetching for efficiency.
    """
    print("\n" + "=" * 60)
    print("COMPANY OVERVIEW PHASE: Fetching missing company overviews")
    print("=" * 60 + "\n")

    all_rows = sheet.get_all_records()

    # Collect companies that need fetching
    companies_to_fetch = []
    row_indices = {}  # Map company name -> list of row indices

    for idx, row in enumerate(all_rows, start=2):
        # Skip if already has company overview
        if row.get('Company overview'):
            continue

        if row.get('Fit score'):
            continue

        if row.get('Applied') == 'TRUE' or row.get('Bad analysis') == 'TRUE' or row.get(
                'Job posting expired') == 'TRUE':
            continue

        company_name = row.get('Company Name', '').strip()
        if not company_name:
            continue

        # Check cache first
        if company_name in company_overview_cache:
            update_cell(sheet, idx, 'Company overview', company_overview_cache[company_name])
            continue

        # Track this company for bulk fetching
        if company_name not in row_indices:
            companies_to_fetch.append(company_name)
            row_indices[company_name] = []
        row_indices[company_name].append(idx)

    if not companies_to_fetch:
        print("No companies need overview fetching")
        return 0

    print(f"Found {len(companies_to_fetch)} unique companies to fetch")

    # Fetch in bulk (up to 1000 at a time)
    fetched_count = 0
    batch_size = 1000

    for i in range(0, len(companies_to_fetch), batch_size):
        batch = companies_to_fetch[i:i + batch_size]
        print(f"\nFetching batch of {len(batch)} companies...")

        # Get overviews via Apify
        overview_map = get_company_overviews_bulk_via_apify(batch)

        # TODO: Apify sometimes returns empty overviews for some companies, 
        #  add a fallback linkedin crawling step in case the sheet is empty 
        #  and searches don't return anything new and useful

        # Update cache and sheet
        bulk_updates = []
        co_col_letter = gspread.utils.rowcol_to_a1(1, get_column_index(sheet, 'Company overview'))[0]

        for company_name, overview in overview_map.items():
            company_overview_cache[company_name] = overview

            # Add all updates for this company to bulk updates
            if company_name in row_indices:
                for row_idx in row_indices[company_name]: 
                    bulk_updates.append({
                        'range': f'{co_col_letter}{row_idx}',
                        'values': [[overview]]
                    })
                    fetched_count += 1
            else:
                print(f"Warning: Company {company_name} returned from Apify but not found in tracking map")

        # Execute bulk update in chunks to avoid limits
        if bulk_updates:
            chunk_size = 100
            for i in range(0, len(bulk_updates), chunk_size):
                chunk = bulk_updates[i:i + chunk_size]
                sheet.batch_update(chunk, value_input_option='USER_ENTERED')
                time.sleep(1)  # Rate limiting between chunks

        # Rate limiting between batches
        if i + batch_size < len(companies_to_fetch):
            time.sleep(random.uniform(2, 4))

    print(f"\nCompany overview fetching completed. Fetched {fetched_count} overviews.")
    return fetched_count



def upload_to_gdrive(file_path: str, filename: str) -> str:
    """
    Upload a file to Google Drive's Resumes directory and return its shareable URL.
    If USE_LOCAL_STORAGE is enabled, saves to local directory instead.
    """
    if USE_LOCAL_STORAGE:
        from local_storage import save_resume_local
        # Read the file and save locally
        with open(file_path, 'rb') as f:
            pdf_bytes = f.read()
        local_path = save_resume_local(pdf_bytes, filename)
        return local_path
    
    # Google Drive upload (existing behavior)
    creds = get_google_creds()
    service = build('drive', 'v3', credentials=creds)

    # Find or create Resumes folder
    folder_name = 'Resumes'
    query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    folders = results.get('files', [])

    if not folders:
        # Create Resumes folder if it doesn't exist
        folder_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        folder = service.files().create(body=folder_metadata, fields='id').execute()
        folder_id = folder.get('id')
    else:
        folder_id = folders[0]['id']

    # Check if file already exists in the Resumes folder
    query = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    existing_files = results.get('files', [])

    file_metadata = {
        'name': filename,
        'parents': [folder_id]
    }
    media = MediaFileUpload(file_path, mimetype='application/pdf')

    if existing_files:
        # Update existing file
        file_id = existing_files[0]['id']
        service.files().update(
            fileId=file_id,
            media_body=media
        ).execute()
    else:
        # Create new file
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()
        file_id = file.get('id')

    # Make the file shareable
    service.permissions().create(
        fileId=file_id,
        body={'type': 'anyone', 'role': 'reader'}
    ).execute()

    # Get shareable link
    shareable_link = f"https://drive.google.com/file/d/{file_id}/view"

    return shareable_link


def delete_resume_from_gdrive(resume_url: str):
    """
    Delete a resume from Google Drive and local Downloads.
    If USE_LOCAL_STORAGE is enabled, deletes from local directory instead.
    """
    if not resume_url:
        return

    if USE_LOCAL_STORAGE:
        from local_storage import delete_resume_local
        delete_resume_local(resume_url)
        return

    # Google Drive deletion (existing behavior)
    try:
        creds = get_google_creds()
        service = build('drive', 'v3', credentials=creds)

        # Extract file ID from URL
        file_id = resume_url.split('/')[-2]

        # Check if file exists in Google Drive
        try:
            file_metadata = service.files().get(fileId=file_id, fields='name,trashed').execute()
            filename = file_metadata['name']
            is_trashed = file_metadata.get('trashed', False)

            # Only delete if file exists and is not already trashed
            if not is_trashed:
                service.files().delete(fileId=file_id).execute()

        except Exception as e:
            # File doesn't exist or we don't have access
            if 'File not found' in str(e) or '404' in str(e):
                return
            else:
                raise e

        # Remove from Downloads if exists  
        local_path = os.path.expanduser(f"~/Downloads/{filename}")
        if os.path.exists(local_path):
            os.remove(local_path)

    except Exception as e:
        print(f"Error removing resume files: {e}")


def validate_jobs_and_fetch_missing_data(driver, sheet):
    from linkedin_scraper import Job
    """
    Validate non-applied good-fit jobs (check expiration, apply filters).
    Also fetches missing Job Descriptions, Locations, and stores Company URLs.
    Marks expired jobs and deletes their resumes.
    """
    if not CRAWL_LINKEDIN:
        return 0
    print("\n" + "=" * 60)
    print("JOB VALIDATION: Checking expirations and fetching missing data")
    print("=" * 60 + "\n")

    all_rows = sheet.get_all_records()
    expired_count = 0
    fetched_count = 0
    not_logged_in = False

    for idx, row in enumerate(all_rows, start=2):  # start=2 because row 1 is headers
        if not row.get('Job Title'):
            break

        fit_score = row.get('Fit score')

        # Only check jobs without fit score or good fit jobs
        if fit_score and fit_score not in ['Good fit', 'Very good fit']:
            continue

        if row.get('Applied') == 'TRUE' or row.get('Bad analysis') == 'TRUE' or row.get(
                'Job posting expired') == 'TRUE':
            continue

        job_url = row.get('Job URL')
        if not job_url:
            continue

        # Check if we need to fetch anything
        needs_jd = not row.get('Job Description')
        needs_location = not row.get('Location')

        last_checked = row.get('Last expiration check')
        if last_checked:
            try:
                last_checked_time = datetime.fromisoformat(last_checked)
                if (datetime.now() - last_checked_time).total_seconds() < 3600 and not (
                        needs_jd or needs_location
                ):
                    print(
                        f"Skipping expiration check (checked {int((datetime.now() - last_checked_time).total_seconds() / 60)} minutes ago): {row.get('Job Title')} @ {row.get('Company Name')}")
                    continue
            except (ValueError, TypeError):
                pass  # Invalid timestamp, proceed with check

        if CRAWL_LINKEDIN and not_logged_in:
            from linkedin_scraper import actions
            
            actions.login(driver, email_address, linkedin_password)
            not_logged_in = False

        print(f"Checking expiration for: {row.get('Job Title')} @ {row.get('Company Name')}")

        job_expired = False
        if CRAWL_LINKEDIN:
            job_expired = check_job_expiration(driver, job_url)
            if job_expired is None:
                from linkedin_scraper import actions

                print(f"Error checking expiration for {job_url}. Resetting the driver and trying again...")
                driver.quit()
                del driver
                driver = setup_driver()
                actions.login(driver, email_address, linkedin_password)
                not_logged_in = False
                job_expired = check_job_expiration(driver, job_url)

        if job_expired:
            print(f"Job has expired: {row.get('Job Title')} @ {row.get('Company Name')}")
            update_cell(sheet, idx, 'Job posting expired', 'TRUE')

            # Delete the resume if it exists
            resume_url = row.get('Tailored resume url')
            if resume_url:
                delete_resume_from_gdrive(resume_url)

            expired_count += 1
        else:
            # Double-check filters for non-expired jobs
            job_title = row.get('Job Title')
            company_name = row.get('Company Name')
            raw_location = row.get('Location', '')

            fit_score_result, fit_score_enum, analysis_reason, _, bulk_filtered = _check_and_process_filters(
                job_title, company_name, raw_location, sheet=sheet
            )

            if fit_score_result:  # Job should be filtered
                update_cell(sheet, idx, 'Fit score', fit_score_result)
                update_cell(sheet, idx, 'Fit score enum', fit_score_enum)
                update_cell(sheet, idx, 'Job analysis', analysis_reason)
                update_cell(sheet, idx, 'Bulk filtered', bulk_filtered)
                print(f"  - Filtered job: {analysis_reason}")

            update_cell(sheet, idx, 'Last expiration check', datetime.now().isoformat())

        if needs_jd or needs_location:
            # Fetch missing data
            print(f"Fetching missing data for: {row.get('Job Title')} @ {row.get('Company Name')}")

            try:
                job_obj = Job(job_url, driver=driver, close_on_complete=False, scrape=False)

                @retry_on_selenium_error(max_retries=3, delay=5)
                def scrape_with_retry(job_obj):
                    job_obj.scrape(close_on_complete=False)
                    return job_obj.to_dict()

                job_dict = scrape_with_retry(job_obj)

                # Fetch Job Description if missing
                if needs_jd:
                    job_description = (
                        job_dict.get('job_description', '')
                        .replace('About the job\n', '')
                        .replace('\nSee less', '')
                        .strip()
                    )
                    update_cell(sheet, idx, 'Job Description', job_description)
                    print(f"  - Fetched Job Description")

                # Fetch Location if missing
                if needs_location:
                    raw_location = job_dict.get('location', '')
                    clean_location = parse_location(raw_location)
                    location_priority = get_location_priority(clean_location)
                    update_cell(sheet, idx, 'Location', clean_location)
                    update_cell(sheet, idx, 'Location Priority', location_priority)
                    print(f"  - Fetched Location: {clean_location}")

                fetched_count += 1

            except Exception as e:
                print(f"Error fetching data for {job_url}: {e}")
                continue

    print(f"\nExpiration check completed. Found {expired_count} expired jobs. Fetched data for {fetched_count} jobs.")
    return expired_count


def analyze_single_job(sheet, row, idx, resume_json) -> str | None:
    """
    Analyze a single job and update the spreadsheet.
    Returns the fit score if analysis was performed, None if skipped.
    Note: Jobs filtered during scraping will already have a fit score.
    """
    if row.get('Fit score'):
        return row.get('Fit score')

    print(f"Analyzing: {row.get('Job Title')} @ {row.get('Company Name')}")

    job_details = {
        'company_name': row.get('Company Name', ''),
        'job_title': row.get('Job Title', ''),
        'job_description': row.get('Job Description', ''),
        'location': row.get('Location', ''),
        'company_overview': row.get('Company overview', ''),
    }

    # Perform job analysis via API
    try:
        job_analysis = get_job_analysis(resume_json, job_details)
        fit_score = parse_fit_score(job_analysis)

        update_cell(sheet, idx, 'Fit score', fit_score)
        update_cell(sheet, idx, 'Fit score enum', fit_score_to_enum(fit_score))
        update_cell(sheet, idx, 'Job analysis', html_to_markdown(job_analysis))

        # Immediately process Very good fit jobs
        if fit_score == 'Very good fit':
            print(f"Very good fit detected! Immediately processing resume and cover letter...")
            try:
                process_cover_letter(sheet, row, idx, resume_json)
                process_resume(sheet, row, idx, resume_json)
            except Exception as e:
                print(f"Error immediately processing Very good fit job: {e}")

        print(f"Added analysis for: {row.get('Job Title')} @ {row.get('Company Name')}")
        return fit_score

    except Exception as e:
        error_message = str(e)
        if '429' in error_message or 'Rate limit' in error_message:
            # Log and continue for rate limit errors
            print(
                f"Rate limit hit for job analysis: {row.get('Job Title')} @ {row.get('Company Name')}. Skipping for now.")
            return None


def analyze_all_jobs(sheet, resume_json):
    """
    First loop: Analyze all jobs that don't have a fit score yet.
    Returns the number of jobs analyzed.
    """
    print("\n" + "=" * 60)
    print("ANALYSIS LOOP: Analyzing all unprocessed jobs")
    print("=" * 60 + "\n")

    all_rows = sheet.get_all_records()
    analyzed_count = 0
    consecutive_analysis_failure_count = 0

    for idx, row in enumerate(all_rows, start=2):  # start=2 because row 1 is headers
        if not row.get('Job Title'):
            break

        # we skip jobs that are expired, filtered, or already analyzed
        # If sustainability check is disabled, we don't skip based on the 'Sustainable company' column
        if row.get('Job posting expired') == 'TRUE' or not row.get('Job Description') or not row.get('Company overview'):
            continue
            
        if CHECK_SUSTAINABILITY and not row.get('Sustainable company'):
            continue

        fit_score = analyze_single_job(sheet, row, idx, resume_json)
        if fit_score:
            analyzed_count += 1
            consecutive_analysis_failure_count = 0
        else:
            consecutive_analysis_failure_count += 1
            if consecutive_analysis_failure_count >= 5:
                print(
                    f"Skipping further analysis due to {consecutive_analysis_failure_count} consecutive analysis failures.")
                break

    print(f"\nAnalysis loop completed. Analyzed {analyzed_count} jobs.")
    return analyzed_count


def process_cover_letter(sheet, row, idx, resume_json):
    """Process cover letter generation/regeneration for a row"""
    job_details = {
        'company_name': row.get('Company Name', ''),
        'job_title': row.get('Job Title', ''),
        'job_description': row.get('Job Description', ''),
        'location': row.get('Location', ''),
    }

    # Handle feedback-based regeneration
    if row.get('CL feedback') and row.get('CL feedback addressed') != 'TRUE':
        print(f"Regenerating cover letter with feedback for: {row.get('Job Title')} @ {row.get('Company Name')}")
        try:
            current_cl = row.get('Tailored cover letter (to be humanized)', '')
            feedback = row.get('CL feedback')

            tailored_cl = get_tailored_cl(resume_json, job_details, current_cl, feedback)
            
            # Store full text in sheet (same for both modes)
            update_cell(sheet, idx, 'Tailored cover letter (to be humanized)', tailored_cl)
            
            # Also save cover letter locally if USE_LOCAL_STORAGE is enabled
            if USE_LOCAL_STORAGE:
                from local_storage import save_cover_letter_local, get_local_file_path
                from utils import get_user_name
                user_name = get_user_name(resume_json).replace(' ', '_')
                company_name = job_details['company_name'].replace(' ', '_')
                filename = get_local_file_path(user_name, company_name, 'cover_letter')
                save_cover_letter_local(tailored_cl, filename)
            
            update_cell(sheet, idx, 'CL feedback addressed', 'TRUE')
            print(f"Regenerated cover letter for: {row.get('Job Title')}")
        except Exception as e:
            print(f"Error regenerating cover letter: {e}")
        return

    # Generate initial cover letter
    if not row.get('Tailored cover letter (to be humanized)'):
        print(f"Generating cover letter for: {row.get('Job Title')} @ {row.get('Company Name')}")
        try:
            tailored_cl = get_tailored_cl(resume_json, job_details)
            
            # Store full text in sheet (same for both modes)
            update_cell(sheet, idx, 'Tailored cover letter (to be humanized)', tailored_cl)
            
            # Also save cover letter locally if USE_LOCAL_STORAGE is enabled
            if USE_LOCAL_STORAGE:
                from local_storage import save_cover_letter_local, get_local_file_path
                from utils import get_user_name
                user_name = get_user_name(resume_json).replace(' ', '_')
                company_name = job_details['company_name'].replace(' ', '_')
                filename = get_local_file_path(user_name, company_name, 'cover_letter')
                save_cover_letter_local(tailored_cl, filename)
            
            print(f"Generated cover letter for: {row.get('Job Title')}")
        except Exception as e:
            print(f"Error generating cover letter: {e}")


def process_resume(sheet, row, idx, resume_json):
    """Process resume generation/regeneration for a row"""
    job_details = {
        'company_name': row.get('Company Name', ''),
        'job_title': row.get('Job Title', ''),
        'job_description': row.get('Job Description', ''),
        'location': row.get('Location', ''),
    }

    # Handle feedback-based regeneration
    if row.get('Resume feedback') and row.get('Resume feedback addressed') != 'TRUE':
        print(f"Regenerating resume with feedback for: {row.get('Job Title')} @ {row.get('Company Name')}")
        try:
            current_resume_json = row.get('Tailored resume json', '')
            feedback = row.get('Resume feedback')

            tailored_json_str, filename, pdf_bytes = get_tailored_resume(
                resume_json,
                job_details,
                current_resume_json,
                feedback
            )

            local_path = save_resume_to_downloads(pdf_bytes, filename)
            gdrive_url = upload_to_gdrive(local_path, filename)
            os.remove(local_path)

            update_cell(sheet, idx, 'Tailored resume url', gdrive_url)
            update_cell(sheet, idx, 'Tailored resume json', tailored_json_str)
            update_cell(sheet, idx, 'Resume feedback addressed', 'TRUE')

            print(f"Regenerated resume for: {row.get('Job Title')}")
        except Exception as e:
            print(f"Error regenerating resume: {e}")
        return

    # Generate initial resume
    if not row.get('Tailored resume url'):
        print(f"Generating tailored resume for: {row.get('Job Title')} @ {row.get('Company Name')}")
        try:
            tailored_json_str, filename, pdf_bytes = get_tailored_resume(resume_json, job_details)

            local_path = save_resume_to_downloads(pdf_bytes, filename)
            gdrive_url = upload_to_gdrive(local_path, filename)
            os.remove(local_path)

            update_cell(sheet, idx, 'Tailored resume url', gdrive_url)
            update_cell(sheet, idx, 'Tailored resume json', tailored_json_str)

            print(f"Generated tailored resume for: {row.get('Job Title')}")
        except Exception as e:
            print(f"Error generating tailored resume: {e}")


def process_resumes_and_cover_letters(sheet, resume_json):
    """
    Second loop: Process resumes and cover letters for good fit jobs.
    Processes jobs in sorted order (by fit score and location priority).
    """
    print("\n" + "=" * 60)
    print("PROCESSING LOOP: Generating resumes and cover letters")
    print("=" * 60 + "\n")

    all_rows = sheet.get_all_records()
    processed_count = 0

    for idx, row in enumerate(all_rows, start=2):  # start=2 because row 1 is headers
        if not row.get('Job Title'):
            break

        fit_score = row.get('Fit score')

        # Skip if not a good fit
        if fit_score not in ['Good fit', 'Very good fit']:
            continue

        # Clean up if already applied, bad analysis, or expired
        if row.get('Applied') == 'TRUE' or row.get('Bad analysis') == 'TRUE' or row.get(
                'Job posting expired') == 'TRUE':
            resume_url = row.get('Tailored resume url')
            if resume_url:
                delete_resume_from_gdrive(resume_url)
                update_cell(sheet, idx, 'Tailored resume url', '')
                update_cell(sheet, idx, 'Tailored resume json', '')
            continue

        # Process cover letter
        process_cover_letter(sheet, row, idx, resume_json)

        # Process resume
        process_resume(sheet, row, idx, resume_json)

        processed_count += 1

    print(f"\nProcessing loop completed. Processed {processed_count} jobs.")
    return processed_count


def collect_jobs_via_apify(sheet):
    """
    Collect jobs using Apify Actor, apply keyword filters, and add basic info to sheet.
    """
    print("\n" + "=" * 60)
    print("COLLECTION PHASE (Apify): Gathering jobs from LinkedIn via Apify")
    print("=" * 60 + "\n")

    existing_jobs = get_existing_jobs(sheet)
    filters = _get_job_filters()
    new_rows = []

    for search_url in SEARCH_URLS:
        print(f"Fetching jobs for search URL via Apify: {search_url}")
        job_items = fetch_jobs_via_apify(search_url)

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

                # Apply keyword filters
                should_skip_title = any(keyword in job_title.lower() for keyword in filters['job_title_skip_keywords'])
                should_skip_title_2 = any(
                    keyword in job_title.lower().split(' ') for keyword in filters['job_title_skip_keywords_2'])
                should_skip_company = any(
                    keyword in company_name.lower() for keyword in filters['company_skip_keywords'])

                if should_skip_title or should_skip_title_2 or should_skip_company:
                    print(f"Skipping job due to title/company filter: {job_title} @ {company_name}")
                    continue

                # Check for duplicates
                job_key = f"{job_title} @ {company_name}"
                if job_key in existing_jobs:
                    # print(f"Skipping duplicate: {job_key}")
                    continue

                clean_location = parse_location(raw_location) if raw_location else ''
                location_priority = get_location_priority(clean_location)

                # Add basic job info to sheet
                row_data = [
                    company_name,  # Company Name
                    job_title,  # Job Title
                    clean_location,  # Location
                    location_priority,  # Location Priority
                    '',  # Job Description (empty - marker for needing scraping)
                    job_url,  # Job URL
                    '',  # Company url
                    '',  # Company overview
                    '',  # Sustainable company
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

                print(f"Collected job via Apify: {job_key}")

            except Exception as e:
                print(f"Unexpected error processing Apify job item: {item}. Error: {e}")
                continue

    if new_rows:
        print(f"Appending {len(new_rows)} new jobs to sheet...")
        sheet.append_rows(new_rows)
        print(f"Successfully added {len(new_rows)} jobs.")
    else:
        print("No new jobs found via Apify.")

    return len(new_rows)


def main():
    """Main loop that runs continuously"""
    import signal
    
    # Set up signal handler for graceful shutdown
    shutdown_requested = False
    
    def signal_handler(signum, frame):
        nonlocal shutdown_requested
        print("\n\nShutdown signal received. Finishing current operation and exiting...")
        shutdown_requested = True
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    if hasattr(signal, 'SIGBREAK'):
        signal.signal(signal.SIGBREAK, signal_handler)
    
    from api_methods import get_resume_json
    resume_json = get_resume_json()

    user_name = get_user_name(resume_json)
    
    # Initialize storage based on USE_LOCAL_STORAGE flag
    if USE_LOCAL_STORAGE:
        print("Using local storage mode (CSV files)")
        from local_storage import ensure_local_directories
        ensure_local_directories()  # Ensure directories exist
        client = None  # Not needed for local storage
    else:
        print("Using Google API mode (Google Sheets/Drive)")
        client = get_google_client()
    
    sheet = setup_spreadsheet(client, user_name)

    last_check_time = 0

    while not shutdown_requested:
        try:
            current_time = time.time()
            time_since_last_check = current_time - last_check_time

            # Check if there are jobs with missing data
            all_rows = sheet.get_all_records()
            has_incomplete_jobs = any(
                row.get('Job Title') and
                not row.get('Fit score') in ['Poor fit', 'Very poor fit', ''] and
                (
                    (not row.get('Job Description') and CRAWL_LINKEDIN) or 
                    not row.get('Company overview')
                )
                for row in all_rows
            )

            # Only do long sleep if all jobs are complete
            if not has_incomplete_jobs and time_since_last_check < 3600:  # 3600 seconds = 1 hour
                sleep_time = 3600 - time_since_last_check
                print(f"All jobs complete. Sleeping for {sleep_time / 60:.1f} minutes until next check...")
                print("(Press Ctrl+C to interrupt and exit)")
                # Sleep in smaller chunks to allow interrupt
                sleep_chunk = 5  # Sleep in 5-second chunks
                slept = 0
                while slept < sleep_time and not shutdown_requested:
                    time.sleep(min(sleep_chunk, sleep_time - slept))
                    slept += sleep_chunk
                if shutdown_requested:
                    break
            elif has_incomplete_jobs:
                print(f"Found jobs with missing data. Processing immediately...")

            print(f"\n{'=' * 60}")
            print(f"Starting new processing cycle at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'=' * 60}\n")

            last_check_time = time.time()

            # Check for shutdown request before starting processing
            if shutdown_requested:
                break
            
            # 1. Collect new jobs (Apify + LinkedIn)
            collect_jobs_via_apify(sheet)

            if shutdown_requested:
                break

            if CRAWL_LINKEDIN:
                from linkedin_scraper import actions
                
                driver = setup_driver()
                actions.login(driver, email_address, linkedin_password)
                
                # Check for expired job postings
                print("\nChecking for expired job postings...")
                validate_jobs_and_fetch_missing_data(driver, sheet)

                # Collect and filter jobs from search URLs
                print("Collecting jobs from LinkedIn search results...")
                collect_and_filter_jobs(driver, sheet)

            # 2. Bulk filter collected jobs (LLM)
            print("\nApplying bulk LLM filtering...")
            bulk_filter_collected_jobs(sheet, resume_json)

            # 3. Enrich job data (Company overviews)
            print("\nScraping detailed job information...")
            company_overview_cache = _build_company_overview_cache(sheet)
            fetch_company_overviews(sheet, company_overview_cache)

            # 4. Validate sustainability
            if CHECK_SUSTAINABILITY:
                print("\nValidating sustainability for companies...")
                validate_sustainability_for_unprocessed_jobs(sheet)
            else:
                print("\nSustainability check is disabled. Skipping...")

            # 5. Single job analysis (LLM Fit Scoring)
            print("\nAnalyzing all unprocessed jobs...")
            analyze_all_jobs(sheet, resume_json)

            print("\nSorting sheet by fit score and location priority...")
            sheet.sort((get_column_index(sheet, 'Fit score enum'), 'des'),
                       (get_column_index(sheet, 'Location Priority'), 'asc'))

            # 6. Process resumes and cover letters for good fit jobs
            print("\nProcessing resumes and cover letters...")
            process_resumes_and_cover_letters(sheet, resume_json)

            print(f"\nProcessing cycle completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

            # driver.quit()
        except KeyboardInterrupt:
            print("\n\nKeyboard interrupt received. Shutting down gracefully...")
            shutdown_requested = True
            break  # Exit the while loop
        except Exception as e:
            if shutdown_requested:
                break
            print(f"\n\nAn error occurred: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    print("\nShutdown complete. Goodbye!")


if __name__ == "__main__":
    main()

# TODO: Once company info is collected for the rest, do a similar bulk filtering for them 
#  (keeping track of the token size estimated by the character length)
