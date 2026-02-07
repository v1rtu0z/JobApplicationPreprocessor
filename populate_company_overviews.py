#!/usr/bin/env python3
"""
Populate missing company overviews by crawling LinkedIn company pages.
Uses fresh browser sessions for each company to avoid detection.

Usage:
    python populate_company_overviews.py              # Run on all companies
    python populate_company_overviews.py --dry-run    # Show what would be fetched
    python populate_company_overviews.py --limit 10   # Limit to N companies
    python populate_company_overviews.py --headless   # Run in headless mode
    python populate_company_overviews.py --retry-failed  # Retry previously failed companies
"""

import argparse
import json
import random
import re
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

# Delay settings (seconds)
MIN_DELAY_BETWEEN_COMPANIES = 12
MAX_DELAY_BETWEEN_COMPANIES = 20
PAGE_LOAD_WAIT = 5

# Consecutive auth wall threshold before long pause
AUTH_WALL_PAUSE_THRESHOLD = 3
AUTH_WALL_LONG_PAUSE_MINUTES = 5


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
# Helper Functions
# ============================================================================

def normalize_company_name(name: str) -> str:
    """Normalize company name for case-insensitive matching."""
    return name.strip().lower() if name else ''


def company_name_to_slug(company_name: str) -> str:
    """Convert company name to LinkedIn URL slug."""
    slug = company_name.lower()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'\s+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    slug = slug.strip('-')
    return slug


def random_delay(min_sec: float, max_sec: float):
    """Sleep for a random duration."""
    delay = random.uniform(min_sec, max_sec)
    time.sleep(delay)
    return delay


# ============================================================================
# Overview Extraction
# ============================================================================

def extract_overview(driver) -> Optional[str]:
    """
    Extract company overview from LinkedIn page.
    Uses multiple methods in order of reliability.
    """
    # Method 1: Direct selector for about-us description (BEST)
    try:
        el = driver.find_element(By.CSS_SELECTOR, 'p[data-test-id="about-us__description"]')
        text = el.text.strip()
        if text and len(text) > 50:
            return text
    except Exception:
        pass

    # Method 2: JSON-LD structured data
    try:
        scripts = driver.find_elements(By.CSS_SELECTOR, 'script[type="application/ld+json"]')
        for script in scripts:
            try:
                data = json.loads(script.get_attribute('innerHTML'))
                if '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and 'description' in item:
                            desc = item['description']
                            if desc and len(desc) > 100:
                                return desc
            except Exception:
                continue
    except Exception:
        pass

    # Method 3: Meta description (fallback - may be truncated)
    try:
        meta = driver.find_element(By.CSS_SELECTOR, 'meta[name="description"]')
        content = meta.get_attribute('content')
        if content:
            parts = content.split('|')
            if len(parts) >= 3:
                desc = parts[2].strip()
                if len(desc) > 50:
                    return desc
    except Exception:
        pass

    return None


def fetch_company_overview(company_name: str, headless: bool = False) -> dict:
    """
    Fetch overview for a single company using a fresh browser session.
    
    Returns dict with keys: status, overview, error
    """
    result = {
        'status': 'unknown',
        'overview': None,
        'error': None
    }
    
    slug = company_name_to_slug(company_name)
    url = f"https://www.linkedin.com/company/{slug}"
    
    driver = None
    try:
        driver = setup_driver(headless=headless)
        time.sleep(1)  # Let browser initialize
        
        driver.get(url)
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
            return result
        
        # Check if we're on a company page
        if '/company/' not in final_url:
            result['status'] = 'redirected'
            result['error'] = f'Unexpected redirect: {final_url}'
            return result
        
        # Extract overview
        overview = extract_overview(driver)
        if overview:
            result['status'] = 'success'
            result['overview'] = overview
        else:
            result['status'] = 'no_overview'
            result['error'] = 'Page loaded but no overview found'
        
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
# Database Operations
# ============================================================================

def build_overview_cache(db: JobDatabase) -> dict:
    """Build cache of company name -> overview from existing database entries."""
    cache = {}
    all_rows = db.get_all_records()
    
    for row in all_rows:
        company_name = row.get('Company Name', '').strip()
        overview = row.get('Company overview', '').strip()
        
        if company_name and overview:
            key = normalize_company_name(company_name)
            if key not in cache:
                cache[key] = overview
    
    return cache


def get_companies_needing_overview(db: JobDatabase, overview_cache: dict, retry_failed: bool = False) -> list[tuple[str, list[dict]]]:
    """
    Get companies that need overview data.
    Returns list of (company_name, [jobs]) tuples.
    
    Args:
        db: Database instance
        overview_cache: Cache of existing overviews
        retry_failed: If True, include companies where fetch was attempted but no overview found
    """
    all_rows = db.get_all_records()
    
    # Fit scores we care about
    good_fit_scores = {'Very good fit', 'Good fit', 'Moderate fit', ''}
    
    company_jobs = {}  # normalized_name -> {'display_name': str, 'jobs': []}
    
    for row in all_rows:
        company_name = row.get('Company Name', '').strip()
        if not company_name:
            continue
        
        company_key = normalize_company_name(company_name)
        
        # Skip if we already have overview in cache
        if company_key in overview_cache:
            continue
        
        # Missing company overview on this row
        if row.get('Company overview', '').strip():
            continue
        
        # Check if already attempted
        already_attempted = row.get('CO fetch attempted', '').strip() == 'TRUE'
        if already_attempted and not retry_failed:
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
        
        # Add to company jobs
        if company_key not in company_jobs:
            company_jobs[company_key] = {
                'display_name': company_name,
                'jobs': []
            }
        company_jobs[company_key]['jobs'].append(row)
    
    return [(data['display_name'], data['jobs']) for data in company_jobs.values()]


def update_company_overview(db: JobDatabase, jobs: list[dict], overview: str):
    """Update company overview for all jobs of a company."""
    updates = []
    for job in jobs:
        job_url = job.get('Job URL', '').strip()
        company_name = job.get('Company Name', '').strip()
        if job_url and company_name:
            updates.append((job_url, company_name, {
                'Company overview': overview,
                'CO fetch attempted': 'TRUE'
            }))
    
    if updates:
        db.bulk_update_by_key(updates)


def mark_fetch_attempted(db: JobDatabase, jobs: list[dict]):
    """Mark company overview fetch as attempted (even if no data found)."""
    updates = []
    for job in jobs:
        job_url = job.get('Job URL', '').strip()
        company_name = job.get('Company Name', '').strip()
        if job_url and company_name:
            updates.append((job_url, company_name, {
                'CO fetch attempted': 'TRUE'
            }))
    
    if updates:
        db.bulk_update_by_key(updates)


# ============================================================================
# Main Migration Logic
# ============================================================================

def run_migration(
    dry_run: bool = False,
    limit: Optional[int] = None,
    headless: bool = False,
    retry_failed: bool = False
):
    """Run the company overview migration."""
    print("=" * 70)
    print("COMPANY OVERVIEW MIGRATION" + (" (RETRY FAILED)" if retry_failed else ""))
    print("=" * 70)
    
    # Load database
    db_path = Path("local_data") / "jobs.db"
    if not db_path.exists():
        print(f"Error: Database not found at {db_path}")
        return
    
    db = JobDatabase(str(db_path), SHEET_HEADER)
    
    # Build overview cache from existing data
    print("\nBuilding overview cache from existing database entries...")
    overview_cache = build_overview_cache(db)
    print(f"Found {len(overview_cache)} companies with existing overviews.")
    
    # Get companies needing overview
    print(f"\nFinding companies that need overview data{' (including previously attempted)' if retry_failed else ''}...")
    companies = get_companies_needing_overview(db, overview_cache, retry_failed=retry_failed)
    
    if not companies:
        print("No companies found that need overview data.")
        return
    
    total_jobs = sum(len(jobs) for _, jobs in companies)
    print(f"Found {len(companies)} companies ({total_jobs} jobs) needing overview data.")
    
    if limit:
        companies = companies[:limit]
        print(f"Limiting to first {limit} companies.")
    
    if dry_run:
        print("\n[DRY RUN] Would fetch overviews for:")
        for i, (company_name, jobs) in enumerate(companies[:20], 1):
            print(f"  {i}. {company_name} ({len(jobs)} jobs)")
        if len(companies) > 20:
            print(f"  ... and {len(companies) - 20} more")
        return
    
    print(f"\nSettings:")
    print(f"  - Delay between companies: {MIN_DELAY_BETWEEN_COMPANIES}-{MAX_DELAY_BETWEEN_COMPANIES} seconds")
    print(f"  - Fresh browser per company: Yes")
    print(f"  - Headless mode: {headless}")
    print()
    
    # Stats
    stats = {
        'processed': 0,
        'success': 0,
        'no_overview': 0,
        'auth_wall': 0,
        'not_found': 0,
        'error': 0,
        'jobs_updated': 0,
    }
    
    consecutive_auth_walls = 0
    
    try:
        for i, (company_name, jobs) in enumerate(companies, 1):
            print(f"[{i}/{len(companies)}] {company_name} ({len(jobs)} jobs)")
            
            # Fetch overview
            result = fetch_company_overview(company_name, headless=headless)
            
            status_icon = {
                'success': '✓',
                'auth_wall': '🔒',
                'not_found': '✗',
                'no_overview': '?',
                'error': '!',
            }.get(result['status'], '?')
            
            print(f"  {status_icon} Status: {result['status']}", end='')
            
            if result['overview']:
                print(f" ({len(result['overview'])} chars)")
                # Update database
                update_company_overview(db, jobs, result['overview'])
                # Also update cache for future lookups in same run
                overview_cache[normalize_company_name(company_name)] = result['overview']
                stats['success'] += 1
                stats['jobs_updated'] += len(jobs)
                consecutive_auth_walls = 0
            else:
                if result['error']:
                    print(f" - {result['error']}")
                else:
                    print()
                # Mark as attempted
                mark_fetch_attempted(db, jobs)
                stats[result['status']] = stats.get(result['status'], 0) + 1
                
                # Track consecutive auth walls
                if result['status'] == 'auth_wall':
                    consecutive_auth_walls += 1
                    if consecutive_auth_walls >= AUTH_WALL_PAUSE_THRESHOLD:
                        pause_minutes = AUTH_WALL_LONG_PAUSE_MINUTES + random.randint(0, 2)
                        print(f"\n  [!] {consecutive_auth_walls} consecutive auth walls. Pausing {pause_minutes} minutes...")
                        time.sleep(pause_minutes * 60)
                        consecutive_auth_walls = 0
                else:
                    consecutive_auth_walls = 0
            
            stats['processed'] += 1
            
            # Delay before next company
            if i < len(companies):
                delay = random_delay(MIN_DELAY_BETWEEN_COMPANIES, MAX_DELAY_BETWEEN_COMPANIES)
                # Show progress every 10 companies
                if i % 10 == 0:
                    print(f"\n  --- Progress: {i}/{len(companies)} ({stats['success']} successful) ---\n")
    
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
    
    # Summary
    print("\n" + "=" * 70)
    print("MIGRATION SUMMARY")
    print("=" * 70)
    print(f"Companies processed: {stats['processed']}/{len(companies)}")
    print(f"Successful fetches: {stats['success']}")
    print(f"Jobs updated: {stats['jobs_updated']}")
    print(f"No overview found: {stats.get('no_overview', 0)}")
    print(f"Not found (404): {stats.get('not_found', 0)}")
    print(f"Auth walls: {stats.get('auth_wall', 0)}")
    print(f"Errors: {stats.get('error', 0)}")
    print("=" * 70)


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Populate missing company overviews from LinkedIn."
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help="Show what would be fetched without making changes"
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help="Maximum number of companies to process"
    )
    parser.add_argument(
        '--headless',
        action='store_true',
        help="Run browser in headless mode"
    )
    parser.add_argument(
        '--retry-failed',
        action='store_true',
        help="Retry companies where fetch was attempted but no overview found"
    )
    
    args = parser.parse_args()
    
    run_migration(
        dry_run=args.dry_run,
        limit=args.limit,
        headless=args.headless,
        retry_failed=args.retry_failed
    )


if __name__ == "__main__":
    main()
