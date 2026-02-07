#!/usr/bin/env python3
"""
Test script for crawling LinkedIn company overviews (CO) in non-headless mode.

By default uses a list of known-good companies (Figma, Google, etc.) so you can
verify extraction works. Pass company names to test specific ones, or --db to
use companies from the DB that are missing CO.

  python test_co_crawl.py                    # default list (Figma, Google, ...)
  python test_co_crawl.py Figma Google       # test these companies
  python test_co_crawl.py --db               # use DB companies missing CO (limit 6)
  python test_co_crawl.py --db 3             # use DB, first 3 companies
  python test_co_crawl.py --no-pause         # no pause between companies
"""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from local_storage import JobDatabase
from utils import SHEET_HEADER
from utils.parsing import normalize_company_name
from utils.linkedin_crawl import fetch_company_overview_via_crawling

# ============================================================================
# Configuration
# ============================================================================

DB_PATH = Path("local_data") / "jobs.db"

# Companies with real LinkedIn company pages — used when no args (test extraction, not slug/redirect)
DEFAULT_TEST_COMPANIES = [
    "Figma",
    "Google",
    "Microsoft",
    "Stripe",
    "Notion",
    "OpenAI",
]

# Same as pipeline.constants
DEFAULT_BAD_FIT_SCORES = ("Poor fit", "Very poor fit", "Questionable fit")
CHECK_SUSTAINABILITY = os.getenv("CHECK_SUSTAINABILITY", "false").lower() == "true"


def default_filter_job_keys(sheet) -> set:
    """Same logic as pipeline.bulk_ops._default_filter_job_keys."""
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


def get_companies_missing_co(sheet, limit: int | None = None) -> list[str]:
    """Return company names that need CO, same logic as fetch_company_overviews in bulk_ops."""
    default_filter_keys = default_filter_job_keys(sheet)
    all_rows = sheet.get_all_records()
    companies_to_fetch = []
    seen = set()

    for row in all_rows:
        job_url = row.get('Job URL', '').strip()
        company_name = row.get('Company Name', '').strip()
        if not job_url or not company_name:
            continue
        if (job_url, company_name) not in default_filter_keys:
            continue
        if row.get('Company overview') and str(row.get('Company overview')).strip():
            continue
        company_key = normalize_company_name(company_name)
        if company_key in seen:
            continue
        seen.add(company_key)
        companies_to_fetch.append(company_name)

    if limit is not None:
        companies_to_fetch = companies_to_fetch[:limit]
    return companies_to_fetch


def run_test(companies: list[str], pause_between: bool = True) -> None:
    """Run CO crawl test in non-headless mode and print detailed results."""
    print("\n" + "=" * 70)
    print("COMPANY OVERVIEW (CO) CRAWL TEST (non-headless)")
    print("=" * 70)
    print(f"\nTesting {len(companies)} companies. Watch the browser.\n")

    success_count = 0
    for i, company_name in enumerate(companies, 1):
        print("-" * 70)
        print(f"[{i}/{len(companies)}] {company_name}")
        print("-" * 70)

        result = fetch_company_overview_via_crawling(company_name, headless=False)

        print(f"  Status: {result['status']}")
        if result.get('error'):
            print(f"  Error:  {result['error']}")
        if result.get('overview'):
            success_count += 1
            preview = result['overview'][:300].replace('\n', ' ')
            if len(result['overview']) > 300:
                preview += "..."
            print(f"  Overview ({len(result['overview'])} chars): {preview}")

        if pause_between and i < len(companies):
            try:
                input("\n  Press Enter for next company (or Ctrl+C to stop)...")
            except KeyboardInterrupt:
                print("\nStopped by user.")
                break

    print("\n" + "=" * 70)
    print(f"Done. Successful: {success_count}/{len(companies)}")
    print("=" * 70 + "\n")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    use_db = "--db" in sys.argv
    pause = "--no-pause" not in sys.argv

    limit = 6
    for a in sys.argv[1:]:
        if a in ("--db", "--no-pause") or a.startswith("--"):
            continue
        try:
            limit = int(a)
            break
        except ValueError:
            pass

    if use_db:
        if not DB_PATH.exists():
            print(f"Error: Database not found at {DB_PATH}")
            return
        db = JobDatabase(str(DB_PATH), SHEET_HEADER)
        companies = get_companies_missing_co(db, limit=limit)
        if not companies:
            print("No companies found missing CO (with default filter).")
            return
        run_test(companies, pause_between=pause)
        return

    if args:
        companies = args
    else:
        companies = DEFAULT_TEST_COMPANIES.copy()
    run_test(companies, pause_between=pause)


if __name__ == "__main__":
    main()
