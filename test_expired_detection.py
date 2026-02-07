#!/usr/bin/env python3
"""
Debug test for "No longer accepting applications" / expired job detection.
Opens a known expired job URL with headless=False so you can see the page
and inspect what selectors find.

Usage (from project root):
  python test_expired_detection.py
"""

import sys
import time
from pathlib import Path

from selenium.webdriver.common.by import By

# Add project root
sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import _setup_linkedin_driver, _check_job_expired

TEST_URL = "https://www.linkedin.com/jobs/view/4355288971"


def main():
    print("Launching browser (headless=False)...")
    driver = _setup_linkedin_driver(headless=False)
    try:
        driver.get(TEST_URL)
        print(f"Loaded {TEST_URL}")
        print("Waiting 5s for page to settle...")
        time.sleep(5)

        # --- Debug: what's on the page? ---
        page_source = driver.page_source
        body_text = driver.find_element(By.TAG_NAME, "body").text

        print("\n" + "=" * 60)
        print("DEBUG: Page content")
        print("=" * 60)
        print(f"'No longer accepting applications' in page_source: {'No longer accepting applications' in page_source}")
        print(f"'no longer accepting applications' in body.text: {'no longer accepting applications' in body_text.lower()}")

        # Find all elements with aria-label="Error"
        error_els = driver.find_elements(By.CSS_SELECTOR, '[aria-label="Error"]')
        print(f"\nElements matching [aria-label=\"Error\"]: {len(error_els)}")
        for i, el in enumerate(error_els):
            tag = el.tag_name
            text = (el.text or "").strip()
            aria = el.get_attribute("aria-label")
            print(f"  [{i}] tag={tag} aria-label={aria!r} text_len={len(text)} text_preview={text[:150]!r}...")

        # LinkedIn closed-job pattern (from real page)
        closed_sel = 'figure.closed-job figcaption, figcaption.closed-job__flavor--closed'
        closed_els = driver.find_elements(By.CSS_SELECTOR, closed_sel)
        print(f"\nElements matching '{closed_sel}': {len(closed_els)}")
        for i, el in enumerate(closed_els):
            print(f"  [{i}] text={el.text.strip()!r}")

        # Also try other possible selectors (LinkedIn might use different markup)
        for selector, label in [
            ('[aria-label="Error"]', 'aria-label=Error'),
            ('[role="alert"]', 'role=alert'),
            ('*[class*="error"]', 'class*error'),
            ('*[class*="expired"]', 'class*expired'),
        ]:
            try:
                els = driver.find_elements(By.CSS_SELECTOR, selector)
                with_text = [e for e in els if e.text and "no longer" in e.text.lower()]
                print(f"  {label}: total={len(els)} with 'no longer' in text={len(with_text)}")
                for e in with_text[:2]:
                    print(f"    -> {e.text[:120]!r}")
            except Exception as e:
                print(f"  {label}: error {e}")

        # Snippet of page_source around "No longer accepting applications"
        if "No longer accepting applications" in page_source:
            idx = page_source.find("No longer accepting applications")
            snippet = page_source[max(0, idx - 300) : idx + 200]
            print("\nHTML snippet around 'No longer accepting applications':")
            print(snippet[:600])
            print("...")

        # Run the actual check
        print("\n" + "=" * 60)
        is_expired, reason = _check_job_expired(driver)
        print(f"Result: is_expired={is_expired} reason={reason!r}")
        print("=" * 60)

        input("\nPress Enter to close browser...")
    finally:
        driver.quit()
        print("Done.")


if __name__ == "__main__":
    main()
