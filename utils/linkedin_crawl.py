"""LinkedIn crawling: job descriptions, company overviews, search results, expiration check."""

import json
import random
import re
import time
from functools import wraps

from .apify_client import rate_limit

# Selectors to try for job description, in order of preference
_JD_SELECTORS = [
    ('div.show-more-less-html__markup', 'show-more-less-html__markup'),
    ('div[componentkey^="JobDetails_AboutTheJob"]', 'JobDetails_AboutTheJob'),
    ('section[data-job-id] div.show-more-less-html__markup', 'data-job-id section'),
    ('div.description__text', 'description__text'),
    ('section.description div.core-section-container__content', 'core-section-container'),
    ('div.jobs-description__content', 'jobs-description__content'),
    ('article.jobs-description', 'jobs-description'),
    ('div[class*="description"] p', 'description paragraph'),
]

_EXPIRED_INDICATORS = [
    'no longer accepting applications',
    'job is no longer available',
    'this job has expired',
    'position has been filled',
    'job has been closed',
    'application deadline has passed',
    'no longer active',
]


def random_scroll(driver, max_scrolls=3):
    """Perform random scrolling to mimic human behavior"""
    num_scrolls = random.randint(1, max_scrolls)
    for _ in range(num_scrolls):
        scroll_amount = random.randint(200, 800)
        driver.execute_script(f"window.scrollBy(0, {scroll_amount});")
        time.sleep(random.uniform(0.3, 0.8))

    if random.random() < 0.3:
        scroll_back = random.randint(100, 400)
        driver.execute_script(f"window.scrollBy(0, -{scroll_back});")
        time.sleep(random.uniform(0.2, 0.5))


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

        job_description = job_dict.get('job_description', '').replace('About the job\n', '').replace('\nSee less', '').strip()
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


def scrape_multiple_pages(driver, search_url: str, max_pages: int = 5) -> list:
    """Scrape jobs from multiple pages of search results."""
    all_jobs = []
    current_page = 1

    driver.get(search_url)
    time.sleep(random.uniform(2, 4))

    while current_page <= max_pages:
        print(f"  Scraping page {current_page}/{max_pages}")

        from custom_job_search import CustomJobSearch

        job_search = CustomJobSearch(driver=driver, close_on_complete=False, scrape=False)
        page_jobs = job_search.scrape_from_url(driver.current_url)
        all_jobs.extend(page_jobs)

        print(f"  Found {len(page_jobs)} jobs on page {current_page}")

        try:
            from selenium.webdriver.common.by import By

            next_button = driver.find_element(
                By.CSS_SELECTOR,
                'button[aria-label="View next page"].jobs-search-pagination__button--next'
            )

            if next_button.get_attribute('disabled'):
                print(f"  Reached last page at page {current_page}")
                break

            driver.execute_script("arguments[0].scrollIntoView(True);", next_button)
            time.sleep(random.uniform(0.5, 1.0))
            next_button.click()

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
        return job_search.scrape_from_url(search_url)
    except Exception as e:
        print(f"Error scraping search results from {search_url}: {e}")
        return []


def _company_name_to_linkedin_slug(company_name: str) -> str:
    """Convert company name to LinkedIn URL slug."""
    slug = company_name.lower()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'\s+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    slug = slug.strip('-')
    return slug


def _setup_linkedin_driver(headless: bool = False):
    """Set up Chrome driver with anti-detection measures for LinkedIn crawling."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    options = Options()
    if headless:
        options.add_argument('--headless=new')

    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--no-sandbox')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)

    width = random.randint(1350, 1450)
    height = random.randint(850, 950)

    driver = webdriver.Chrome(options=options)
    driver.set_window_size(width, height)
    # Prevent driver.get() from hanging indefinitely on slow or stuck pages
    driver.set_page_load_timeout(60)
    driver.implicitly_wait(10)

    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
        'source': '''
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            })
        '''
    })

    return driver


def _looks_like_product_blurb(text: str) -> bool:
    """True if text looks like a product/integration blurb, not a company About description."""
    if not text or len(text) < 50:
        return False  # too short to classify; allow short overviews (50–199 chars) unless signals below match
    t = text.lower()
    # Feature-list / integration style (e.g. "Figma in Google Chat" sidebar)
    if " → " in text or " get notified " in t or " in google chat " in t or " in slack " in t:
        return True
    if re.search(r"preview \w+ files?\s*[→\-]", t) or ("reply to comments" in t and " in chat" in t):
        return True
    return False


def _looks_like_cookie_banner(text: str) -> bool:
    """True if text is cookie/privacy banner, not company About."""
    if not text or len(text) < 50:
        return False
    t = text.lower()
    if "linkedin respects your privacy" in t or "cookie policy" in t:
        return True
    if "essential and non-essential cookies" in t or "select accept to consent" in t:
        return True
    return False


def _looks_like_sidebar_or_nav(text: str) -> bool:
    """True if text looks like a sidebar/nav block (followers, See jobs, etc.), not the About paragraph."""
    if not text or len(text) < 80:
        return False
    t = text.lower()
    # Sidebar often has "X followers", "See jobs", "Follow", "Discover all X employees" in one block
    if " followers " in t and ("see jobs" in t or " follow " in t):
        return True
    if "touch glass" in t and "overview" in t and "jobs" in t:  # nav + metadata
        return True
    return False


# Known anchor phrases for company About (element containing this is in the right block)
_ABOUT_ANCHOR_PHRASES = [
    "Design is everyone's business",  # Figma
]


def _extract_linkedin_overview(driver) -> str | None:
    """Extract company overview from LinkedIn company page. Returns best candidate; LLM can handle noise."""
    from selenium.webdriver.common.by import By

    candidates: list[str] = []

    def _ok(c: str) -> bool:
        return (
            not _looks_like_product_blurb(c)
            and not _looks_like_cookie_banner(c)
            and not _looks_like_sidebar_or_nav(c)
        )

    # 0) Anchor on known phrase
    for phrase in _ABOUT_ANCHOR_PHRASES:
        try:
            els = driver.find_elements(
                By.XPATH,
                f'.//*[contains(normalize-space(), {json.dumps(phrase)})]'
            )
            anchor_candidates = []
            for el in els:
                text = (el.text or "").strip()
                if not text or phrase not in text or _looks_like_cookie_banner(text):
                    continue
                if 50 < len(text) < 15000:
                    anchor_candidates.append(text)
            if anchor_candidates:
                candidates.append(min(anchor_candidates, key=len))
        except Exception:
            continue

    # 1) LinkedIn About selectors
    for selector in (
        '.org-about-module__description p',
        '.organization-about-module__content-consistant-cards-description p',
        'p[data-test-id="about-us__description"]',
        '[data-test-id="about-us__description"]',
        '.org-about-module__description',
        '.organization-about-module__content-consistant-cards-description',
        'section[data-test-id="about-us"] p',
        'div[data-test-id="about-us"] p',
    ):
        try:
            el = driver.find_element(By.CSS_SELECTOR, selector)
            text = (el.text or "").strip()
            if text and len(text) > 50:
                candidates.append(text)
        except Exception:
            continue

    # 2) JSON-LD
    try:
        scripts = driver.find_elements(By.CSS_SELECTOR, 'script[type="application/ld+json"]')
        for script in scripts:
            try:
                raw = script.get_attribute('innerHTML')
                if not raw:
                    continue
                data = json.loads(raw)
                if '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') in ('Organization', 'Corporation'):
                            desc = item.get('description') or item.get('articleBody')
                            if desc and len(desc) > 80:
                                candidates.append(desc.strip())
                if isinstance(data, dict) and 'description' in data:
                    desc = data['description']
                    if desc and len(desc) > 80:
                        candidates.append(desc.strip())
            except Exception:
                continue
    except Exception:
        pass

    # 3) meta description
    try:
        meta = driver.find_element(By.CSS_SELECTOR, 'meta[name="description"]')
        content = (meta.get_attribute('content') or "").strip()
        if content and len(content) > 50 and "linkedin" not in content.lower() and "log in" not in content.lower():
            candidates.append(content)
        for p in content.split("|"):
            p = p.strip()
            if len(p) > 50 and "linkedin" not in p.lower() and "log in" not in p.lower():
                candidates.append(p)
    except Exception:
        pass

    # 4) main fallback (capped to avoid slowness)
    for selector in ('main p', '[role="main"] p', 'section.core-section-container p', 'div.ph5 p'):
        try:
            els = driver.find_elements(By.CSS_SELECTOR, selector)
            for el in els[:12]:
                text = (el.text or "").strip()
                if text and 100 < len(text) < 15000 and "cookie" not in text.lower()[:100]:
                    candidates.append(text)
            if candidates:
                break
        except Exception:
            continue

    good = [c for c in candidates if len(c) >= 200 and _ok(c)]
    if good:
        return max(good, key=len)
    fallback = [c for c in candidates if len(c) >= 80 and _ok(c)]
    if fallback:
        return max(fallback, key=len)
    return None


def fetch_company_overview_via_crawling(company_name: str, headless: bool = True) -> dict:
    """Fetch company overview by directly crawling LinkedIn company page."""
    result = {
        'status': 'unknown',
        'overview': None,
        'error': None
    }

    slug = _company_name_to_linkedin_slug(company_name)
    url = f"https://www.linkedin.com/company/{slug}"

    driver = None
    try:
        # Page load has a 60s timeout; if it hangs, we'll return status 'timeout'
        driver = _setup_linkedin_driver(headless=headless)
        time.sleep(1)

        try:
            driver.get(url)
        except Exception as load_err:
            err_msg = getattr(load_err, "msg", str(load_err))
            if "timeout" in err_msg.lower() or "TimeoutException" in type(load_err).__name__:
                result['status'] = 'timeout'
                result['error'] = f'Page load timed out: {url}'
                return result
            raise
        # Shorter wait so we detect wrong/missing page faster (was 4–6s)
        time.sleep(random.uniform(2, 3))

        final_url = driver.current_url
        title = (driver.title or "").strip()

        if 'login' in final_url or 'authwall' in final_url:
            result['status'] = 'auth_wall'
            result['error'] = 'Redirected to login'
            return result

        if 'page not found' in title.lower() or '/404' in final_url:
            result['status'] = 'not_found'
            return result

        if '/company/' not in final_url:
            result['status'] = 'redirected'
            result['error'] = f'Unexpected redirect: {final_url}'
            return result

        # Early check: title should match company (avoids wasting time on wrong/generic page)
        title_lower = title.lower()
        company_lower = company_name.lower()
        slug_lower = slug.lower()
        name_in_title = company_lower in title_lower or slug_lower in title_lower
        # Allow "Figma | LinkedIn" or "Notion – Overview" etc.; reject if title is clearly another company
        if not name_in_title and len(title) > 3:
            # Could be wrong company (e.g. different "Notion") or generic LinkedIn page
            result['status'] = 'no_overview'
            result['error'] = 'Page title does not match company (wrong or generic page)'
            return result

        overview = _extract_linkedin_overview(driver)
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


def fetch_company_overviews_via_crawling(
    company_names: list[str],
    headless: bool = True,
    min_delay: float = 12.0,
    max_delay: float = 20.0
) -> tuple[dict[str, str], list[str]]:
    """Fetch company overviews by crawling LinkedIn company pages."""
    if not company_names:
        return {}, []

    print(f"\nFetching {len(company_names)} company overviews via LinkedIn crawling...")

    successful = {}
    failed = []
    consecutive_auth_walls = 0

    for i, company_name in enumerate(company_names):
        # Print progress every time when few companies, otherwise every 10
        if len(company_names) <= 10 or (i + 1) % 10 == 0 or i == 0:
            print(f"  Crawling progress: {i + 1}/{len(company_names)} — {company_name}")
        result = fetch_company_overview_via_crawling(company_name, headless=headless)

        if result['status'] == 'success' and result['overview']:
            successful[company_name] = result['overview']
            consecutive_auth_walls = 0
        else:
            failed.append(company_name)

            if result['status'] == 'auth_wall':
                consecutive_auth_walls += 1
                if consecutive_auth_walls >= 3:
                    pause_minutes = random.randint(5, 8)
                    print(f"  [!] {consecutive_auth_walls} consecutive auth walls. Pausing {pause_minutes} minutes...")
                    time.sleep(pause_minutes * 60)
                    consecutive_auth_walls = 0
            else:
                consecutive_auth_walls = 0

        if i < len(company_names) - 1:
            time.sleep(random.uniform(min_delay, max_delay))

    print(f"  Crawling complete: {len(successful)} successful, {len(failed)} failed")
    return successful, failed


def _extract_job_description(driver) -> str | None:
    """Extract job description from LinkedIn job page."""
    from selenium.webdriver.common.by import By

    for selector, _ in _JD_SELECTORS:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for el in elements:
                text = el.text.strip()
                if text and len(text) > 200:
                    return text
        except Exception:
            continue
    return None


def _check_job_expired(driver) -> tuple[bool, str | None]:
    """Check if job page indicates the job is expired/closed."""
    from selenium.webdriver.common.by import By

    try:
        closed_figures = driver.find_elements(By.CSS_SELECTOR, 'figure.closed-job figcaption, figcaption.closed-job__flavor--closed')
        for el in closed_figures:
            if el.text and 'no longer accepting applications' in el.text.lower():
                return True, 'No longer accepting applications (closed-job)'
    except Exception:
        pass

    try:
        error_els = driver.find_elements(By.CSS_SELECTOR, '[aria-label="Error"]')
        for el in error_els:
            if el.text and 'no longer accepting applications' in el.text.lower():
                return True, 'No longer accepting applications (aria-label=Error)'
    except Exception:
        pass

    try:
        page_text = driver.find_element(By.TAG_NAME, 'body').text.lower()
        for indicator in _EXPIRED_INDICATORS:
            if indicator in page_text:
                return True, indicator
    except Exception:
        pass

    return False, None


def _is_job_search_page(driver, requested_job_url: str) -> bool:
    """Return True if the current page looks like a job search/results page."""
    url = (requested_job_url or "").strip()
    current = (driver.current_url or "").strip()
    if "/jobs/search" in current:
        return True
    if "/jobs/view/" in url:
        job_id = url.rstrip("/").split("/")[-1].split("?")[0]
        if job_id and job_id not in current:
            return True
    return False


def fetch_job_description_via_crawling(job_url: str, headless: bool = True) -> dict:
    """Fetch job description for a single job using a fresh browser session."""
    result = {
        'status': 'unknown',
        'description': None,
        'is_expired': False,
        'expired_reason': None,
        'error': None
    }

    driver = None
    try:
        driver = _setup_linkedin_driver(headless=headless)
        time.sleep(1)

        driver.get(job_url)
        time.sleep(5)

        final_url = driver.current_url
        title = driver.title

        if 'login' in final_url or 'authwall' in final_url:
            result['status'] = 'auth_wall'
            result['error'] = 'Redirected to login'
            return result

        if 'page not found' in title.lower() or '/404' in final_url:
            result['status'] = 'not_found'
            result['is_expired'] = True
            result['expired_reason'] = '404 page'
            return result

        is_expired, expired_reason = _check_job_expired(driver)
        if is_expired:
            result['status'] = 'expired'
            result['is_expired'] = True
            result['expired_reason'] = expired_reason
            return result

        if _is_job_search_page(driver, job_url):
            result['status'] = 'search_page'
            result['error'] = 'Landed on job search page instead of single job view'
            return result

        description = _extract_job_description(driver)
        if description:
            result['status'] = 'success'
            result['description'] = description
        else:
            result['status'] = 'no_description'
            result['error'] = 'Page loaded but no job description found (selector issue, NOT necessarily expired)'

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


def fetch_job_descriptions_via_crawling(
    jobs: list[dict],
    headless: bool = True,
    min_delay: float = 5.0,
    max_delay: float = 10.0,
    on_result: callable = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Fetch job descriptions by crawling LinkedIn job pages."""
    if not jobs:
        return [], [], []

    print(f"\n  Fetching {len(jobs)} job descriptions via LinkedIn crawling...")
    print(f"    (Press Ctrl+C to stop crawling early - partial results will be saved)")

    successful = []
    expired = []
    failed = []
    consecutive_auth_walls = 0
    interrupted = False

    for i, job in enumerate(jobs):
        try:
            job_url = job.get('job_url', '')
            company = job.get('company', '')
            title = job.get('title', '')

            if (i + 1) % 10 == 0 or i == 0:
                print(f"    JD crawling progress: {i + 1}/{len(jobs)} (success={len(successful)}, expired={len(expired)}, failed={len(failed)})")

            result = fetch_job_description_via_crawling(job_url, headless=headless)

            status = result['status']
            desc_len = len(result.get('description') or '') if result.get('description') else 0
            print(f"      [{i+1}] {company[:30]:30} | status={status:15} | desc_len={desc_len}")

            if result['status'] == 'success' and result['description']:
                desc_text = result['description']
                job_data = {'job_url': job_url, 'company': company, 'description': desc_text}
                successful.append(job_data)
                if on_result:
                    try:
                        on_result('success', job_data)
                    except Exception as e:
                        print(f"        [WARN] on_result(success) failed: {e}")
                print(f"        → Added to successful list (desc_len={len(desc_text)})")
                consecutive_auth_walls = 0
            elif result['status'] == 'success' and not result['description']:
                print(f"        → WARNING: status=success but description is None/empty!")
                job_data = {'job_url': job_url, 'company': company}
                failed.append(job_data)
                if on_result:
                    try:
                        on_result('failed', job_data)
                    except Exception as e:
                        print(f"        [WARN] on_result(failed) failed: {e}")
            elif result['is_expired']:
                job_data = {
                    'job_url': job_url,
                    'company': company,
                    'reason': result['expired_reason']
                }
                expired.append(job_data)
                if on_result:
                    try:
                        on_result('expired', job_data)
                    except Exception as e:
                        print(f"        [WARN] on_result(expired) failed: {e}")
                print(f"        → Expired ({result.get('expired_reason') or 'unknown reason'})")
                consecutive_auth_walls = 0
            else:
                job_data = {'job_url': job_url, 'company': company}
                failed.append(job_data)
                if on_result:
                    try:
                        on_result('failed', job_data)
                    except Exception as e:
                        print(f"        [WARN] on_result(failed) failed: {e}")
                if result.get('status') == 'search_page':
                    print(f"        → Landed on search page (wrong JD skipped)")
                elif result.get('error'):
                    print(f"        Error: {result['error'][:80]}")

                if result['status'] == 'auth_wall':
                    consecutive_auth_walls += 1
                    if consecutive_auth_walls >= 3:
                        pause_minutes = random.randint(3, 5)
                        print(f"    [!] {consecutive_auth_walls} consecutive auth walls. Pausing {pause_minutes} minutes...")
                        time.sleep(pause_minutes * 60)
                        consecutive_auth_walls = 0
                else:
                    consecutive_auth_walls = 0

            if i < len(jobs) - 1:
                time.sleep(random.uniform(min_delay, max_delay))

        except KeyboardInterrupt:
            print(f"\n    [!] Keyboard interrupt received - stopping crawl early")
            print(f"    Partial results: {len(successful)} successful, {len(expired)} expired, {len(failed)} failed")
            interrupted = True
            break

    if not interrupted:
        print(f"    JD crawling complete: {len(successful)} successful, {len(expired)} expired, {len(failed)} failed")

    if failed:
        print(f"    [!] WARNING: {len(failed)} jobs could not be crawled - will try Apify fallback if batch is large enough")

    return successful, expired, failed


def retry_on_selenium_error(max_retries=3, delay=5):
    """Decorator to retry a function call on specific Selenium exceptions."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                from selenium.common import StaleElementReferenceException
            except ImportError:
                from selenium.common.exceptions import StaleElementReferenceException
            try:
                from httpcore import TimeoutException
            except ImportError:
                TimeoutException = TimeoutError

            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (StaleElementReferenceException, TimeoutException, TimeoutError) as e:
                    last_exception = e
                    print(f"Caught {type(e).__name__}. Retrying in {delay} seconds (Attempt {attempt + 1}/{max_retries})...")
                    time.sleep(delay)
            raise RuntimeError(
                f"Function failed after {max_retries} attempts due to unrecoverable error: {type(last_exception).__name__}"
            ) from last_exception

        return wrapper

    return decorator


@retry_on_selenium_error(max_retries=3, delay=5)
def check_job_expiration(driver, job_url: str) -> bool | None:
    """Check if a job posting has expired by navigating to the URL."""
    try:
        driver.get(job_url)
        random_scroll(driver)
        time.sleep(random.uniform(1.5, 2.5))

        is_expired, _ = _check_job_expired(driver)
        if is_expired:
            return True
        page_source = driver.page_source
        return 'No longer accepting applications' in page_source or "The job you were looking for was not found." in page_source
    except Exception as e:
        print(f"Error checking job expiration for {job_url}: {e}")
        return None
