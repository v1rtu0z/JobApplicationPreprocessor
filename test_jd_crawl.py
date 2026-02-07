#!/usr/bin/env python3
"""
Test script for crawling LinkedIn job descriptions.
Uses fresh browser sessions for each job to avoid detection.

Tests with 5 random jobs, asks for confirmation, and saves to DB if confirmed.
"""

import json
import random
import sys
import time
from pathlib import Path
from typing import Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from local_storage import JobDatabase
from utils import SHEET_HEADER

# ============================================================================
# Configuration
# ============================================================================

# Database path and schema
DB_PATH = Path("local_data") / "jobs.db"

# Delay settings (seconds)
MIN_DELAY_BETWEEN_JOBS = 5
MAX_DELAY_BETWEEN_JOBS = 10
PAGE_LOAD_WAIT = 4

# ============================================================================
# Browser Setup
# ============================================================================

def setup_driver(headless: bool = False):
    """Set up Chrome driver with anti-detection measures."""
    options = Options()
    if headless:
        options.add_argument('--headless=new')
    
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--no-sandbox')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    # Randomize window size slightly
    width = random.randint(1350, 1450)
    height = random.randint(850, 950)
    
    driver = webdriver.Chrome(options=options)
    driver.set_window_size(width, height)
    
    # Make navigator.webdriver undefined
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
        'source': '''
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            })
        '''
    })
    
    return driver


# ============================================================================
# Job Description Extraction
# ============================================================================

# Selectors to try for job description, in order of preference
JD_SELECTORS = [
    # Public job view selectors
    ('div.show-more-less-html__markup', 'show-more-less-html__markup'),
    ('div[componentkey^="JobDetails_AboutTheJob"]', 'JobDetails_AboutTheJob'),
    ('section[data-job-id] div.show-more-less-html__markup', 'data-job-id section'),
    ('div.description__text', 'description__text'),
    ('section.description div.core-section-container__content', 'core-section-container__content'),
    # Authenticated view selectors
    ('div.jobs-description__content', 'jobs-description__content'),
    ('article.jobs-description', 'jobs-description'),
    # Generic fallbacks
    ('div[class*="description"] p', 'description paragraph'),
]

# Indicators that a job is expired/closed
EXPIRED_INDICATORS = [
    'no longer accepting applications',
    'job is no longer available',
    'this job has expired',
    'position has been filled',
    'job has been closed',
    'application deadline has passed',
    'no longer active',
]


def extract_job_description(driver) -> tuple[Optional[str], Optional[str]]:
    """
    Extract job description from LinkedIn job page.
    Returns (description, selector_used) tuple.
    """
    for selector, selector_name in JD_SELECTORS:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for el in elements:
                text = el.text.strip()
                # Filter out too short or non-descriptive content
                if text and len(text) > 200:
                    return text, selector_name
        except Exception:
            continue
    
    return None, None


def check_if_expired(driver) -> tuple[bool, Optional[str]]:
    """
    Check if job page indicates the job is expired/closed.
    Returns (is_expired, reason) tuple.
    """
    try:
        page_text = driver.find_element(By.TAG_NAME, 'body').text.lower()
        for indicator in EXPIRED_INDICATORS:
            if indicator in page_text:
                return True, indicator
    except Exception:
        pass
    
    # Check for specific expired job elements
    expired_selectors = [
        'div[class*="closed"]',
        'div[class*="expired"]',
        'span[class*="closed"]',
        'div.job-expired',
    ]
    
    for selector in expired_selectors:
        try:
            el = driver.find_element(By.CSS_SELECTOR, selector)
            if el.is_displayed():
                return True, f"Found element: {selector}"
        except Exception:
            continue
    
    return False, None


def fetch_job_details(job_url: str, headless: bool = False) -> dict:
    """
    Fetch job description for a single job using a fresh browser session.
    
    Returns dict with keys: status, description, selector_used, is_expired, expired_reason, error
    """
    result = {
        'status': 'unknown',
        'description': None,
        'selector_used': None,
        'is_expired': False,
        'expired_reason': None,
        'error': None
    }
    
    driver = None
    try:
        driver = setup_driver(headless=headless)
        time.sleep(1)  # Let browser initialize
        
        driver.get(job_url)
        time.sleep(PAGE_LOAD_WAIT)
        
        final_url = driver.current_url
        title = driver.title
        
        # Check for auth wall
        if 'login' in final_url or 'authwall' in final_url:
            result['status'] = 'auth_wall'
            result['error'] = 'Redirected to login'
            return result
        
        # Check for 404
        if 'page not found' in title.lower() or '/404' in final_url:
            result['status'] = 'not_found'
            result['is_expired'] = True
            result['expired_reason'] = '404 page'
            return result
        
        # Check if expired
        is_expired, expired_reason = check_if_expired(driver)
        if is_expired:
            result['is_expired'] = True
            result['expired_reason'] = expired_reason
        
        # Extract job description
        description, selector_used = extract_job_description(driver)
        if description:
            result['status'] = 'success'
            result['description'] = description
            result['selector_used'] = selector_used
        else:
            result['status'] = 'no_description'
            result['error'] = 'Page loaded but no job description found (selector issue)'
            # Don't assume expired - could just be a selector issue
        
        return result
        
    except Exception as e:
        result['status'] = 'error'
        result['error'] = str(e)
        return result
        
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


# ============================================================================
# Job Selection
# ============================================================================

def get_jobs_needing_description(db: JobDatabase, limit: int = 5) -> list[dict]:
    """
    Get random jobs that need description data.
    Uses same filtering as dashboard default view.
    """
    all_rows = db.get_all_records()
    
    # Fit scores we care about (including empty = not yet analyzed)
    good_fit_scores = {'Very good fit', 'Good fit', 'Moderate fit', ''}
    
    candidates = []
    
    for row in all_rows:
        # Missing job description
        if row.get('Job Description', '').strip():
            continue
        
        # Must have job URL
        job_url = row.get('Job URL', '').strip()
        if not job_url:
            continue
        
        # Fit score filter
        fit_score = row.get('Fit score', '').strip()
        if fit_score not in good_fit_scores:
            continue
        
        # Skip applied/expired/bad/unsustainable
        if row.get('Applied', '').strip() == 'TRUE':
            continue
        if row.get('Job posting expired', '').strip() == 'TRUE':
            continue
        if row.get('Bad analysis', '').strip() == 'TRUE':
            continue
        if row.get('Sustainable company', '').strip() == 'FALSE':
            continue
        
        candidates.append(row)
    
    # Shuffle and return limited number
    random.shuffle(candidates)
    return candidates[:limit]


# ============================================================================
# Interactive Test
# ============================================================================

def run_interactive_test():
    """Run interactive test with 5 jobs."""
    print("\n" + "=" * 70)
    print("JOB DESCRIPTION CRAWL TEST")
    print("=" * 70)
    
    if not DB_PATH.exists():
        print(f"\nError: Database not found at {DB_PATH}")
        return
    
    db = JobDatabase(str(DB_PATH), SHEET_HEADER)
    
    # Get test jobs
    jobs = get_jobs_needing_description(db, limit=5)
    
    if not jobs:
        print("\nNo jobs found needing descriptions!")
        return
    
    print(f"\nFound {len(jobs)} jobs to test.\n")
    
    for i, job in enumerate(jobs, 1):
        job_url = job.get('Job URL', '')
        company_name = job.get('Company Name', '')
        job_title = job.get('Job Title', '')
        
        print("\n" + "-" * 70)
        print(f"[{i}/{len(jobs)}] {job_title} @ {company_name}")
        print(f"URL: {job_url}")
        print("-" * 70)
        
        # Fetch job details
        print("\nFetching job page...")
        result = fetch_job_details(job_url, headless=False)
        
        print(f"\nStatus: {result['status']}")
        
        if result['error']:
            print(f"Error: {result['error']}")
        
        if result['is_expired']:
            print(f"⚠️  EXPIRED: {result['expired_reason']}")
            
            # Auto-save expired status
            db.update_job_by_key(job_url, company_name, {
                'Job posting expired': 'TRUE'
            })
            print("✓ Automatically marked as expired in database.")
        
        elif result['description']:
            print(f"Selector used: {result['selector_used']}")
            print(f"Description length: {len(result['description'])} chars")
            print("\n--- DESCRIPTION PREVIEW (first 500 chars) ---")
            print(result['description'][:500])
            if len(result['description']) > 500:
                print("... [truncated]")
            print("--- END PREVIEW ---")
            
            # Ask for confirmation
            confirm = input("\nSave this job description to database? (y/n): ").strip().lower()
            if confirm == 'y':
                db.update_job_by_key(job_url, company_name, {
                    'Job Description': result['description']
                })
                print("✓ Saved to database.")
            else:
                print("Skipped.")
        
        elif result['status'] == 'no_description':
            print("No description found (selector issue - NOT marking as expired).")
            print("You may want to check the page manually or add better selectors.")
        
        else:
            print(f"Unknown status: {result['status']}")
            print("You may want to check the page manually.")
        
        # Delay before next job (unless last one)
        if i < len(jobs):
            delay = random.uniform(MIN_DELAY_BETWEEN_JOBS, MAX_DELAY_BETWEEN_JOBS)
            print(f"\nWaiting {delay:.1f}s before next job...")
            time.sleep(delay)
    
    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    run_interactive_test()
