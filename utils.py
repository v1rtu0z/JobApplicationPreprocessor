import json
import os
import random
import time
import re
from pathlib import Path
from functools import wraps
from typing import Any

import google.genai as genai
import html2text
from urllib.parse import urlparse, parse_qs
from apify_client import ApifyClient

# Global variable to track last request time
last_request_time = 0


def column_index_to_letter(col_index: int) -> str:
    """
    Convert a 1-indexed column number to column letter(s).
    E.g., 1 -> 'A', 2 -> 'B', 27 -> 'AA'
    """
    result = ""
    while col_index > 0:
        col_index, remainder = divmod(col_index - 1, 26)
        result = chr(65 + remainder) + result
    return result


class ApifyStateManager:
    """Thread-safe manager for Apify availability state with automatic retry logic."""
    
    def __init__(self):
        self._available = True
        self._last_failure_time = None
        self._retry_delay = 3600  # 1 hour before retrying after failure
    
    def is_available(self) -> bool:
        """Check if Apify is currently available."""
        # If failed recently, check if enough time has passed to retry
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


# Global instance
apify_state = ApifyStateManager()

# Legacy support - treat as a simple boolean for backwards compatibility
class _ApifyAvailableProxy:
    """Proxy class to maintain backwards compatibility with direct assignment."""
    
    def __bool__(self):
        return apify_state.is_available()
    
    def __repr__(self):
        return str(apify_state.is_available())


APIFY_AVAILABLE = _ApifyAvailableProxy()


from config import _get_job_filters, _save_job_filters

def rate_limit():
    """Ensure at least 1 second has passed since last request"""
    global last_request_time
    current_time = time.time()
    time_since_last = current_time - last_request_time

    if time_since_last < 1.0:
        sleep_duration = random.uniform(0.5, 1.0)  # Random between 0.5 and 1.0
        time.sleep(sleep_duration)

    last_request_time = time.time()


def random_scroll(driver, max_scrolls=3):
    """Perform random scrolling to mimic human behavior"""
    num_scrolls = random.randint(1, max_scrolls)
    for _ in range(num_scrolls):
        scroll_amount = random.randint(200, 800)
        driver.execute_script(f"window.scrollBy(0, {scroll_amount});")
        time.sleep(random.uniform(0.3, 0.8))

    # Occasionally scroll back up
    if random.random() < 0.3:
        scroll_back = random.randint(100, 400)
        driver.execute_script(f"window.scrollBy(0, -{scroll_back});")
        time.sleep(random.uniform(0.2, 0.5))


def html_to_markdown(html_text: str) -> str:
    """Convert HTML to Markdown"""
    h = html2text.HTML2Text()
    h.ignore_links = False
    h.body_width = 0  # Don't wrap text
    return h.handle(html_text)


def parse_job_url(driver, linkedin_url: str) -> dict:
    """Parse a single job URL and return job details"""
    rate_limit()

    try:
        from linkedin_scraper import Job
        
        job_obj = Job(
            linkedin_url,
            driver=driver,
            close_on_complete=False,
            scrape=True
        )
        job_dict = job_obj.to_dict()

        job_description = job_dict.get('job_description', '').replace('About the job\n', '').replace('\nSee less',
                                                                                                     '').strip()
        return {
            'company_name': job_dict.get('company', ''),
            
            'job_title': job_dict.get('job_title', ''),
            'job_description': job_description,
            'job_url': linkedin_url,
            'location': job_dict.get('location', ''),
        }
    except Exception as e:
        print(f"Error parsing job {linkedin_url}: {e}")
        return None


# Add this method to handle pagination
def scrape_multiple_pages(driver, search_url: str, max_pages: int = 5) -> list:
    """
    Scrape jobs from multiple pages of search results.

    Args:
        driver: Selenium WebDriver
        search_url: Initial search URL
        max_pages: Maximum number of pages to scrape (default: 5)

    Returns:
        List of all job listings from all pages
    """
    all_jobs = []
    current_page = 1

    # Navigate to initial URL
    driver.get(search_url)
    time.sleep(random.uniform(2, 4))

    while current_page <= max_pages:
        print(f"  Scraping page {current_page}/{max_pages}")

        # Scrape current page
        from custom_job_search import CustomJobSearch

        job_search = CustomJobSearch(driver=driver, close_on_complete=False, scrape=False)
        page_jobs = job_search.scrape_from_url(driver.current_url)
        all_jobs.extend(page_jobs)

        print(f"  Found {len(page_jobs)} jobs on page {current_page}")

        # Try to find and click next page button
        try:
            from selenium.webdriver.common.by import By
            
            next_button = driver.find_element(
                By.CSS_SELECTOR,
                'button[aria-label="View next page"].jobs-search-pagination__button--next'
            )

            # Check if button is disabled (last page)
            if next_button.get_attribute('disabled'):
                print(f"  Reached last page at page {current_page}")
                break

            # Scroll button into view and click
            driver.execute_script("arguments[0].scrollIntoView(True);", next_button)
            time.sleep(random.uniform(0.5, 1.0))
            next_button.click()

            # Wait for next page to load with random delay
            time.sleep(random.uniform(5, 10))
            current_page += 1

        except Exception as e:
            print(f"  No more pages or error navigating: {e}")
            break

    print(f"  Total jobs collected from {current_page} pages: {len(all_jobs)}")
    return all_jobs


def scrape_search_results(driver, search_url: str) -> list:
    """Scrape all jobs from a LinkedIn search results page"""
    rate_limit()

    try:
        from custom_job_search import CustomJobSearch
        
        job_search = CustomJobSearch(driver=driver, close_on_complete=False, scrape=False)
        job_listings = job_search.scrape_from_url(search_url)
        return job_listings
    except Exception as e:
        print(f"Error scraping search results from {search_url}: {e}")
        return []


def fit_score_to_enum(fit_score: str) -> int:
    """Convert fit score text to numeric value for sorting"""
    score_map = {
        'Very good fit': 5,
        'Good fit': 4,
        'Moderate fit': 3,
        'Poor fit': 2,
        'Very poor fit': 1,
        'Questionable fit': 0
    }
    return score_map.get(fit_score, 0)


def get_user_name(resume_json) -> Any:
    user_name = resume_json.get('personal', {}).get('full_name')
    if not user_name:
        raise Exception("User name not found in resume JSON")
    return user_name


def normalize_company_name(company_name: str) -> str:
    """
    Normalize company name for case-insensitive matching and caching.
    Strips whitespace and converts to lowercase.
    
    Args:
        company_name: Company name string
        
    Returns:
        Normalized company name (lowercase, stripped)
    """
    if not company_name:
        return ''
    return company_name.strip().lower()


def get_company_overviews_bulk_via_apify(company_names: list[str]) -> dict[str, str]:
    """
    Fetch company overviews in bulk using Apify (up to 1000 companies).

    Args:
        company_names: List of company names to fetch

    Returns:
        Dict mapping company name -> company overview
    """
    if not company_names:
        return {}

    if not APIFY_AVAILABLE:
        print("Apify is currently unavailable (usage limit reached). Skipping company overview fetch.")
        return {}

    print(f"Fetching {len(company_names)} company overviews via Apify in bulk...")

    from main import APIFY_API_TOKEN
    client = ApifyClient(APIFY_API_TOKEN)

    try:
        # Prepare the input for Apify actor
        # The actor accepts an array of company profile URLs or names
        run_input = {
            "identifier": company_names,
            "maxResults": len(company_names)
        }

        # Run the actor
        run = client.actor("apimaestro/linkedin-company-detail").call(run_input=run_input)
        
        # Fetch results from the dataset
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())

        if not items:
            print(f"  No company data found on Apify")
            return {}

        # Map company names to overviews
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


SHEET_HEADER = [
    'Company Name', 'Job Title', 'Location', 'Location Priority', 'Job Description', 'Job URL', 'Company URL',
    'Company overview', 'Sustainable company', 'CO fetch attempted',
    'Fit score', 'Fit score enum', 'Bulk filtered', 'Job analysis', 'Tailored resume url', 'Tailored resume json',
    'Resume feedback',
    'Resume feedback addressed', 'Tailored cover letter (to be humanized)', 'CL feedback',
    'CL feedback addressed', 'Applied', 'Bad analysis', 'Job posting expired', 'Last expiration check'
]


def parse_location(raw_location: str) -> str:
    """
    Extract city, country from the raw location string.
    Example: "Belgrade, Serbia · Reposted 6 minutes ago..." -> "Belgrade, Serbia"
    """
    if not raw_location:
        return ''

    # Split by middle dot and take first part
    location_part = raw_location.split('·')[0].strip()
    return location_part


def get_location_priority(location: str) -> int:
    """
    Return priority score for sorting based on configuration in filters.yaml.
    """
    filters = _get_job_filters()
    location_priorities = filters.get('location_priorities', {})
    
    location_lower = location.lower()

    # Sort priorities by score to ensure we check them in order if needed, 
    # but here we just look for matches.
    for loc, priority in sorted(location_priorities.items(), key=lambda x: x[1]):
        if loc.lower() in location_lower:
            return priority
            
    # Default priority if no match found
    return max(location_priorities.values()) + 1 if location_priorities else 5


def _call_gemini_for_sustainability(prompt: str, key_name_context: str = "") -> dict | None:
    """
    Common logic for calling Gemini API with fallback for sustainability checks.
    
    Args:
        prompt: The prompt to send to Gemini
        key_name_context: Context string for logging (e.g., company name)
    
    Returns:
        Parsed JSON response dict, or None if all keys failed
    """
    api_keys = [
        ('primary', os.getenv("GEMINI_API_KEY")),
        ('backup', os.getenv("BACKUP_GEMINI_API_KEY"))
    ]

    for key_name, api_key in api_keys:
        if not api_key:
            if key_name == 'primary':
                print(f"Warning: GEMINI_API_KEY not found, trying backup...")
                continue
            else:
                print(f"Warning: Both API keys not found")
                return None

        try:
            client = genai.Client(api_key=api_key)
            
            rate_limit()
            model_name = os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')
            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )

            response_text = response.text.strip()
            cleaned = response_text.replace('```json', '').replace('```', '').strip()
            result = json.loads(cleaned)
            
            return result

        except Exception as e:
            error_msg = str(e)
            if key_name == 'primary':
                print(f"Error with {key_name} key{' for ' + key_name_context if key_name_context else ''}: {e}")
                print(f"  → Trying backup key...")
                continue
            else:
                print(f"Error with {key_name} key{' for ' + key_name_context if key_name_context else ''}: {e}")
                return None

    return None


def is_sustainable_company_bulk(companies_data: list[dict], sheet=None) -> dict[str, dict]:
    """
    Determine sustainability for multiple companies in bulk.
    
    Args:
        companies_data: List of dicts with keys 'company_name', 'company_overview', 'job_description'
        sheet: Google Sheet object (optional)
        
    Returns:
        Dict mapping company name -> {'is_sustainable': bool, 'reasoning': str}
    """
    results = {}
    
    # Build sustainability cache once for efficiency
    sustainability_cache = None
    if sheet:
        sustainability_cache = _build_sustainability_cache(sheet)
    
    # Check cache first for all companies
    remaining_companies = []
    for data in companies_data:
        name = data['company_name']
        if sheet and sustainability_cache:
            cached_result = get_sustainability_from_sheet(name, sheet, cache=sustainability_cache)
            if cached_result is not None:
                results[name] = {
                    'is_sustainable': cached_result == 'TRUE',
                    'reasoning': 'Cached from sheet'
                }
                continue
        
        if not data.get('company_overview') or len(data['company_overview']) < 50:
            results[name] = {
                'is_sustainable': None,
                'reasoning': 'Insufficient company overview'
            }
            continue
            
        remaining_companies.append(data)
        
    if not remaining_companies:
        return results

    # Load criteria from filters
    filters = _get_job_filters()
    criteria = filters.get('sustainability_criteria', {})
    positive_list = "\n".join([f"- {c}" for c in criteria.get('positive', [])])
    negative_list = "\n".join([f"- {c}" for c in criteria.get('negative', [])])

    companies_text = ""
    for i, data in enumerate(remaining_companies):
        companies_text += f"""
--- Company {i+1} ---
Name: {data['company_name']}
Overview: {data['company_overview']}
Job Description snippet: {data['job_description'][:500] if data['job_description'] else "N/A"}
"""

    prompt = f"""Analyze if these companies work on something sustainability-oriented.
{companies_text}

Criteria for Sustainability:
Return is_sustainable: true *ONLY* for companies in sustainable industries like:
{positive_list}

Return is_sustainable: false for:
{negative_list}

Return is_sustainable: false for neutral industries (banking, tech, finance, insurance, investment) UNLESS they have an explicit and primary sustainability/ESG/impact focus.

You must respond with ONLY a JSON dictionary where keys are the exact company names provided above and values are objects with "is_sustainable" (boolean) and "reasoning" (string).
Example:
{{
  "Company A": {{"is_sustainable": true, "reasoning": "Solar energy manufacturer"}},
  "Company B": {{"is_sustainable": false, "reasoning": "Defense contractor"}}
}}"""

    batch_results = _call_gemini_for_sustainability(prompt, "bulk check")
    
    if batch_results:
        for data in remaining_companies:
            name = data['company_name']
            if name in batch_results:
                res = batch_results[name]
                is_sust = res.get('is_sustainable')
                reason = res.get('reasoning', 'No reasoning provided')
                results[name] = {
                    'is_sustainable': is_sust,
                    'reasoning': reason
                }
                
                if is_sust is False:
                    print(f"  ⚠️  Bulk Sustainability check: {name} -> False")
                    print(f"      Reason: {reason}")
                else:
                    print(f"  ✓  Bulk Sustainability check: {name} -> True")
            else:
                print(f"Warning: Result for {name} missing from bulk API response")
                results[name] = {'is_sustainable': None, 'reasoning': 'Missing from API response'}
    else:
        # All API calls failed
        for data in remaining_companies:
            results[data['company_name']] = {'is_sustainable': None, 'reasoning': 'API Error'}

    return results


def is_sustainable_company(company_name: str, company_overview: str, job_description: str, sheet=None) -> bool | None:
    """
    Determine if a company is sustainable (not in weapons, fossil fuels, or harmful industries).
    Checks cache first to avoid redundant API calls.

    Args:
        company_name: Name of the company
        company_overview: Company description/overview
        job_description: Job posting description
        sheet: Google Sheet object for caching (optional)

    Returns:
        True if sustainable, False if unsustainable, None if insufficient data
    """
    # Check cache first if sheet is provided
    if sheet:
        # Build cache once (could be optimized further by passing cache from caller)
        sustainability_cache = _build_sustainability_cache(sheet)
        cached_result = get_sustainability_from_sheet(company_name, sheet, cache=sustainability_cache)
        if cached_result is not None:
            # We already have a result in the sheet, no need to print anything or call API
            return cached_result == 'TRUE'

    if not company_overview or len(company_overview) < 50:
        return None

    print(f"Checking sustainability for: {company_name}")

    # Load criteria from filters
    filters = _get_job_filters()
    criteria = filters.get('sustainability_criteria', {})
    positive_list = "\n".join([f"- {c}" for c in criteria.get('positive', [])])
    negative_list = "\n".join([f"- {c}" for c in criteria.get('negative', [])])

    prompt = f"""Analyze if this company works on something sustainability-oriented:

Company Name: {company_name}

Company Overview: {company_overview}

Job Description: {job_description[:1000] if job_description else "Not available"}

Return True *ONLY* for companies in sustainable industries like:
{positive_list}

Return False for:
{negative_list}

Return False for neutral industries (banking, tech, finance, insurance, investment) UNLESS they have explicit sustainability/ESG/impact investing focus.

You must respond with ONLY a JSON object in this exact format:
{{
  "is_sustainable": True or False,
  "reasoning": "brief explanation"
}}"""

    result = _call_gemini_for_sustainability(prompt, company_name)
    
    if result:
        is_sustainable = result.get("is_sustainable", True)
        reasoning = result.get("reasoning", "No reasoning provided")

        if not is_sustainable:
            print(f"  ⚠️  Sustainability check: {company_name} -> False")
            print(f"      Reason: {reasoning}")
        else:
            print(f"  ✓  Sustainability check: {company_name} -> True")

        return is_sustainable
    else:
        print(f"Both API keys failed for {company_name}, returning None")
        return None


def validate_sustainability_for_unprocessed_jobs(sheet):
    """
    Process sustainability checks for jobs that:
    1. Have company overview available
    2. Don't have a definitive 'Sustainable company' value yet (True/False)
    3. Haven't been filtered or applied to yet

    Updates the 'Sustainable company' field and marks unsustainable companies as 'Very poor fit'.
    Uses bulk processing for efficiency.
    """
    print("\n" + "=" * 60)
    print("SUSTAINABILITY VALIDATION: Checking unprocessed companies")
    print("=" * 60 + "\n")

    all_rows = sheet.get_all_records()
    companies_to_check = []  # List of dicts for bulk API
    companies_seen = set()  # Track unique companies in this batch collection

    # Phase 1: Collect unique companies that need checking (only from rows we might still process)
    # Only consider rows that are not applied, not expired, not bad analysis – we disregard those.
    # Also skip rows that are already processed/filtered (have a fit score), so we only check
    # companies that have at least one job still pending analysis.
    for row in all_rows:
        if row.get('Applied') == 'TRUE' or row.get('Bad analysis') == 'TRUE' or row.get('Job posting expired') == 'TRUE':
            continue

        if row.get('Fit score') in ['Poor fit', 'Very poor fit', 'Moderate fit', 'Questionable fit']:
            continue

        # Skip if already has definitive sustainable company value
        sustainable_value = str(row.get('Sustainable company', '')).strip().upper()
        if sustainable_value in ['TRUE', 'FALSE']:
            continue

        # Skip if no company overview yet
        company_overview = row.get('Company overview', '').strip()
        if not company_overview:
            continue

        company_name = row.get('Company Name', '').strip()
        if not company_name:
            continue

        # Use case-insensitive matching for company names
        company_key = normalize_company_name(company_name)
        if company_key in companies_seen:
            continue

        companies_seen.add(company_key)
        companies_to_check.append({
            'company_name': company_name,
            'company_overview': company_overview,
            'job_description': row.get('Job Description', '')
        })

    if not companies_to_check:
        print("No companies need sustainability validation.")
        return 0

    names = [c['company_name'] for c in companies_to_check]
    print(f"Found {len(companies_to_check)} companies to check for sustainability: {', '.join(names)}")

    # Phase 2: Process in batches
    # Note: This could be imported from main.py if made a shared constant
    batch_size = 10  # Number of companies to check for sustainability per batch
    total_processed = 0

    for i in range(0, len(companies_to_check), batch_size):
        batch = companies_to_check[i:i + batch_size]
        print(f"\nProcessing batch {i // batch_size + 1} ({len(batch)} companies)...")

        batch_results = is_sustainable_company_bulk(batch, sheet=sheet)

        for company_name, result in batch_results.items():
            is_sustainable = result['is_sustainable']
            reasoning = result['reasoning']

            if is_sustainable is None:
                continue

            sustainability_value = 'TRUE' if is_sustainable else 'FALSE'
            
            # Find all jobs with this company name and update them
            # Case-insensitive exact match preferred, substring match as fallback
            search_name = company_name.strip().lower()
            bulk_updates = []  # Collect updates for bulk processing
            
            for row in all_rows:
                row_company = row.get('Company Name', '').strip().lower()
                job_url = row.get('Job URL', '').strip()
                
                if not job_url:
                    continue
                
                # Prefer exact match, but allow substring match for company name variations
                if row_company == search_name:
                    match = True
                elif search_name in row_company or row_company in search_name:
                    match = True
                else:
                    match = False
                
                if match:
                    updates = {'Sustainable company': sustainability_value}

                    # If unsustainable, mark as Very poor fit
                    if not is_sustainable and not row.get('Fit score'):
                        updates.update({
                            'Fit score': 'Very poor fit',
                            'Fit score enum': str(fit_score_to_enum('Very poor fit')),
                            'Job analysis': f'Unsustainable company: {reasoning}'
                        })
                    
                    bulk_updates.append((job_url, row.get('Company Name', ''), updates))
            
            # Perform bulk update for all jobs with this company
            if bulk_updates:
                sheet.bulk_update_by_key(bulk_updates)
                total_processed += 1

    print(f"\nSustainability validation completed. Processed {total_processed} companies.")
    return total_processed


def setup_driver():
    """Initialize and return a headless Chrome driver"""
    from selenium.webdriver.chrome.options import Options
    
    options = Options()
    # options.add_argument('--headless=new')
    from selenium import webdriver
    
    return webdriver.Chrome(options=options)


def setup_database(user_name):
    """
    Set up the local SQLite database for job data.
    """
    from local_storage import JobDatabase
    db_path = Path("local_data") / "jobs.db"
    db = JobDatabase(str(db_path), SHEET_HEADER)
    print(f"Using local SQLite storage: {db_path}")
    return db


# Legacy alias for compatibility
def setup_spreadsheet(user_name):
    """Legacy alias for setup_database()."""
    return setup_database(user_name)


def get_existing_jobs(sheet):
    """Get set of existing job keys (job_title @ company_name) from spreadsheet"""
    all_rows = sheet.get_all_records()
    existing_jobs = set()
    for row in all_rows:
        job_title = row.get('Job Title', '').strip()
        company_name = row.get('Company Name', '').strip()
        if job_title and company_name:
            job_key = f"{job_title} @ {company_name}"
            existing_jobs.add(job_key)
    return existing_jobs


def parse_fit_score(job_analysis: str) -> str:
    """Extract fit score from job analysis text"""
    fit_levels = ['Very good fit', 'Good fit', 'Moderate fit', 'Poor fit', 'Very poor fit']
    for level in fit_levels:
        if level in job_analysis:
            return level
    return 'Questionable fit'


def update_cell(db, job_url: str, company_name: str, column_name: str, value: str):
    """Helper to update a job field by job URL and company name"""
    if not job_url or not company_name:
        return
    db.update_job_by_key(job_url, company_name, {column_name: value})


def get_column_index(sheet, column_name: str) -> int | Any:
    """Legacy helper for compatibility - returns column index for spreadsheet operations"""
    sheet_header = sheet.row_values(1)
    col_idx = sheet_header.index(column_name) + 1
    return col_idx


def retry_on_selenium_error(max_retries=3, delay=5):
    """Decorator to retry a function call on specific Selenium exceptions."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                from selenium.common import StaleElementReferenceException
                from httpcore import TimeoutException

                try:
                    return func(*args, **kwargs)
                except (StaleElementReferenceException, TimeoutException, TimeoutError) as e:
                    last_exception = e
                    print(
                        f"Caught {type(e).__name__}. Retrying in {delay} seconds (Attempt {attempt + 1}/{max_retries})...")
                    time.sleep(delay)
            # If all retries fail, raise the last exception
            raise RuntimeError(
                f"Function failed after {max_retries} attempts due to unrecoverable error: {type(last_exception).__name__}"
            ) from last_exception

        return wrapper

    return decorator


@retry_on_selenium_error(max_retries=3, delay=5)
def check_job_expiration(driver, job_url: str) -> bool | None:
    """
    Check if a job posting has expired by navigating to the URL
    and looking for "No longer accepting applications" text.

    Returns:
        True if job is expired, False otherwise
    """
    try:
        driver.get(job_url)
        random_scroll(driver)
        time.sleep(random.uniform(1.5, 2.5))  # Wait for page to load

        page_source = driver.page_source
        return 'No longer accepting applications' in page_source or "The job you were looking for was not found." in page_source
    except Exception as e:
        print(f"Error checking job expiration for {job_url}: {e}")
        return None


def _build_sustainability_cache(sheet):
    """
    Build a dictionary of company name -> sustainability status from existing sheet data.
    Uses case-insensitive matching and takes the first definitive value found.
    
    Returns:
        Dict mapping company_name_lower -> 'TRUE' or 'FALSE'
    """
    all_rows = sheet.get_all_records()
    cache = {}
    for row in all_rows:
        company_name = row.get('Company Name', '').strip()
        if not company_name:
            continue
        
        company_key = normalize_company_name(company_name)
        # Only add if not already in cache (first occurrence wins)
        if company_key not in cache:
            sustainable = row.get('Sustainable company', '').strip()
            if sustainable in ['TRUE', 'FALSE']:
                cache[company_key] = sustainable
    return cache

def get_sustainability_from_sheet(company_name: str, sheet, cache: dict = None) -> str | None:
    """
    Check if sustainability status is already known for a company.
    Uses cache if provided, otherwise builds one (less efficient).
    
    Args:
        company_name: Company name to look up
        sheet: Sheet object (used if cache not provided)
        cache: Pre-built cache dict (optional, for efficiency)
    
    Returns:
        'TRUE', 'FALSE', or None if not found
    """
    if cache is None:
        # Build cache on the fly (less efficient, but backward compatible)
        cache = _build_sustainability_cache(sheet)
    
    company_key = normalize_company_name(company_name)
    return cache.get(company_key)


def match_job_to_apify_result(job: dict, apify_item: dict) -> bool:
    """
    Match a job from the database to an Apify result by comparing job title and company name.
    Uses normalized company names and substring matching for titles to handle variations.
    
    Args:
        job: Dict with keys 'title' and 'company' (from database)
        apify_item: Dict with structure {'job_info': {'title': str, ...}, 'company_info': {'name': str, ...}}
    
    Returns:
        True if the job matches the Apify result, False otherwise
    """
    job_info = apify_item.get('job_info', {})
    comp_info = apify_item.get('company_info', {})
    
    # Extract and normalize job title
    item_title = job_info.get('title', '').strip().lower()
    job_title_normalized = job.get('title', '').strip().lower()
    
    # Extract and normalize company name
    item_company_normalized = normalize_company_name(comp_info.get('name', ''))
    job_company_normalized = normalize_company_name(job.get('company', ''))
    
    # Match if titles overlap (substring match) and companies match (normalized)
    # Using substring matching for titles as exact matches may fail due to variations
    title_matches = (job_title_normalized in item_title or item_title in job_title_normalized)
    company_matches = (job_company_normalized == item_company_normalized or
                     job_company_normalized in item_company_normalized or
                     item_company_normalized in job_company_normalized)
    
    return title_matches and company_matches


def fetch_job_details_bulk_via_apify(job_ids: list[str]) -> list[dict]:
    """
    Fetch job details (including full descriptions) in bulk using Apify.

    Args:
        job_ids: List of LinkedIn job IDs to fetch

    Returns:
        List of job detail objects
    """
    if not job_ids:
        return []

    if not APIFY_AVAILABLE:
        print("Apify is currently unavailable (usage limit reached). Skipping job detail fetch.")
        return []

    print(f"Fetching {len(job_ids)} job details via Apify in bulk...")

    from main import APIFY_API_TOKEN
    client = ApifyClient(APIFY_API_TOKEN)

    try:
        # Prepare the input for Apify actor
        run_input = {
            "job_id": job_ids
        }

        # Run the actor
        run = client.actor("apimaestro/linkedin-job-detail").call(run_input=run_input)
        
        # Fetch results from the dataset
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
            print("No more data can be fetched via Apify this month.")
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

    from main import APIFY_API_TOKEN
    
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
        
        # Extract keywords
        keywords = query_params.get('keywords', [''])[0]
        
        # Extract geoId (location)
        location = query_params.get('geoId', [''])[0]
        
        # Extract workplace type (f_WT)
        # LinkedIn f_WT values: 1=On-site, 2=Remote, 3=Hybrid
        # Actor remote values: onsite, remote, hybrid
        remote_map = {'1': 'onsite', '2': 'remote', '3': 'hybrid'}
        f_wt = query_params.get('f_WT', [])
        # Handle both multiple f_WT parameters and comma-separated values in one parameter
        if f_wt:
            first_wt = f_wt[0].split(',')[0]
            remote = remote_map.get(first_wt, "")
        else:
            remote = ""

        # Extract experience level (f_E)
        # LinkedIn f_E values: 1=Internship, 2=Entry level, 3=Associate, 4=Mid-Senior level, 5=Director, 6=Executive
        # Actor experienceLevel values: internship, entry, associate, mid_senior, director, executive
        exp_map = {
            '1': 'internship',
            '2': 'entry',
            '3': 'associate',
            '4': 'mid_senior',
            '5': 'director',
            '6': 'executive'
        }
        f_e = query_params.get('f_E', [])
        # Handle both multiple f_E parameters and comma-separated values in one parameter
        if f_e:
            first_e = f_e[0].split(',')[0]
            experience_level = exp_map.get(first_e, "")
        else:
            experience_level = ""

        # Extract sort order (sortBy)
        # LinkedIn sortBy values: R=Relevant, DD=Most recent
        # Actor sort values: relevant, recent
        sort_map = {'R': 'relevant', 'DD': 'recent'}
        sort_val = query_params.get('sortBy', [''])[0]
        sort = sort_map.get(sort_val, "")

        # Extract date posted (f_TPR)
        # LinkedIn f_TPR values: r604800 (week), r2592000 (month), r86400 (day)
        # Actor date_posted values: month, week, day
        date_posted_map = {
            'r2592000': 'month',
            'r604800': 'week',
            'r86400': 'day'
        }
        f_tpr = query_params.get('f_TPR', [''])[0]
        date_posted = date_posted_map.get(f_tpr, "")

        # Extract Easy Apply (f_AL)
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
    
    client = ApifyClient(APIFY_API_TOKEN)
    
    try:
        run = client.actor("apimaestro/linkedin-jobs-scraper-api").call(run_input=run_input)
        
        # Results are in results field of the output object (Key-value store)
        # However, the JS/Python examples show listing from dataset.
        # Looking at the documentation provided in the issue description:
        # "In Standby mode, an Actor provides a web server which can be used as a website, API, or an MCP server."
        # "In Batch mode, an Actor accepts a well-defined JSON input... and optionally produces a well-defined JSON output, datasets with results..."
        
        # The Python example uses client.dataset(run["defaultDatasetId"]).iterate_items()
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        
        # The actor documentation says it returns a list of results in a JSON object 
        # but the Python example iterates over dataset items. 
        # Usually dataset items are the individual results (jobs).
        
        # Based on the "Output Format" section in README:
        # { "status": "success", "jobsFound": 50, ..., "results": [ { ... }, ... ] }
        # This looks like the OUTPUT of the run (Key-value store).
        # Let's check both if possible, but usually Apify Actors push to dataset.
        
        if not items:
            # Try to get from Key-Value store "OUTPUT"
            try:
                record = client.key_value_store(run["defaultKeyValueStoreId"]).get_record("OUTPUT")
                if record and 'value' in record:
                    val = record['value']
                    if isinstance(val, dict) and 'results' in val:
                        items = val['results']
            except Exception as kv_err:
                print(f"Error fetching from KV store: {kv_err}")

        print(f"Fetched {len(items)} jobs from Apify.")
        return items
    except Exception as e:
        error_msg = str(e)
        print(f"Error running Apify Actor: {error_msg}")
        if "Monthly usage hard limit exceeded" in error_msg:
            print("\n" + "!" * 60)
            print("CRITICAL: APIFY MONTHLY USAGE HARD LIMIT REACHED.")
            print("No more jobs can be fetched via Apify this month.")
            print("Disabling Apify for the remainder of this run.")
            print("!" * 60 + "\n")
            apify_state.mark_unavailable()
        return []
