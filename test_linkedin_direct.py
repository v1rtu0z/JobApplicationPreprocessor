#!/usr/bin/env python3
"""
Test script to validate LinkedIn company overview extraction with real data.
Tests the first 5 companies from the database that need overview data.
Checks DB cache first to avoid unnecessary crawling.
"""

import re
import time
import random
import sys
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from local_storage import JobDatabase
from utils import SHEET_HEADER

# Delay settings (seconds)
MIN_DELAY_BETWEEN_COMPANIES = 12
MAX_DELAY_BETWEEN_COMPANIES = 20
PAGE_LOAD_WAIT = 5

# Use fresh driver for each company to avoid session tracking
USE_FRESH_DRIVER_PER_COMPANY = True


def setup_driver(headless=False):
    """Set up Chrome driver with anti-detection."""
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
    
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
        'source': '''
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            })
        '''
    })
    
    return driver


def company_name_to_slug(company_name: str) -> str:
    """Convert company name to LinkedIn URL slug."""
    slug = company_name.lower()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'\s+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    slug = slug.strip('-')
    return slug


def normalize_company_name(name: str) -> str:
    """Normalize company name for case-insensitive matching."""
    return name.strip().lower() if name else ''


def build_overview_cache(db: JobDatabase) -> dict:
    """
    Build a cache of company name -> overview from existing database entries.
    This avoids crawling for companies we already have data for.
    """
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


def extract_overview(driver) -> str | None:
    """
    Extract company overview using the best selector found.
    Priority:
    1. p[data-test-id="about-us__description"] - most specific
    2. JSON-LD @graph description
    3. Meta description (fallback, less complete)
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
        import json
        scripts = driver.find_elements(By.CSS_SELECTOR, 'script[type="application/ld+json"]')
        for script in scripts:
            try:
                data = json.loads(script.get_attribute('innerHTML'))
                # Navigate to @graph[*].description
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

    # Method 3: Meta description (fallback - truncated but better than nothing)
    try:
        meta = driver.find_element(By.CSS_SELECTOR, 'meta[name="description"]')
        content = meta.get_attribute('content')
        if content:
            # Remove LinkedIn prefix like "Company | X followers on LinkedIn. Tagline. |"
            parts = content.split('|')
            if len(parts) >= 3:
                desc = parts[2].strip()
                if len(desc) > 50:
                    return desc
            elif len(content) > 50:
                return content
    except Exception:
        pass

    return None


def get_companies_needing_overview(db: JobDatabase, overview_cache: dict, limit: int = 5) -> list[str]:
    """Get unique company names that need overview data (not in cache)."""
    all_rows = db.get_all_records()
    
    # Fit scores we care about
    good_fit_scores = {'Very good fit', 'Good fit', 'Moderate fit', ''}
    
    seen_companies = set()
    companies = []
    
    for row in all_rows:
        company_name = row.get('Company Name', '').strip()
        if not company_name:
            continue
        
        company_key = normalize_company_name(company_name)
        
        # Skip if already in our results
        if company_key in seen_companies:
            continue
        
        # Skip if we already have overview in cache (from other jobs)
        if company_key in overview_cache:
            continue
        
        # Missing company overview on this row
        if row.get('Company overview', '').strip():
            continue
        
        # Not already attempted
        if row.get('CO fetch attempted', '').strip() == 'TRUE':
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
        
        seen_companies.add(company_key)
        companies.append(company_name)
        
        if len(companies) >= limit:
            break
    
    return companies


def human_like_delay(min_sec: float, max_sec: float):
    """Sleep for a random duration to mimic human behavior."""
    delay = random.uniform(min_sec, max_sec)
    print(f"  [Waiting {delay:.1f} seconds...]")
    time.sleep(delay)


def test_company(company_name: str, driver) -> dict:
    """Test fetching overview for a single company."""
    result = {
        'company': company_name,
        'slug': company_name_to_slug(company_name),
        'url': None,
        'status': 'unknown',
        'overview': None,
        'error': None
    }
    
    slug = result['slug']
    url = f"https://www.linkedin.com/company/{slug}"
    result['url'] = url
    
    try:
        print(f"\n  Fetching: {url}")
        driver.get(url)
        
        # Wait for page to load
        time.sleep(PAGE_LOAD_WAIT)
        
        final_url = driver.current_url
        title = driver.title
        
        print(f"  Page title: {title}")
        print(f"  Final URL: {final_url}")
        
        # Check for login redirect
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
            result['error'] = f'Redirected to: {final_url}'
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


def main():
    print("="*70)
    print("LINKEDIN OVERVIEW EXTRACTION TEST (with DB cache check)")
    print("="*70)
    
    # Load database
    db_path = Path("local_data") / "jobs.db"
    if not db_path.exists():
        print(f"Database not found at {db_path}")
        return
    
    db = JobDatabase(str(db_path), SHEET_HEADER)
    
    # Build overview cache from existing data
    print("\nBuilding overview cache from existing database entries...")
    overview_cache = build_overview_cache(db)
    print(f"Found {len(overview_cache)} companies with existing overviews in database.")
    
    # Get companies to test (excluding those in cache)
    print("\nFetching first 5 companies that need overview data (not in cache)...")
    companies = get_companies_needing_overview(db, overview_cache, limit=5)
    
    if not companies:
        print("No companies found that need overview data.")
        return
    
    print(f"\nWill test these {len(companies)} companies:")
    for i, company in enumerate(companies, 1):
        print(f"  {i}. {company}")
    
    print(f"\nSettings:")
    print(f"  - Delay between companies: {MIN_DELAY_BETWEEN_COMPANIES}-{MAX_DELAY_BETWEEN_COMPANIES} seconds")
    print(f"  - Page load wait: {PAGE_LOAD_WAIT} seconds")
    print(f"  - Manual verification pause after each company")
    
    print("\nPress Enter to start...")
    input()
    
    results = []
    driver = None
    
    try:
        for i, company in enumerate(companies, 1):
            print(f"\n{'='*70}")
            print(f"[{i}/{len(companies)}] Testing: {company}")
            print("="*70)
            
            # Create fresh driver for each company to avoid session tracking
            if USE_FRESH_DRIVER_PER_COMPANY:
                if driver:
                    print("  [Closing previous browser...]")
                    driver.quit()
                    driver = None
                print("  [Starting fresh browser...]")
                driver = setup_driver(headless=False)
                time.sleep(2)  # Let browser fully initialize
            elif driver is None:
                driver = setup_driver(headless=False)
            
            result = test_company(company, driver)
            results.append(result)
            
            print(f"\n  Status: {result['status']}")
            if result['error']:
                print(f"  Error: {result['error']}")
            
            if result['overview']:
                print(f"\n  EXTRACTED OVERVIEW ({len(result['overview'])} chars):")
                print("  " + "-"*60)
                # Print with word wrapping
                words = result['overview'].split()
                line = "  "
                for word in words:
                    if len(line) + len(word) + 1 > 80:
                        print(line)
                        line = "  " + word
                    else:
                        line += " " + word if line != "  " else word
                if line.strip():
                    print(line)
                print("  " + "-"*60)
            
            # PAUSE for user verification
            print("\n  >>> Please verify this result in the browser.")
            print("  >>> Press Enter to continue to next company...")
            input()
            
            # Delay before next company (except for last one)
            if i < len(companies):
                human_like_delay(MIN_DELAY_BETWEEN_COMPANIES, MAX_DELAY_BETWEEN_COMPANIES)
        
        # Summary
        print("\n" + "="*70)
        print("FINAL SUMMARY")
        print("="*70)
        
        for i, result in enumerate(results, 1):
            status_icon = {
                'success': '✓',
                'auth_wall': '🔒',
                'not_found': '✗',
                'no_overview': '?',
                'error': '!',
                'redirected': '→'
            }.get(result['status'], '?')
            
            overview_info = f" ({len(result['overview'])} chars)" if result['overview'] else ""
            print(f"  {status_icon} {result['company']}: {result['status']}{overview_info}")
        
        print("\n" + "-"*70)
        successes = sum(1 for r in results if r['status'] == 'success')
        auth_walls = sum(1 for r in results if r['status'] == 'auth_wall')
        print(f"Success: {successes}/{len(results)}")
        print(f"Auth walls: {auth_walls}/{len(results)}")
        print("-"*70)
        
        print("\nDo all the extracted overviews look correct? (yes/no): ", end="")
        response = input().strip().lower()
        
        if response in ('yes', 'y'):
            print("\nGreat! Ready to update the main script with this approach.")
        else:
            print("\nPlease describe what's wrong so I can adjust.")
        
    finally:
        if driver:
            print("\nClosing browser...")
            driver.quit()


if __name__ == "__main__":
    main()
