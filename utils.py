import json
import os
import random
import time
from functools import wraps
from typing import Any

import google.genai as genai
import gspread
import html2text
from urllib.parse import urlparse, parse_qs
from apify_client import ApifyClient
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Google Sheets OAuth setup
SCOPES = ["https://www.googleapis.com/auth/drive",
          "https://www.googleapis.com/auth/spreadsheets"]

# Global variable to track last request time
last_request_time = 0


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


def get_google_creds():
    """Get authorized Google credentials, supporting both Service Account and OAuth."""
    creds = None
    
    # 1. Try Service Account first (Easiest for new users)
    if os.path.exists('service_account.json'):
        try:
            creds = service_account.Credentials.from_service_account_file(
                'service_account.json', scopes=SCOPES)
            return creds
        except Exception as e:
            print(f"Warning: Failed to load service_account.json: {e}")

    # 2. Fallback to OAuth flow (credentials.json + token.json)
    try:
        if os.path.exists('token.json'):
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception:
                    creds = None

            if not creds or not creds.valid:
                if not os.path.exists('credentials.json'):
                    raise Exception("Missing 'service_account.json' OR 'credentials.json'. "
                                    "Please follow the setup guide to obtain credentials.")
                
                flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
                creds = flow.run_local_server(port=0)

            # Save the new/refreshed credentials
            with open('token.json', 'w') as token:
                token.write(creds.to_json())
        
        return creds
    except Exception as e:
        raise Exception(f"Google authentication failed: {e}")


def get_google_client():
    """Get an authorized gspread client."""
    creds = get_google_creds()
    return gspread.authorize(creds)


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

        # # Run the actor
        # run = client.actor("apimaestro/linkedin-company-detail").call(run_input=run_input)
        # 
        # # Fetch results from the dataset
        # items = list(client.dataset(run["defaultDatasetId"]).iterate_items())

        items = [
            {
                "input_identifier": "Enway",
                "basic_info": {
                    "name": "ENWAY a Bucher Company",
                    "universal_name": "enway",
                    "description": "ENWAY is a deep tech specialist based in Berlin, specializing in building the software platform for autonomous sweeping machines. Our cutting-edge technology enables machines to work intelligently, performing repetitive and dangerous tasks or supporting drivers to work more efficiently.\n\nIn September 2022, ENWAY joined forces with Bucher Municipal, one of the largest municipal sweeping manufacturers. Together, we are actively working towards our shared vision of fully autonomous sweeping vehicles. We value an  entrepreneurial \"can-do\" attitude.",
                    "website": "http://www.enway.ai",
                    "linkedin_url": "https://www.linkedin.com/company/enway/",
                    "specialties": [
                        "Autonomous Operations",
                        "Technology Platform",
                        "Street Sweeping",
                        "Autonomous Vehicles",
                        "Artificial Intelligence",
                        "Machine Learning",
                        "Autonomous Cleaning",
                        "Industrial Cleaning",
                        "Autonomous Driving",
                        "Computer Vision",
                        "Electrical Engineering",
                        "Software Engineering",
                        "Smart city",
                        "Green city",
                        "Clean city",
                        "Robotics"
                    ],
                    "industries": [
                        "Information Technology & Services"
                    ],
                    "is_verified": False,
                    "founded_info": {
                        "year": 2017,
                        "month": None,
                        "day": None
                    },
                    "page_type": "COMPANY",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "We are building the software platform for autonomous sweeping machines.",
                "phone": "",
                "company_urn": "18164664",
                "stats": {
                    "employee_count": 16,
                    "follower_count": 2657,
                    "employee_count_range": {
                        "start": 11,
                        "end": 50
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {
                        "country": "DE",
                        "state": "Berlin",
                        "city": "Berlin",
                        "postal_code": "12099",
                        "line1": "Mariendorfer Damm 1",
                        "line2": "c/o The Drivery",
                        "is_hq": True,
                        "description": "Enway GmbH"
                    },
                    "offices": [
                        {
                            "country": "DE",
                            "state": "Berlin",
                            "city": "Berlin",
                            "postal_code": "12099",
                            "line1": "Mariendorfer Damm 1",
                            "line2": "c/o The Drivery",
                            "is_hq": True,
                            "description": "Enway GmbH",
                            "region": "Berlin"
                        },
                        {
                            "country": "SG",
                            "state": None,
                            "city": "Singapore",
                            "postal_code": "068914",
                            "line1": "160 Robinson Road #24-09",
                            "line2": None,
                            "is_hq": False,
                            "description": "Enway Pte Ltd",
                            "region": "Singapore"
                        }
                    ],
                    "geo_coordinates": {
                        "latitude": 52.560253,
                        "longitude": 13.296672
                    }
                },
                "media": {
                    "logo_url": "https://media.licdn.com/dms/image/v2/D4D0BAQHi1vNgwCBLow/company-logo_400_400/company-logo_400_400/0/1734707081608/enway_logo?e=1765411200&v=beta&t=Qk8Bqd7mU8492UUKLUtaMuA9P8z7UM1ANnwBFnJV9TI",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "http://www.enway.ai",
                    "linkedin": "https://www.linkedin.com/company/enway/",
                    "job_search": "https://www.linkedin.com/jobs/search?geoId=92000000&f_C=18164664",
                    "sales_navigator": None,
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "Learn more",
                    "url": "http://enway.ai/",
                    "type": "LEARN_MORE",
                    "visible": True
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [
                    "7324290",
                    "18291296",
                    "3116425",
                    "10641045",
                    "11857884",
                    "11203741",
                    "28813464",
                    "10554031",
                    "14829209",
                    "11059328",
                    "33186384",
                    "10037458"
                ],
                "hashtags": [
                    "#robotics",
                    "#autonomous",
                    "#autonomousvehicles"
                ],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "Us3 Consulting",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "ComfNet Solutions GmbH",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "NFON AG",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "Wizdata Solutions",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "BDO Germany",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "Talent Link by e2i",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "Robin Cook",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "Baker Finn Recruitment",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "NVIDIA",
                "basic_info": {
                    "name": "NVIDIA",
                    "universal_name": "nvidia",
                    "description": "Since its founding in 1993, NVIDIA (NASDAQ: NVDA) has been a pioneer in accelerated computing. The company’s invention of the GPU in 1999 sparked the growth of the PC gaming market, redefined computer graphics, ignited the era of modern AI and is fueling the creation of the metaverse. NVIDIA is now a full-stack computing company with data-center-scale offerings that are reshaping industry.",
                    "website": "http://www.nvidia.com",
                    "linkedin_url": "https://www.linkedin.com/company/nvidia/",
                    "specialties": [
                        "GPU-accelerated computing",
                        "artificial intelligence",
                        "deep learning",
                        "virtual reality",
                        "gaming",
                        "self-driving cars",
                        "supercomputing",
                        "robotics",
                        "virtualization",
                        "parallel computing",
                        "professional graphics",
                        "automotive technology"
                    ],
                    "industries": [
                        "Computer Hardware"
                    ],
                    "is_verified": True,
                    "founded_info": {
                        "year": 1993,
                        "month": None,
                        "day": None
                    },
                    "page_type": "COMPANY",
                    "verification": {
                        "is_verified": True,
                        "last_verified_at": 1692140741310
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "3608",
                "stats": {
                    "employee_count": 45883,
                    "follower_count": 4353816,
                    "employee_count_range": {
                        "start": 10001,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {
                        "country": "US",
                        "state": "CA",
                        "city": "Santa Clara",
                        "postal_code": "95050",
                        "line1": "2701 San Tomas Expressway",
                        "line2": None,
                        "is_hq": True,
                        "description": None
                    },
                    "offices": [
                        {
                            "country": "JP",
                            "state": "Minato-ku",
                            "city": "Tokyo",
                            "postal_code": "107-0052",
                            "line1": "2-11-7 Akasaka",
                            "line2": " 13th Floor",
                            "is_hq": False,
                            "description": "ATT New Tower ",
                            "region": "Tokyo"
                        },
                        {
                            "country": "US",
                            "state": "CA",
                            "city": "Santa Clara",
                            "postal_code": "95050",
                            "line1": "2701 San Tomas Expressway",
                            "line2": None,
                            "is_hq": True,
                            "description": None,
                            "region": "Santa Clara"
                        },
                        {
                            "country": "TW",
                            "state": "Taipei City",
                            "city": "Taipei City",
                            "postal_code": "114",
                            "line1": "No. 8, Ji Hu Rd.",
                            "line2": None,
                            "is_hq": False,
                            "description": "NVIDIA BVI Holdings Limited, Taiwan Branch",
                            "region": "Taipei City"
                        },
                        {
                            "country": "IN",
                            "state": "Village Chakala, Andheri East",
                            "city": "Mumbai",
                            "postal_code": "400 093",
                            "line1": "No. 127 Andheri Kurla Road",
                            "line2": "CNB Square",
                            "is_hq": False,
                            "description": "NVIDIA Graphics Pvt. Ltd. ",
                            "region": "Mumbai"
                        },
                        {
                            "country": "IN",
                            "state": "Telangana",
                            "city": "Hyderabad",
                            "postal_code": "500046",
                            "line1": "Nanakramguda, Serilingampally Mandal",
                            "line2": "Plot # 6A&B, IT Park Layout, RR District",
                            "is_hq": False,
                            "description": "NVIDIA Graphics Pvt. Ltd.",
                            "region": "Hyderabad"
                        },
                        {
                            "country": "IN",
                            "state": "Yerwada",
                            "city": "Pune",
                            "postal_code": "411 006",
                            "line1": "Survey No. 144/145, Samrat Ashok Path",
                            "line2": "Off Airport Road",
                            "is_hq": False,
                            "description": "Commerzone, Building No. 5",
                            "region": "Pune"
                        }
                    ],
                    "geo_coordinates": {
                        "latitude": 35.69269,
                        "longitude": 139.709
                    }
                },
                "media": {
                    "logo_url": "https://media.licdn.com/dms/image/v2/D560BAQGV36q2EowSyw/company-logo_400_400/company-logo_400_400/0/1724881581208/nvidia_logo?e=1765411200&v=beta&t=zuN5mzV2Aw9sJIaUhaGSc5SiITWwO4k4WCbEONADGXA",
                    "cover_url": "https://media.licdn.com/dms/image/v2/D561BAQFf-h2uJn9luw/company-background_10000/B56ZhC2Y0vHMAU-/0/1753468210846/nvidia_cover?e=1764532800&v=beta&t=6QEHeTJAQW0tNHjLRjGx8eFuBuPLKzzcs2ZxwOg-p08",
                    "cropped_cover_url": "https://media.licdn.com/dms/image/v2/D563DAQE7hmSKOEQ4-g/image-scale_191_1128/B56ZhC2Y0mG4Ag-/0/1753468210886/nvidia_cover?e=1764532800&v=beta&t=1EB3nRYWzBE-Jl7xDx8KXZdtlHiXHGQwZGGIY5MtB14"
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "http://www.nvidia.com",
                    "linkedin": "https://www.linkedin.com/company/nvidia/",
                    "job_search": "https://www.linkedin.com/jobs/search?geoId=92000000&f_C=3608",
                    "sales_navigator": None,
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "Visit website",
                    "url": "https://www.nvidia.com",
                    "type": "VIEW_WEBSITE",
                    "visible": True
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [
                        "18000973",
                        "99467754",
                        "18000077",
                        "3589800",
                        "3970082",
                        "42446849",
                        "42447607",
                        "18094797",
                        "103331527",
                        "6629126",
                        "100932021",
                        "90460745",
                        "37553728",
                        "40981439",
                        "68992010",
                        "79124990",
                        "3761136",
                        "71986325"
                    ],
                    "by_jobs": []
                },
                "similar_companies": [
                    "106863934",
                    "103331527",
                    "90460745",
                    "71986325",
                    "68992010",
                    "18000973",
                    "101031931",
                    "18000077",
                    "104825671",
                    "18094797",
                    "11193683",
                    "3970082"
                ],
                "hashtags": [
                    "#deeplearning",
                    "#gpu",
                    "#ai"
                ],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "Finanzguru",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "Adentis Portugal",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "NBCC Consulting",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "Storyblok",
                "basic_info": {
                    "name": "Storyblok",
                    "universal_name": "storyblok",
                    "description": "Storyblok is a headless CMS that enables marketers and developers to create with joy and succeed in the AI-driven content era. It empowers you to deliver structured and consistent content everywhere: websites, apps, AI search, and beyond.\n\nMarketers get a visual editor with reusable components, in-context preview, and workflows to launch fast and stay on brand. Developers have freedom to use their favorite frameworks and integrate with anything through the API-first platform. Brands get one source of truth for content that is accurate, flexible, and measurable.\n\nLegendary brands like Virgin Media O2, Oatly, and TomTom use Storyblok to make a bigger, faster market impact. It’s Joyful Headless™, and it changes everything.",
                    "website": "https://www.storyblok.com",
                    "linkedin_url": "https://www.linkedin.com/company/storyblok/",
                    "specialties": [
                        "CMS",
                        "Content Management System",
                        "headless CMS",
                        "SaaS",
                        "headless e-commerce"
                    ],
                    "industries": [
                        "Computer Software"
                    ],
                    "is_verified": True,
                    "founded_info": {
                        "year": 2017,
                        "month": None,
                        "day": None
                    },
                    "page_type": "COMPANY",
                    "verification": {
                        "is_verified": True,
                        "last_verified_at": 1694542711442
                    }
                },
                "tagline": "Storyblok is a headless CMS that helps marketers & developers create with joy and win in the AI-driven content era.",
                "phone": "",
                "company_urn": "17989065",
                "stats": {
                    "employee_count": 286,
                    "follower_count": 38879,
                    "employee_count_range": {
                        "start": 201,
                        "end": 500
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {
                        "country": "AT",
                        "state": "Oberösterreich",
                        "city": "Linz",
                        "postal_code": "4020",
                        "line1": "Peter-Behrens-Platz 2",
                        "line2": "Bau 2, 2. Stock",
                        "is_hq": True,
                        "description": "Tabakfabrik"
                    },
                    "offices": [
                        {
                            "country": "GB",
                            "state": "England",
                            "city": "London",
                            "postal_code": "W8 5EH",
                            "line1": "Young Street",
                            "line2": None,
                            "is_hq": False,
                            "description": "Northcliffe House",
                            "region": "London"
                        },
                        {
                            "country": "DE",
                            "state": None,
                            "city": "Hamburg",
                            "postal_code": "20359",
                            "line1": "Aufzug A., 6. Stock",
                            "line2": None,
                            "is_hq": False,
                            "description": "Regus Millertorplatz 1",
                            "region": "Hamburg"
                        },
                        {
                            "country": "US",
                            "state": "Delaware",
                            "city": "Wilmington",
                            "postal_code": "19801",
                            "line1": "129 Orange St",
                            "line2": None,
                            "is_hq": False,
                            "description": "Storyblok, Inc.",
                            "region": "Wilmington"
                        },
                        {
                            "country": "BR",
                            "state": None,
                            "city": "Rio de Janeiro",
                            "postal_code": "22775-040",
                            "line1": "Abelardo Bueno 600 - Barra da Tijuca",
                            "line2": None,
                            "is_hq": False,
                            "description": "Av. Embaixador",
                            "region": "Rio De Janeiro"
                        },
                        {
                            "country": "AT",
                            "state": None,
                            "city": "Vienna",
                            "postal_code": "1060",
                            "line1": "Loquaiplatzt 12/2",
                            "line2": None,
                            "is_hq": False,
                            "description": "Storyblok Solutions GmbH",
                            "region": "Vienna"
                        },
                        {
                            "country": "AT",
                            "state": "Oberösterreich",
                            "city": "Linz",
                            "postal_code": "4020",
                            "line1": "Peter-Behrens-Platz 2",
                            "line2": "Bau 2, 2. Stock",
                            "is_hq": True,
                            "description": "Tabakfabrik",
                            "region": "Linz"
                        }
                    ],
                    "geo_coordinates": {
                        "latitude": 51.51649,
                        "longitude": -0.128427
                    }
                },
                "media": {
                    "logo_url": "https://media.licdn.com/dms/image/v2/D4D0BAQH2iK5SRvu9ig/company-logo_400_400/company-logo_400_400/0/1736709482795/storyblok_logo?e=1765411200&v=beta&t=f1piTXd8Z267zx6zamg-CZqYZI-26zaMi91KdSi5PAU",
                    "cover_url": "https://media.licdn.com/dms/image/v2/D4D1BAQGCXbn7oy_xow/company-background_10000/B4DZqWazy8IgAU-/0/1763460202203/storyblok_cover?e=1764532800&v=beta&t=_PHHJH7oAcH3Bw8F7iiHGtRZ-C10tjFjj4ubm5FREGQ",
                    "cropped_cover_url": "https://media.licdn.com/dms/image/v2/D4D3DAQEjs7sEPi478Q/image-scale_191_1128/B4DZqWazy0HwAg-/0/1763460202200/storyblok_cover?e=1764532800&v=beta&t=F47hYhMDK185RrieRJcsl48GKggXZ-vGwxws7X66Nhg"
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "https://www.storyblok.com",
                    "linkedin": "https://www.linkedin.com/company/storyblok/",
                    "job_search": "https://www.linkedin.com/jobs/search?geoId=92000000&f_C=17989065",
                    "sales_navigator": None,
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "Contact us",
                    "url": "https://www.storyblok.com/fs/enterprise-contact",
                    "type": "VIEW_CONTACT_INFO",
                    "visible": True
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [
                    "28491094",
                    "128505",
                    "1594050",
                    "74126343",
                    "109731",
                    "10688209",
                    "16181286",
                    "7947",
                    "216295",
                    "38115511",
                    "33883",
                    "18867879"
                ],
                "hashtags": [
                    "#cms",
                    "#storyblok",
                    "#content"
                ],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "PrimeIT",
                "basic_info": {
                    "name": "Prime IT B.V.",
                    "universal_name": "primeit",
                    "description": None,
                    "website": "http://www.primeit.nl",
                    "linkedin_url": "https://www.linkedin.com/company/primeit/",
                    "specialties": [],
                    "industries": [
                        "Information Technology & Services"
                    ],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "COMPANY",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "Be First, Be Professional, Be Prime!",
                "phone": "",
                "company_urn": "14799172",
                "stats": {
                    "employee_count": 2,
                    "follower_count": 23,
                    "employee_count_range": {
                        "start": 2,
                        "end": 10
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {
                        "country": "NL",
                        "state": "North Holland",
                        "city": "Aalsmeer",
                        "postal_code": "1431",
                        "line1": "Lakenblekerstraat 49",
                        "line2": None,
                        "is_hq": True,
                        "description": "Hoofdkantoor"
                    },
                    "offices": [
                        {
                            "country": "NL",
                            "state": "North Holland",
                            "city": "Aalsmeer",
                            "postal_code": "1431",
                            "line1": "Lakenblekerstraat 49",
                            "line2": None,
                            "is_hq": True,
                            "description": "Hoofdkantoor",
                            "region": "Aalsmeer"
                        }
                    ],
                    "geo_coordinates": {
                        "latitude": 51.89373,
                        "longitude": 4.523071
                    }
                },
                "media": {
                    "logo_url": "https://media.licdn.com/dms/image/v2/C4D0BAQGl3UD4CiYe7A/company-logo_400_400/company-logo_400_400/0/1630537462122/primeit_logo?e=1765411200&v=beta&t=8j6qbNuxi34a7p0P__18U9qb5QVe_-HCYrOOgqsgFII",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "http://www.primeit.nl",
                    "linkedin": "https://www.linkedin.com/company/primeit/",
                    "job_search": "https://www.linkedin.com/jobs/search?geoId=92000000&f_C=14799172",
                    "sales_navigator": None,
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "Visit website",
                    "url": "http://www.primeit.nl",
                    "type": "VIEW_WEBSITE",
                    "visible": True
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [
                    "928486"
                ],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "Berlin Recycling",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "Morgan McKinley",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "KASIKORN Business-Technology Group [KBTG]",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "Makro PRO",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "Phillip Life Assurance",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "Infinitas by Krungthai",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "Bitazza",
                "basic_info": {
                    "name": "Bitazza",
                    "universal_name": "bitazza",
                    "description": "A digital asset broker breaking frontiers and bridging the gap between the old and new.",
                    "website": "https://www.bitazza.com",
                    "linkedin_url": "https://www.linkedin.com/company/bitazza/",
                    "specialties": [],
                    "industries": [
                        "Financial Services"
                    ],
                    "is_verified": True,
                    "founded_info": {
                        "year": 2018,
                        "month": None,
                        "day": None
                    },
                    "page_type": "COMPANY",
                    "verification": {
                        "is_verified": True,
                        "last_verified_at": 1755896757945
                    }
                },
                "tagline": "Bitazza is one of the fastest growing and trusted digital assets management platforms globally. Freedom begins here.",
                "phone": "",
                "company_urn": "18853034",
                "stats": {
                    "employee_count": 112,
                    "follower_count": 27002,
                    "employee_count_range": {
                        "start": 51,
                        "end": 200
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {
                        "country": "TH",
                        "state": "Bangkok City",
                        "city": "Makkasan",
                        "postal_code": "10400",
                        "line1": "Phaya Thai Road",
                        "line2": None,
                        "is_hq": True,
                        "description": None
                    },
                    "offices": [
                        {
                            "country": "TH",
                            "state": "Bangkok City",
                            "city": "Makkasan",
                            "postal_code": "10400",
                            "line1": "Phaya Thai Road",
                            "line2": None,
                            "is_hq": True,
                            "description": None,
                            "region": "Makkasan"
                        }
                    ],
                    "geo_coordinates": {
                        "latitude": 13.783921,
                        "longitude": 100.55141
                    }
                },
                "media": {
                    "logo_url": "https://media.licdn.com/dms/image/v2/D560BAQGH6xVugc5pkg/company-logo_400_400/company-logo_400_400/0/1666013403179?e=1765411200&v=beta&t=0FkCmcX-0gUkwvrqmPa7s9i57jzOMnAxII4IuWUBkCs",
                    "cover_url": "https://media.licdn.com/dms/image/v2/D561BAQFoRYXspvPvNQ/company-background_10000/company-background_10000/0/1667966255134/bitazza_cover?e=1764532800&v=beta&t=RzanZ-01-qS6OPvtDRcJvBm-sfHj6WpeNWcxMj7D5mY",
                    "cropped_cover_url": "https://media.licdn.com/dms/image/v2/D563DAQGZtZZhuTtoPg/image-scale_191_1128/image-scale_191_1128/0/1667966255341/bitazza_cover?e=1764532800&v=beta&t=OLia9_2NFIePh2gYf_KdR2ca3PBBsetiX3ezNArQ6KY"
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "https://www.bitazza.com",
                    "linkedin": "https://www.linkedin.com/company/bitazza/",
                    "job_search": "https://www.linkedin.com/jobs/search?geoId=92000000&f_C=18853034",
                    "sales_navigator": None,
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "Visit website",
                    "url": "https://bitazza.com",
                    "type": "VIEW_WEBSITE",
                    "visible": True
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [
                    "18963513",
                    "33246798",
                    "6451760",
                    "844671",
                    "589418",
                    "90595583",
                    "13336409",
                    "69884978",
                    "6436310",
                    "10310718",
                    "68615195",
                    "73819824"
                ],
                "hashtags": [
                    "#digitalbanking",
                    "#fintech",
                    "#blockchain"
                ],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "Global Sport Ventures",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "ttb bank",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "SCB – Siam Commercial Bank",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "MyPetroCareer.com",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "Onepoint",
                "basic_info": {
                    "name": "Onepoint",
                    "universal_name": "onepoint",
                    "description": "Depuis 25 ans, Onepoint accompagne les grandes transformations des entreprises et des acteurs publics.\nGroupe international de conseil et de tech, présent dans 19 villes partout dans le monde, il réunit un collectif 4 500 talents et réalise un chiffre d’affaires annuel de plus de 500 millions d’euros.   ",
                    "website": "https://www.groupeonepoint.com",
                    "linkedin_url": "https://www.linkedin.com/company/onepoint/",
                    "specialties": [
                        "Transformation digitale",
                        "Vision & stratégie",
                        "Innovation",
                        "Design",
                        "Développement, opération & sécurité",
                        "Architecture & process",
                        "Organisation & culture",
                        "Data & IA",
                        "Plateformes",
                        "Supercollectifs"
                    ],
                    "industries": [
                        "Management Consulting"
                    ],
                    "is_verified": True,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "COMPANY",
                    "verification": {
                        "is_verified": True,
                        "last_verified_at": 1686852035939
                    }
                },
                "tagline": "Depuis plus de 20 ans, Onepoint accompagne les grandes transformations des entreprises et des acteurs publics.",
                "phone": "",
                "company_urn": "816396",
                "stats": {
                    "employee_count": 3725,
                    "follower_count": 127803,
                    "employee_count_range": {
                        "start": 1001,
                        "end": 5000
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {
                        "country": "FR",
                        "state": None,
                        "city": "Paris",
                        "postal_code": "75116",
                        "line1": "29, rue des Sablons",
                        "line2": None,
                        "is_hq": True,
                        "description": "Onepoint Paris"
                    },
                    "offices": [
                        {
                            "country": "FR",
                            "state": "Pays de la Loire",
                            "city": "Nantes",
                            "postal_code": "44100",
                            "line1": "3, Rue Lavoisier",
                            "line2": None,
                            "is_hq": False,
                            "description": "Onepoint Nantes",
                            "region": "Nantes"
                        },
                        {
                            "country": "FR",
                            "state": None,
                            "city": "Paris",
                            "postal_code": "75116",
                            "line1": "29, rue des Sablons",
                            "line2": None,
                            "is_hq": True,
                            "description": "Onepoint Paris",
                            "region": "Paris"
                        },
                        {
                            "country": "FR",
                            "state": "Auvergne-Rhône-Alpes",
                            "city": "Lyon",
                            "postal_code": "69002",
                            "line1": "5, Rue Charles Biennier",
                            "line2": None,
                            "is_hq": False,
                            "description": "Onepoint Lyon",
                            "region": "Lyon"
                        },
                        {
                            "country": "FR",
                            "state": None,
                            "city": "Begles",
                            "postal_code": "33130",
                            "line1": "2, rue Marc Sangnier",
                            "line2": "La Cité Numérique",
                            "is_hq": False,
                            "description": "Onepoint Bordeaux",
                            "region": "Begles"
                        },
                        {
                            "country": "BE",
                            "state": "Belgium North",
                            "city": "Zele",
                            "postal_code": "B-9240",
                            "line1": "Nachtegaalstraat 8W3",
                            "line2": "RINKHOUT",
                            "is_hq": False,
                            "description": "Onepoint Zele - Belgium North",
                            "region": "Belgium"
                        },
                        {
                            "country": "BE",
                            "state": "Région de Bruxelles-Capitale",
                            "city": "Bruxelles",
                            "postal_code": "1000",
                            "line1": "Chaussée de la Hulpe 120",
                            "line2": None,
                            "is_hq": False,
                            "description": "Onepoint Bruxelles - Belgique Sud",
                            "region": "Belgium"
                        },
                        {
                            "country": "SG",
                            "state": None,
                            "city": "Singapour",
                            "postal_code": "308900",
                            "line1": "51 Goldhill Plaza",
                            "line2": None,
                            "is_hq": False,
                            "description": "Onepoint Singapour",
                            "region": "Singapour"
                        },
                        {
                            "country": "CA",
                            "state": "Québec",
                            "city": "Montréal",
                            "postal_code": "H3B",
                            "line1": "606 Rue Cathcart",
                            "line2": "Bureau 400",
                            "is_hq": False,
                            "description": "Onepoint Canada",
                            "region": "Montréal"
                        },
                        {
                            "country": "AU",
                            "state": "Nouvelle-Galles du Sud",
                            "city": "Centre d'affaires de Sydney",
                            "postal_code": "2000",
                            "line1": "233 Castlereagh St",
                            "line2": None,
                            "is_hq": False,
                            "description": "Onepoint Australia, Sydney",
                            "region": "Centre D'affaires De Sydney"
                        },
                        {
                            "country": "AU",
                            "state": "Victoria",
                            "city": "Melbourne",
                            "postal_code": "3000",
                            "line1": "575 Bourke St",
                            "line2": "Level 7",
                            "is_hq": False,
                            "description": "Onepoint Australia, Melbourne",
                            "region": "Melbourne"
                        }
                    ],
                    "geo_coordinates": {
                        "latitude": 47.253536,
                        "longitude": -1.522597
                    }
                },
                "media": {
                    "logo_url": "https://media.licdn.com/dms/image/v2/D4E0BAQGvpe_509Zo-w/company-logo_400_400/company-logo_400_400/0/1665673493364/onepoint_logo?e=1765411200&v=beta&t=t9OFaXOkG0OyniWj0IvSJ20lQjDplLQxJ5UiLLwbomE",
                    "cover_url": "https://media.licdn.com/dms/image/v2/D4E1BAQFvAIwdFW6ljg/company-background_10000/B4EZnD7eQvIoAU-/0/1759928773044/onepoint_cover?e=1764532800&v=beta&t=DqcIZVJui3D9tM5nLhxPGGKRUfrSYqmDN3F_LGa41Yk",
                    "cropped_cover_url": "https://media.licdn.com/dms/image/v2/D4E3DAQFEQHsU9xGvcA/image-scale_191_1128/B4EZnD7eRdGoAc-/0/1759928772758/onepoint_cover?e=1764532800&v=beta&t=1P3utynI_H3cKMsJRsJeO2d0bGwDfM5meGGRha_LKjI"
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "https://www.groupeonepoint.com",
                    "linkedin": "https://www.linkedin.com/company/onepoint/",
                    "job_search": "https://www.linkedin.com/jobs/search?geoId=92000000&f_C=816396%2C1227272%2C19845",
                    "sales_navigator": None,
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "Visit website",
                    "url": "https://www.groupeonepoint.com",
                    "type": "VIEW_WEBSITE",
                    "visible": True
                },
                "affiliated_companies": {
                    "by_employees": [
                        "1227272",
                        "19845"
                    ],
                    "showcases": [
                        "94230886",
                        "5150991"
                    ],
                    "by_jobs": [
                        "1227272",
                        "19845"
                    ]
                },
                "similar_companies": [
                    "26628263",
                    "69183778",
                    "106205930",
                    "12627290",
                    "76588919",
                    "5146464",
                    "80951952",
                    "12997986",
                    "88877348",
                    "1711",
                    "66650664",
                    "9427185"
                ],
                "hashtags": [
                    "#transformationdigitale",
                    "#onepoint"
                ],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "OMRON Industrial Automation APAC",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "Hudson Singapore",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "YouTrip",
                "basic_info": {
                    "name": "YouTrip",
                    "universal_name": "youtrip",
                    "description": "YouTrip is the leading and fastest-growing multi-currency payment platform in Asia Pacific. In 2018, we pioneered the region's first multi-currency digital wallet. Now, YouTrip is the #1 multi-currency digital wallet trusted by millions across the region, processing over US$15 billion in total payment value annually. \n\nOur consumer and business propositions – YouTrip and YouBiz – empower individuals and businesses with inclusive, accessible, and affordable financial solutions. YouTrip has raised over US$110 million to date, including its recent Series B round led by global venture capital firm Lightspeed Venture Partners—underscoring strong investor confidence in its mission to transform digital financial services across the Asia Pacific. \n\nRecognised as World Economic Forum’s Global Innovator 2025, CNBC’s World’s Top Fintech Companies (2025, 2024), and LinkedIn’s Top Startup (2024, 2023), YouTrip is dedicated to creating the next generation of digital finance services for consumers and businesses.",
                    "website": "http://www.you.co",
                    "linkedin_url": "https://www.linkedin.com/company/youtrip/",
                    "specialties": [
                        "fintech",
                        "payment",
                        "FX",
                        "finance",
                        "technology",
                        "SE Asia",
                        "cross-border",
                        "B2B payments",
                        "remittance",
                        "Asia Pacific"
                    ],
                    "industries": [
                        "Financial Services"
                    ],
                    "is_verified": True,
                    "founded_info": {
                        "year": 2016,
                        "month": None,
                        "day": None
                    },
                    "page_type": "COMPANY",
                    "verification": {
                        "is_verified": True,
                        "last_verified_at": 1694542711794
                    }
                },
                "tagline": "#1 multi-currency digital wallet trusted by millions across Asia Pacific",
                "phone": "",
                "company_urn": "13239491",
                "stats": {
                    "employee_count": 285,
                    "follower_count": 114366,
                    "employee_count_range": {
                        "start": 201,
                        "end": 500
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {
                        "country": "SG",
                        "state": "Singapore",
                        "city": "Singapore",
                        "postal_code": None,
                        "line1": None,
                        "line2": None,
                        "is_hq": True,
                        "description": "Singapore Office"
                    },
                    "offices": [
                        {
                            "country": "SG",
                            "state": "Singapore",
                            "city": "Singapore",
                            "postal_code": None,
                            "line1": None,
                            "line2": None,
                            "is_hq": True,
                            "description": "Singapore Office",
                            "region": "Singapore"
                        },
                        {
                            "country": "TH",
                            "state": None,
                            "city": "Bangkok",
                            "postal_code": None,
                            "line1": None,
                            "line2": None,
                            "is_hq": False,
                            "description": "Thailand Office",
                            "region": "Bangkok"
                        }
                    ],
                    "geo_coordinates": {
                        "latitude": 1.356523,
                        "longitude": 103.80859
                    }
                },
                "media": {
                    "logo_url": "https://media.licdn.com/dms/image/v2/D560BAQH1SRVf5t8LTw/company-logo_400_400/company-logo_400_400/0/1686543505724/youtrip_logo?e=1765411200&v=beta&t=VNORsCfO2KfR4AxQjB_x-GJ6HASSSx3AMfdZXmAM0Ko",
                    "cover_url": "https://media.licdn.com/dms/image/v2/D561BAQGDcdjAE9RANA/company-background_10000/company-background_10000/0/1686544552893/youtrip_cover?e=1764532800&v=beta&t=cN-aMFDwd5i8Z5_eIIw-UkVbdHmQSQdWGiW41KlfuSM",
                    "cropped_cover_url": "https://media.licdn.com/dms/image/v2/D563DAQEnJ7rrFxfNAw/image-scale_191_1128/image-scale_191_1128/0/1686544552530/youtrip_cover?e=1764532800&v=beta&t=46kv36feBN-AYOe8gTi4HiTnJFq6elvy3YG79z5T13w"
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "http://www.you.co",
                    "linkedin": "https://www.linkedin.com/company/youtrip/",
                    "job_search": "https://www.linkedin.com/jobs/search?geoId=92000000&f_C=13239491",
                    "sales_navigator": None,
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "Visit website",
                    "url": "http://www.you.co",
                    "type": "VIEW_WEBSITE",
                    "visible": True
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [
                    "3656965",
                    "6451760",
                    "5382086",
                    "33246798",
                    "88007673",
                    "165158",
                    "2235",
                    "2778669",
                    "8771",
                    "3788927",
                    "18118",
                    "13393453"
                ],
                "hashtags": [
                    "#fintech",
                    "#startup",
                    "#youtrip"
                ],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "Vouch Recruitment",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "X-Press Feeders",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "Ollion",
                "basic_info": {
                    "name": "Ollion",
                    "universal_name": "ollion",
                    "description": "Ollion is the enterprise tech consultancy that’s all in on your future. Our global team of ~600 employees around the world is solving the kind of business problems you can actually put a name to, working together to untangle complex challenges on our way to creating elegant, iterative, and enduring solutions. \n\nIn other words, helping ambitious organizations just like yours change – and change for good. \n\nWe’re Ollion. \nAnd we’re here to multiply humanity’s potential. \n\nFormed in 2023 through the merger and integration of ST Telemedia Cloud in Singapore (comprising the former businesses of Cloud Comrade and CloudCover) and 2nd Watch in the US (including Aptitive, acquired by 2nd watch in 2022). These companies – originated in Seattle, Chicago, India and Singapore – make Ollion a truly global enterprise.\n\nBacked by experienced tech investors, including ST Telemedia, Columbia Capital, Madrona and Delta-V.\n",
                    "website": "www.ollion.com",
                    "linkedin_url": "https://www.linkedin.com/company/ollion/",
                    "specialties": [
                        "Cloud Consulting",
                        "Managed Service Provider",
                        "Public Cloud Migrations",
                        "Cloud Architecture",
                        "Cloud Roadmap",
                        "Public Cloud Workload Management",
                        "Cloud Advisory",
                        "Cloud Modernization",
                        "Data Insights",
                        "Cloud Security",
                        "Cloud Operations",
                        "Code Pipes",
                        "Cloud Economics"
                    ],
                    "industries": [
                        "Information Technology & Services"
                    ],
                    "is_verified": False,
                    "founded_info": {
                        "year": 2023,
                        "month": None,
                        "day": None
                    },
                    "page_type": "COMPANY",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "Ollion is the global, born-in-the-cloud consultancy working together to unify business-shaping tech for good.",
                "phone": "",
                "company_urn": "97402272",
                "stats": {
                    "employee_count": 257,
                    "follower_count": 37913,
                    "employee_count_range": {
                        "start": 501,
                        "end": 1000
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "https://media.licdn.com/dms/image/v2/D4D0BAQGLCusa28wSTQ/company-logo_400_400/company-logo_400_400/0/1698871635837/ollion_logo?e=1765411200&v=beta&t=3R-GX9HbE_hmm5LSlqmSQio0FikuuyU1ZTIDDKZjzkw",
                    "cover_url": "https://media.licdn.com/dms/image/v2/D4D1BAQEeGHDy4-BlVg/company-background_10000/company-background_10000/0/1698871227808/ollion_cover?e=1764532800&v=beta&t=jK5qUOAiitpepZ81JxFeOgsh0gHLFGq4Tjw0jOWRFGE",
                    "cropped_cover_url": "https://media.licdn.com/dms/image/v2/D4D3DAQHolLdI-_VKJg/image-scale_191_1128/image-scale_191_1128/0/1698871227769/ollion_cover?e=1764532800&v=beta&t=D-tsjAHKmabUmb1Y149ipPdMNRbO2zmcPlWU8mt4sKA"
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "www.ollion.com",
                    "linkedin": "https://www.linkedin.com/company/ollion/",
                    "job_search": "https://www.linkedin.com/jobs/search?geoId=92000000&f_C=97402272",
                    "sales_navigator": None,
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "Visit website",
                    "url": "http://www.ollion.com",
                    "type": "VIEW_WEBSITE",
                    "visible": True
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [
                    "96454343",
                    "1441",
                    "64863146",
                    "9304199",
                    "102011558",
                    "18027771",
                    "2880382",
                    "14623098",
                    "2505439",
                    "15506",
                    "16168340",
                    "4286466"
                ],
                "hashtags": [
                    "#ollionglobal",
                    "#ollion",
                    "#weareollion"
                ],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "GKP Solutions, Inc.",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "Trulyyy",
                "basic_info": {
                    "name": "Trulyyy",
                    "universal_name": "trulyyy",
                    "description": "Trulyyy is a specialized recruitment firm dedicated to fostering a dynamic ecosystem in both tech and commercial domains within the Singapore business landscape. We prioritize the interests of companies and professionals alike.\n\nFor Clients - we invest time in comprehensively understanding your products, requirements, and corporate culture, adopting a strategic approach that incorporates Corporate Function discipline for both technical and non-technical entities. Our mission is to assist companies in assembling high-performing teams while ensuring alignment with broader organizational goals across various business functions.\n\nFor Talents - our commitment extends beyond understanding your expertise and career motivations. We go the extra mile by sharing market trends and offering career consultation, addressing not only technical roles but also incorporating Corporate Function discipline. Our goal is to help professionals in joining a dream team that suits their aspirations and skills.",
                    "website": "http://www.trulyyy.com",
                    "linkedin_url": "https://www.linkedin.com/company/trulyyy/",
                    "specialties": [
                        "Tech Recruitment",
                        "Commercial Recruitment",
                        "Professional Recruitment",
                        "Career Consulting"
                    ],
                    "industries": [
                        "Human Resources"
                    ],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "COMPANY",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "A specialized recruitment firm fostering tech and commercial ecosystem within Singapore Business Landscape",
                "phone": "",
                "company_urn": "65633438",
                "stats": {
                    "employee_count": 12,
                    "follower_count": 32425,
                    "employee_count_range": {
                        "start": 11,
                        "end": 50
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {
                        "country": "SG",
                        "state": None,
                        "city": "Singapore",
                        "postal_code": None,
                        "line1": None,
                        "line2": None,
                        "is_hq": True,
                        "description": "Headquarters"
                    },
                    "offices": [
                        {
                            "country": "SG",
                            "state": None,
                            "city": "Singapore",
                            "postal_code": None,
                            "line1": None,
                            "line2": None,
                            "is_hq": True,
                            "description": "Headquarters",
                            "region": "Singapore"
                        }
                    ],
                    "geo_coordinates": {
                        "latitude": 1.356523,
                        "longitude": 103.80859
                    }
                },
                "media": {
                    "logo_url": "https://media.licdn.com/dms/image/v2/C560BAQGsCyCQR_Nd9Q/company-logo_400_400/company-logo_400_400/0/1630670987288?e=1765411200&v=beta&t=m8OnAH7XR7sH_0k1rukdyrU1CNRCrgeoROQZvkxlNss",
                    "cover_url": "https://media.licdn.com/dms/image/v2/C561BAQFX2OpnT3BY7A/company-background_10000/company-background_10000/0/1649993065266/trulyyy_cover?e=1764532800&v=beta&t=bWOYnLVU5BPL3r2dfWKPhRn7MC5FVozDQmKuw7J0oZI",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "http://www.trulyyy.com",
                    "linkedin": "https://www.linkedin.com/company/trulyyy/",
                    "job_search": "https://www.linkedin.com/jobs/search?geoId=92000000&f_C=65633438",
                    "sales_navigator": None,
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "Visit website",
                    "url": "http://www.trulyyy.com",
                    "type": "VIEW_WEBSITE",
                    "visible": True
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [
                    "6451760",
                    "33246798",
                    "2778669",
                    "1104359",
                    "13336409",
                    "13322447",
                    "2530051",
                    "1912194",
                    "16175",
                    "18289948",
                    "3821463",
                    "10667"
                ],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "A5 Labs",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "Kulicke & Soffa",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "Searce Inc",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "Breeze",
                "basic_info": {
                    "name": "Breezeworks",
                    "universal_name": "breeze",
                    "description": "Running your own service company is hard. As a small business owner, you are expected to excel at every role — salesperson, marketer, taskmaster, accountant, dispatcher, and receptionist. Breezeworks’ mission is to put cutting-edge mobile technology in the hands of service professionals like you. We build products that improve your quality of life and help you serve your customers better.\r\n\r\nLed by CEO Matthew Cowan and CTO Adam Block, Breezeworks is a tight-knit team of tech folks and small business specialists. We’re backed by a group of inspirational technology and business leaders including Marc Benioff, Max Levchin, James Murdoch, David Sacks, Jeff Skoll and Peter Thiel, and investors Allen & Company, Obvious Ventures, Charles River Ventures, Harmony Partners and XSeed Capital.\r\n\r\nWe have an enduring faith in the power of small business, and we’re focused on building the technology to help your small business succeed. Our customers are our greatest asset and we love to hear from you.",
                    "website": "http://www.breezeworks.com/",
                    "linkedin_url": "https://www.linkedin.com/company/breeze/",
                    "specialties": [],
                    "industries": [
                        "Information Technology & Services"
                    ],
                    "is_verified": False,
                    "founded_info": {
                        "year": 2012,
                        "month": None,
                        "day": None
                    },
                    "page_type": "COMPANY",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": None,
                "phone": "",
                "company_urn": "1272562",
                "stats": {
                    "employee_count": 27,
                    "follower_count": 242,
                    "employee_count_range": {
                        "start": 11,
                        "end": 50
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {
                        "country": "US",
                        "state": None,
                        "city": "San Francisco",
                        "postal_code": None,
                        "line1": None,
                        "line2": None,
                        "is_hq": True,
                        "description": None
                    },
                    "offices": [
                        {
                            "country": "US",
                            "state": None,
                            "city": "San Francisco",
                            "postal_code": None,
                            "line1": None,
                            "line2": None,
                            "is_hq": True,
                            "description": None,
                            "region": "San Francisco"
                        }
                    ],
                    "geo_coordinates": {
                        "latitude": 37.39271,
                        "longitude": -122.042
                    }
                },
                "media": {
                    "logo_url": "https://media.licdn.com/dms/image/v2/C560BAQHOl0LXzPxHNQ/company-logo_400_400/company-logo_400_400/0/1631317534920?e=1765411200&v=beta&t=RNl22tr6EjFVKs5Ss_PHEe1uJ4GMVLE_SaHjIlkgGgA",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "http://www.breezeworks.com/",
                    "linkedin": "https://www.linkedin.com/company/breeze/",
                    "job_search": "https://www.linkedin.com/jobs/search?geoId=92000000&f_C=1272562",
                    "sales_navigator": None,
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "Visit website",
                    "url": "http://www.breezeworks.com/",
                    "type": "VIEW_WEBSITE",
                    "visible": True
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [
                    "14484420",
                    "2500210",
                    "37256517",
                    "18728102",
                    "254852",
                    "6391875",
                    "2081083",
                    "243491",
                    "129463",
                    "28791829",
                    "79353700",
                    "3490856"
                ],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "Visier Inc.",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "Cygnify",
                "basic_info": {
                    "name": "Cygnify",
                    "universal_name": "cygnify",
                    "description": "Cygnify is an on-demand, plug & play TA team on a month-to-month subscription, delivering unlimited global hires with no placement fees.\n\nOur Talent Acquisition as a Service (TAaaS) offers companies instant access to a fully managed team of recruitment experts, cutting-edge AI tools, and a 100M+ candidate database. \n\nAll our monthly plans are transparent, and flexible, with no lock-ins, supporting all roles, levels, and locations globally.\n\nPress Play to supercharge your Talent Acquisition—streamlining hiring with a single partner across every location, leveraging our deep market expertise, extensive networks, and proven success in securing top talent.\n\nAvoid the high costs of growing an in-house team and agency placement fees. We have it all in our plug & play TA solution.\n",
                    "website": "https://www.cygnify.io/",
                    "linkedin_url": "https://www.linkedin.com/company/cygnify/",
                    "specialties": [
                        "TAaaS",
                        "Recruitment",
                        "Talent Acquisition",
                        "RPO"
                    ],
                    "industries": [
                        "Management Consulting"
                    ],
                    "is_verified": True,
                    "founded_info": {
                        "year": 2024,
                        "month": None,
                        "day": None
                    },
                    "page_type": "COMPANY",
                    "verification": {
                        "is_verified": True,
                        "last_verified_at": 1755896757961
                    }
                },
                "tagline": "Talent Acquisition as a Service (TAaaS) - Your Global TA Team On-Demand",
                "phone": "",
                "company_urn": "97225930",
                "stats": {
                    "employee_count": 13,
                    "follower_count": 55188,
                    "employee_count_range": {
                        "start": 11,
                        "end": 50
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {
                        "country": "SG",
                        "state": None,
                        "city": "Singapore",
                        "postal_code": None,
                        "line1": None,
                        "line2": None,
                        "is_hq": True,
                        "description": None
                    },
                    "offices": [
                        {
                            "country": "SG",
                            "state": None,
                            "city": "Singapore",
                            "postal_code": None,
                            "line1": None,
                            "line2": None,
                            "is_hq": True,
                            "description": None,
                            "region": "Singapore"
                        }
                    ],
                    "geo_coordinates": {
                        "latitude": 1.356523,
                        "longitude": 103.80859
                    }
                },
                "media": {
                    "logo_url": "https://media.licdn.com/dms/image/v2/D560BAQHLR3u2XDu8kA/company-logo_400_400/B56ZU1l0AqHEAc-/0/1740360860052/cygnify_logo?e=1765411200&v=beta&t=0Acn4xaNOLoXycd1zRQWSMZZ1eNLRfKwMNrhBkQshoU",
                    "cover_url": "https://media.licdn.com/dms/image/v2/D561BAQGs0aEMrtiegA/company-background_10000/B56ZU24uGdGsAU-/0/1740382593875/cygnify_cover?e=1764532800&v=beta&t=fBEMw-wuHow7SHL0R_E7WHxeKLUPgouRlV7WXvrDA1Q",
                    "cropped_cover_url": "https://media.licdn.com/dms/image/v2/D563DAQGZ2ruRCUAZQQ/image-scale_191_1128/B56ZU24uG2HQAc-/0/1740382593843/cygnify_cover?e=1764532800&v=beta&t=9pwqme-aawpR20E7b_OWlIrL7p_b4TjmKIo6f65b7j8"
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "https://www.cygnify.io/",
                    "linkedin": "https://www.linkedin.com/company/cygnify/",
                    "job_search": "https://www.linkedin.com/jobs/search?geoId=92000000&f_C=97225930",
                    "sales_navigator": None,
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "Visit website",
                    "url": "http://www.cygnify.io",
                    "type": "VIEW_WEBSITE",
                    "visible": True
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [
                    "1104359",
                    "104857176",
                    "6451760",
                    "33246798",
                    "104665252",
                    "166328",
                    "13336409",
                    "308813",
                    "16175",
                    "71534821",
                    "1038",
                    "66719"
                ],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "Crossing Hurdles",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "Coinbase",
                "basic_info": {
                    "name": "Coinbase",
                    "universal_name": "coinbase",
                    "description": "Founded in June of 2012, Coinbase is a digital currency wallet and platform where merchants and consumers can transact with new digital currencies like bitcoin, ethereum, and litecoin. Our vision is to bring more innovation, efficiency, and equality of opportunity to the world by building an open financial system. Our first step on that journey is making digital currency accessible and approachable for everyone. Two principles guide our efforts. First, be the most trusted company in our domain. Second, create user-focused products that are easier and more intuitive to use.",
                    "website": "http://www.coinbase.com",
                    "linkedin_url": "https://www.linkedin.com/company/coinbase/",
                    "specialties": [
                        "Digital Currency",
                        "Software",
                        "Payment Processing",
                        "Bitcoin",
                        "Technology",
                        "API",
                        "Cryptography",
                        "Bitcoin Exchange",
                        "Digital Currency Exchange",
                        "Virtual Currency",
                        "FinTech",
                        "Ethereum",
                        "Ether",
                        "Blockchain"
                    ],
                    "industries": [
                        "Financial Services"
                    ],
                    "is_verified": True,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "COMPANY",
                    "verification": {
                        "is_verified": True,
                        "last_verified_at": 1677652959756
                    }
                },
                "tagline": None,
                "phone": "",
                "company_urn": "2857634",
                "stats": {
                    "employee_count": 7108,
                    "follower_count": 1304367,
                    "employee_count_range": {
                        "start": 1001,
                        "end": 5000
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {
                        "country": "US",
                        "state": None,
                        "city": "Remote First",
                        "postal_code": None,
                        "line1": None,
                        "line2": None,
                        "is_hq": True,
                        "description": None
                    },
                    "offices": [
                        {
                            "country": "US",
                            "state": None,
                            "city": "Remote First",
                            "postal_code": None,
                            "line1": None,
                            "line2": None,
                            "is_hq": True,
                            "description": None,
                            "region": "Remote First"
                        }
                    ],
                    "geo_coordinates": {
                        "latitude": 39.643436,
                        "longitude": -79.99579
                    }
                },
                "media": {
                    "logo_url": "https://media.licdn.com/dms/image/v2/C560BAQHsPlWyC0Ksxg/company-logo_400_400/company-logo_400_400/0/1630669856291/coinbase_logo?e=1765411200&v=beta&t=uLTuNQ0_hR2D26qqI5bDrCKyJaXvrQBuo9ZePIi8gQQ",
                    "cover_url": "https://media.licdn.com/dms/image/v2/D4E1BAQG6eIu7Qw-h_w/company-background_10000/company-background_10000/0/1726081654510/coinbase_cover?e=1764532800&v=beta&t=4pcBN5NI4SB2mgEIOBioG6ghf5hIG95-O_FpE4E3WhA",
                    "cropped_cover_url": "https://media.licdn.com/dms/image/v2/D4E3DAQE6VH50vtC6Dg/image-scale_191_1128/image-scale_191_1128/0/1726081654112/coinbase_cover?e=1764532800&v=beta&t=t9-uBzLA6uBjmI-LZVYLkLyJCFJw4hg-IA5eYJ3YcCQ"
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "http://www.coinbase.com",
                    "linkedin": "https://www.linkedin.com/company/coinbase/",
                    "job_search": "https://www.linkedin.com/jobs/search?geoId=92000000&f_C=2857634",
                    "sales_navigator": None,
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "Visit website",
                    "url": "http://www.coinbase.com",
                    "type": "VIEW_WEBSITE",
                    "visible": True
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [
                        "72067847",
                        "108298673"
                    ],
                    "by_jobs": []
                },
                "similar_companies": [
                    "72057622",
                    "13451935",
                    "13336409",
                    "1666",
                    "1815218",
                    "1441",
                    "3509899",
                    "72067847",
                    "9266905",
                    "1337",
                    "13005306",
                    "165158"
                ],
                "hashtags": [
                    "#coinbase",
                    "#livecrypto",
                    "#cryptocurrency"
                ],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "Synapxe",
                "basic_info": {
                    "name": "Synapxe",
                    "universal_name": "synapxe",
                    "description": "Synapxe is the national HealthTech agency inspiring tomorrow’s health. The nexus of HealthTech, we connect people and systems to power a healthier Singapore.\n\nTogether with partners, we create intelligent technological solutions to improve the health of millions of people every day, everywhere. Reimagine the future of health together with us at www.synapxe.sg",
                    "website": "https://careers-public-healthtech-jobs.synapxe.sg/",
                    "linkedin_url": "https://www.linkedin.com/company/synapxe/",
                    "specialties": [
                        "Enterprise Architecture",
                        "Applications Development",
                        "Software Engineering",
                        "Data Centre Management",
                        "IT Security",
                        "IT Planning & Infrastructure",
                        "Artificial Intelligence",
                        "Robotics ",
                        "Command & Control ",
                        "IT Program Management",
                        "IT Master Planning",
                        "Business Intelligence"
                    ],
                    "industries": [
                        "Information Technology & Services"
                    ],
                    "is_verified": True,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "COMPANY",
                    "verification": {
                        "is_verified": True,
                        "last_verified_at": 1686852097228
                    }
                },
                "tagline": None,
                "phone": "",
                "company_urn": "373987",
                "stats": {
                    "employee_count": 3532,
                    "follower_count": 83720,
                    "employee_count_range": {
                        "start": 1001,
                        "end": 5000
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {
                        "country": "SG",
                        "state": None,
                        "city": "Singapore",
                        "postal_code": "139691",
                        "line1": "1 N Buona Vista Link, Singapore 139691",
                        "line2": None,
                        "is_hq": True,
                        "description": "Synapxe"
                    },
                    "offices": [
                        {
                            "country": "SG",
                            "state": None,
                            "city": "Singapore",
                            "postal_code": "139691",
                            "line1": "1 N Buona Vista Link, Singapore 139691",
                            "line2": None,
                            "is_hq": True,
                            "description": "Synapxe",
                            "region": "Singapore"
                        }
                    ],
                    "geo_coordinates": {
                        "latitude": 1.356523,
                        "longitude": 103.80859
                    }
                },
                "media": {
                    "logo_url": "https://media.licdn.com/dms/image/v2/D560BAQHEwgT_3YzScg/company-logo_400_400/company-logo_400_400/0/1690375113349/ihis_sg_logo?e=1765411200&v=beta&t=BIFXqafXeg44VEjZS_FvuOnG3MHmqrqzR7FEsVHqFnE",
                    "cover_url": "https://media.licdn.com/dms/image/v2/D561BAQGXOg8zMrxtrA/company-background_10000/company-background_10000/0/1728613234604/synapxe_cover?e=1764532800&v=beta&t=yMCCgGmTIM_HnH7OYXwq-DHhC11z5gvSDs2ejBpsSAk",
                    "cropped_cover_url": "https://media.licdn.com/dms/image/v2/D563DAQHnelHpGO3tRQ/image-scale_191_1128/image-scale_191_1128/0/1728613234916/synapxe_cover?e=1764532800&v=beta&t=mLB475GiPcbCZIYM6sFRv4XLTwOqTM4SffgS_XJKTtc"
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "https://careers-public-healthtech-jobs.synapxe.sg/",
                    "linkedin": "https://www.linkedin.com/company/synapxe/",
                    "job_search": "https://www.linkedin.com/jobs/search?geoId=92000000&f_C=373987",
                    "sales_navigator": None,
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "Visit website",
                    "url": "https://www.synapxe.sg/",
                    "type": "VIEW_WEBSITE",
                    "visible": True
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [
                    "14370894",
                    "30975013",
                    "16482",
                    "14705571",
                    "18910822",
                    "23645",
                    "164351",
                    "14607710",
                    "6451760",
                    "52064779",
                    "325025",
                    "12977"
                ],
                "hashtags": [
                    "#inspiringtomorrowshealth",
                    "#synapxe",
                    "#healthtech"
                ],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "Bloomberg",
                "basic_info": {
                    "name": "Bloomberg",
                    "universal_name": "bloomberg",
                    "description": "Bloomberg is a global leader in business and financial information, delivering trusted data, news, and insights that bring transparency and efficiency, and fairness to markets. We help connect influential communities across the global financial ecosystem via reliable technology solutions that enable our customers to make more informed decisions and foster better collaboration.  \n \nWe challenge the status quo through constant innovation. We collaborate broadly because we know that other perspectives matter. We put our customers first, as a guiding beacon. And we believe doing the right thing – by our people, our clients, and our communities – is the best thing for our business.",
                    "website": "http://bloomberg.com/company",
                    "linkedin_url": "https://www.linkedin.com/company/bloomberg/",
                    "specialties": [
                        "Financial Data",
                        "Analysis",
                        "Software Engineering",
                        "Machine Learning",
                        "News",
                        "Media"
                    ],
                    "industries": [
                        "Financial Services"
                    ],
                    "is_verified": True,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "COMPANY",
                    "verification": {
                        "is_verified": True,
                        "last_verified_at": 1692144623176
                    }
                },
                "tagline": None,
                "phone": "",
                "company_urn": "2494",
                "stats": {
                    "employee_count": 25667,
                    "follower_count": 2112204,
                    "employee_count_range": {
                        "start": 10001,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {
                        "country": "US",
                        "state": "NY",
                        "city": "New York",
                        "postal_code": "10022",
                        "line1": "731 Lexington Ave.",
                        "line2": None,
                        "is_hq": True,
                        "description": None
                    },
                    "offices": [
                        {
                            "country": "JP",
                            "state": None,
                            "city": "Tokyo",
                            "postal_code": "1006321",
                            "line1": "Marunouchi Bldg. 21F",
                            "line2": "2-4-1 Marunochi, Chiyoda",
                            "is_hq": False,
                            "description": "Bloomberg Tokyo",
                            "region": "Tokyo"
                        },
                        {
                            "country": "GB",
                            "state": "UK",
                            "city": "London",
                            "postal_code": "EC4N 4TQ",
                            "line1": "3 Queen Victoria Street",
                            "line2": None,
                            "is_hq": False,
                            "description": None,
                            "region": "London"
                        },
                        {
                            "country": "US",
                            "state": "NY",
                            "city": "New York",
                            "postal_code": "10022",
                            "line1": "731 Lexington Ave.",
                            "line2": None,
                            "is_hq": True,
                            "description": None,
                            "region": "New York City Metropolitan Area"
                        },
                        {
                            "country": "US",
                            "state": "NJ",
                            "city": "Skillman",
                            "postal_code": "08558",
                            "line1": "100 Business Park Dr",
                            "line2": None,
                            "is_hq": False,
                            "description": None,
                            "region": "New York City Metropolitan Area"
                        }
                    ],
                    "geo_coordinates": {
                        "latitude": 35.69269,
                        "longitude": 139.709
                    }
                },
                "media": {
                    "logo_url": "https://media.licdn.com/dms/image/v2/C4D0BAQF0uyE7RGKDGg/company-logo_400_400/company-logo_400_400/0/1631374698859/bloomberg_lp_logo?e=1765411200&v=beta&t=UaKduROCfhNnHZoB90go1rxxBwy9irPfHsKWNMI9b2Q",
                    "cover_url": "https://media.licdn.com/dms/image/v2/D4E1BAQFsuITqUCRPzg/company-background_10000/company-background_10000/0/1696518311644/bloomberg_cover?e=1764532800&v=beta&t=mKL-4IrP2ouXIE_zz6T_MFO_tiK9IbmzBx_67fuUhcs",
                    "cropped_cover_url": "https://media.licdn.com/dms/image/v2/D4E3DAQEnE5R9TBlRug/image-scale_191_1128/image-scale_191_1128/0/1696518311741/bloomberg_cover?e=1764532800&v=beta&t=_Vce81VhxV1_GFidaKFK05ijpbBPjXO42iPUkKUUlak"
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "http://bloomberg.com/company",
                    "linkedin": "https://www.linkedin.com/company/bloomberg/",
                    "job_search": "https://www.linkedin.com/jobs/search?geoId=92000000&f_C=2494",
                    "sales_navigator": None,
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "Visit website",
                    "url": "https://www.bloomberg.com/company/?utm_medium=LI&utm_source=Social-o&utm_campaign=678145&tactic=678145",
                    "type": "VIEW_WEBSITE",
                    "visible": True
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [
                        "3507137",
                        "31769",
                        "3594627",
                        "100128240",
                        "88937381",
                        "5283957"
                    ],
                    "by_jobs": []
                },
                "similar_companies": [
                    "4697",
                    "10996666",
                    "4757",
                    "497017",
                    "5283957",
                    "98843233",
                    "1382",
                    "1421",
                    "4756",
                    "2282",
                    "65868452",
                    "5298"
                ],
                "hashtags": [
                    "#inclusioninaction",
                    "#impactinaction",
                    "#makeithappenhere"
                ],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "Matrixport Official",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "OCBC",
                "basic_info": {
                    "name": "OCBC Limited",
                    "universal_name": "ocbc",
                    "description": "Ocean Conference Business Centre\n\nWelcome to OCBC - Ocean Conference Business Centre – a well-designed, stylish multifunction venue suitable for fully serviced offices for long and short term lease, as well as for hosting seminars, conferences, networking events, teambuilding workshops, board meetings, and presentations. Overall, it is an exceptional venue for extraordinary events.  \n\nOCBC can offer your business fully furnished functioning offices, with a variety of complimentary and ancillary support services available on demand. The property is purposefully designed in a unique manner to offer independent business suites and/or common areas for workstation rental, all with natural light, common lobby, access to kitchen facilities, reception area, as well as a beautiful spacious garden, with access to a BBQ and a pool area.  \n\nAmong other things, OCBC can develop into a “one-stop-shop”, for entrepreneurs who aim to be free from all administrative tasks, thus allowing them to focus on efficiently running and expanding their business. \n",
                    "website": "http://www.ocbc.com.cy",
                    "linkedin_url": "https://www.linkedin.com/company/ocbc/",
                    "specialties": [],
                    "industries": [
                        "Executive Office"
                    ],
                    "is_verified": False,
                    "founded_info": {
                        "year": 2016,
                        "month": None,
                        "day": None
                    },
                    "page_type": "COMPANY",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": None,
                "phone": "",
                "company_urn": "18049816",
                "stats": {
                    "employee_count": 3,
                    "follower_count": 32,
                    "employee_count_range": {
                        "start": 2,
                        "end": 10
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {
                        "country": "CY",
                        "state": None,
                        "city": "Nicosia",
                        "postal_code": "CY-2402",
                        "line1": "11 Erechtiou Street",
                        "line2": "Engomi",
                        "is_hq": True,
                        "description": None
                    },
                    "offices": [
                        {
                            "country": "CY",
                            "state": None,
                            "city": "Nicosia",
                            "postal_code": "CY-2402",
                            "line1": "11 Erechtiou Street",
                            "line2": "Engomi",
                            "is_hq": True,
                            "description": None,
                            "region": "Nicosia"
                        }
                    ],
                    "geo_coordinates": {
                        "latitude": 35.174652,
                        "longitude": 33.36388
                    }
                },
                "media": {
                    "logo_url": "https://media.licdn.com/dms/image/v2/C560BAQEwqGrfh9xvoQ/company-logo_400_400/company-logo_400_400/0/1631311632599?e=1765411200&v=beta&t=g5V9kokBeCEmo8G_mzhZWkGMTyR_75t1ai0al2rYOek",
                    "cover_url": "https://media.licdn.com/dms/image/v2/C561BAQGevEtD_En2Fw/company-background_10000/company-background_10000/0/1584901018634?e=1764532800&v=beta&t=sLKcAzBun1xCKCp20llwQYQPNrykjrgzksh6ASh96sA",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "http://www.ocbc.com.cy",
                    "linkedin": "https://www.linkedin.com/company/ocbc/",
                    "job_search": "https://www.linkedin.com/jobs/search?geoId=92000000&f_C=18049816",
                    "sales_navigator": None,
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "Visit website",
                    "url": "http://www.ocbc.com.cy",
                    "type": "VIEW_WEBSITE",
                    "visible": True
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [
                    "35106",
                    "111728",
                    "1068",
                    "66256",
                    "711086",
                    "412023",
                    "3266802",
                    "165277",
                    "6883",
                    "11448",
                    "13233661"
                ],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "Firmus Technologies",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "Quantifind",
                "basic_info": {
                    "name": "Quantifind",
                    "universal_name": "quantifind",
                    "description": "Quantifind helps some of the world’s biggest banks catch money laundering and fraud. Quantifind also works with government agencies to use the same platform to uncover criminal networks and combat election tampering. Unlike other players in this space, Quantifind delivers results as software-as-a-service (SaaS) with consumer-grade user experiences. \n\nQuantifind is a data science technology company whose AI platform uncovers signals of risk across disparate and unstructured text sources. In financial crimes risk management, Quantifind’s solution uniquely combines internal financial institution data with public domain data to assess risk in the context of Know Your Customer (KYC), Customer Due Diligence (CDD), Fraud Risk Management, and Anti-Money Laundering (AML) processes. Today these compliance processes are burdened by ever-increasing regulatory responsibilities and an expectation of frictionless transactions. Legacy technologies demand increasingly more human resources as the operations expand; Quantifind’s solution offers a way to cut through the inefficiency and enhance effectiveness simultaneously.",
                    "website": "https://www.quantifind.com/",
                    "linkedin_url": "https://www.linkedin.com/company/quantifind/",
                    "specialties": [
                        "Big Data",
                        "Predictive Analytics",
                        "Unstructured Data",
                        "Text Analytics",
                        "Fraud Analytics",
                        "Media Data",
                        "anti-money laundering",
                        "fintech",
                        "regtech",
                        "machine learning",
                        "data science",
                        "law enforcement",
                        "anti-money laundering",
                        "KYC",
                        "compliance",
                        "financial crimes investigation",
                        "AML",
                        "financial crimes",
                        "fincrime"
                    ],
                    "industries": [
                        "Computer Software"
                    ],
                    "is_verified": True,
                    "founded_info": {
                        "year": 2009,
                        "month": None,
                        "day": None
                    },
                    "page_type": "COMPANY",
                    "verification": {
                        "is_verified": True,
                        "last_verified_at": 1718051248908
                    }
                },
                "tagline": "Our AI-powered Risk Intelligence helps organizations detect and mitigate risk with greater accuracy and speed.",
                "phone": "",
                "company_urn": "1321033",
                "stats": {
                    "employee_count": 100,
                    "follower_count": 7575,
                    "employee_count_range": {
                        "start": 51,
                        "end": 200
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {
                        "country": "US",
                        "state": "California",
                        "city": "Palo Alto",
                        "postal_code": "94301",
                        "line1": "444 High St",
                        "line2": None,
                        "is_hq": True,
                        "description": "HQ"
                    },
                    "offices": [
                        {
                            "country": "US",
                            "state": "California",
                            "city": "Palo Alto",
                            "postal_code": "94301",
                            "line1": "444 High St",
                            "line2": None,
                            "is_hq": True,
                            "description": "HQ",
                            "region": "Palo Alto"
                        }
                    ],
                    "geo_coordinates": {
                        "latitude": 37.39271,
                        "longitude": -122.042
                    }
                },
                "media": {
                    "logo_url": "https://media.licdn.com/dms/image/v2/D560BAQFLJi6zNFdfPQ/company-logo_400_400/company-logo_400_400/0/1709588723817/quantifind_logo?e=1765411200&v=beta&t=TPpYt5NVw5wqhwd19SQbaj65Sj5S14MJZMuI1jgz7Y0",
                    "cover_url": "https://media.licdn.com/dms/image/v2/D4E1BAQFQvw7nffU0Fw/company-background_10000/company-background_10000/0/1706640037263/quantifind_cover?e=1764532800&v=beta&t=OhtXSOuFHsrHfIFsV4nEIPxjbGKT8TLy6bLsPI1fOSY",
                    "cropped_cover_url": "https://media.licdn.com/dms/image/v2/D4E3DAQGSzwAZiQyyHw/image-scale_191_1128/image-scale_191_1128/0/1706640037503/quantifind_cover?e=1764532800&v=beta&t=fpr4pnywzsVWSPFDGFWlbyh5O0TkFLurC99Kyeled8k"
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "https://www.quantifind.com/",
                    "linkedin": "https://www.linkedin.com/company/quantifind/",
                    "job_search": "https://www.linkedin.com/jobs/search?geoId=92000000&f_C=1321033",
                    "sales_navigator": None,
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "Learn more",
                    "url": "https://www.quantifind.com",
                    "type": "LEARN_MORE",
                    "visible": True
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [
                        "92785197"
                    ],
                    "by_jobs": []
                },
                "similar_companies": [
                    "1441",
                    "1833",
                    "1586",
                    "33275761",
                    "76161023",
                    "571385",
                    "1035",
                    "11193683",
                    "150573",
                    "14389",
                    "15197985",
                    "7596960"
                ],
                "hashtags": [
                    "#regtech",
                    "#financialcrime",
                    "#amlcompliance"
                ],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            },
            {
                "input_identifier": "Swire Shipping",
                "basic_info": {
                    "name": "",
                    "universal_name": "",
                    "description": "",
                    "website": "",
                    "linkedin_url": "",
                    "specialties": [],
                    "industries": [],
                    "is_verified": False,
                    "founded_info": {
                        "year": None,
                        "month": None,
                        "day": None
                    },
                    "page_type": "",
                    "verification": {
                        "is_verified": False,
                        "last_verified_at": None
                    }
                },
                "tagline": "",
                "phone": "",
                "company_urn": "",
                "stats": {
                    "employee_count": None,
                    "follower_count": None,
                    "employee_count_range": {
                        "start": None,
                        "end": None
                    },
                    "student_count": None
                },
                "locations": {
                    "headquarters": {},
                    "offices": [],
                    "geo_coordinates": {
                        "latitude": None,
                        "longitude": None
                    }
                },
                "media": {
                    "logo_url": "",
                    "cover_url": "",
                    "cropped_cover_url": ""
                },
                "funding": {
                    "total_rounds": None,
                    "latest_round": {
                        "type": "",
                        "date": None,
                        "url": "",
                        "investors_count": None
                    },
                    "crunchbase_url": ""
                },
                "links": {
                    "website": "",
                    "linkedin": "",
                    "job_search": "",
                    "sales_navigator": "",
                    "crunchbase": ""
                },
                "call_to_action": {
                    "text": "",
                    "url": "",
                    "type": "",
                    "visible": False
                },
                "affiliated_companies": {
                    "by_employees": [],
                    "showcases": [],
                    "by_jobs": []
                },
                "similar_companies": [],
                "hashtags": [],
                "corporate_relationships": {
                    "parent_company": "",
                    "acquirer_company": ""
                }
            }
        ]

        if not items:
            print(f"  No company data found on Apify")
            return ''

        # Map company names to overviews
        company_map = {}
        for item in items:
            company_name = item.get('input_identifier', '')
            if company_name:
                company_name = company_name.strip()
            description = item.get('basic_info', {}).get('description', '')
            if description:
                description = description.strip()

            if company_name and description:
                company_map[company_name] = description

        print(f"Successfully fetched {len(company_map)}/{len(company_names)} company overviews")
        return company_map

    except Exception as e:
        print(f"Error in bulk Apify fetch: {e}")
        return {}


ITA_SEARCH_URL = 'https://www.linkedin.com/jobs/search/?currentJobId=4312026327&f_E=3%2C4&f_TPR=r604800&f_WT=2&geoId=103350119&keywords=(software%20OR%20%22data%20Engineer%22%20OR%20Backend%20OR%20%22back%20End%22%20OR%20%22ai%20Engineer%22%20OR%20%22aritifical%20Inteligence%20Engineer%22%20OR%20%22ml%20Engineer%22)%20AND%20NOT%20(%22php%22%20OR%20%22full%20Stack%22%20OR%20%22kubernetes%22%20OR%20%22frontend%22%20OR%20%22android%22%20OR%20%22angular%22%20OR%20%22network%22%20OR%20%22manager%22%20OR%20%22research%22)&origin=JOB_SEARCH_PAGE_LOCATION_HISTORY&refresh=True&sortBy=R'
RM_SEARCH_URL = 'https://www.linkedin.com/jobs/search/?currentJobId=4313461130&f_E=3%2C4&f_TPR=r604800&f_WT=1%2C2%2C3&geoId=106398949&keywords=(software%20OR%20%22data%20Engineer%22%20OR%20Backend%20OR%20%22back%20End%22%20OR%20%22ai%20Engineer%22%20OR%20%22aritifical%20Inteligence%20Engineer%22%20OR%20%22ml%20Engineer%22)%20AND%20NOT%20(%22php%22%20OR%20%22full%20Stack%22%20OR%20%22kubernetes%22%20OR%20%22frontend%22%20OR%20%22android%22%20OR%20%22angular%22%20OR%20%22network%22%20OR%20%22manager%22%20OR%20%22research%22)&origin=JOB_SEARCH_PAGE_JOB_FILTER&refresh=True&sortBy=R'
SRB_SEARCH_URL = 'https://www.linkedin.com/jobs/search/?currentJobId=4288592065&f_E=3%2C4&f_TPR=r604800&f_WT=2&geoId=101855366&keywords=(software%20OR%20%22data%20Engineer%22%20OR%20Backend%20OR%20%22back%20End%22%20OR%20%22ai%20Engineer%22%20OR%20%22aritifical%20Inteligence%20Engineer%22%20OR%20%22ml%20Engineer%22)%20AND%20NOT%20(%22php%22%20OR%20%22full%20Stack%22%20OR%20%22kubernetes%22%20OR%20%22frontend%22%20OR%20%22android%22%20OR%20%22angular%22%20OR%20%22network%22%20OR%20%22manager%22%20OR%20%22research%22)&origin=JOB_SEARCH_PAGE_LOCATION_AUTOCOMPLETE&refresh=True&sortBy=R'
EU_SEARCH_URL = 'https://www.linkedin.com/jobs/search/?currentJobId=4312048028&f_E=3%2C4&f_TPR=r604800&f_WT=2&geoId=91000000&keywords=(software%20OR%20%22data%20Engineer%22%20OR%20Backend%20OR%20%22back%20End%22%20OR%20%22ai%20Engineer%22%20OR%20%22aritifical%20Inteligence%20Engineer%22%20OR%20%22ml%20Engineer%22)%20AND%20NOT%20(%22php%22%20OR%20%22full%20Stack%22%20OR%20%22kubernetes%22%20OR%20%22frontend%22%20OR%20%22android%22%20OR%20%22angular%22%20OR%20%22network%22%20OR%20%22manager%22%20OR%20%22research%22)&origin=JOB_SEARCH_PAGE_SEARCH_BUTTON&refresh=True&sortBy=R'
THAI_SEARCH_URL = 'https://www.linkedin.com/jobs/search/?currentJobId=4316904406&f_E=3%2C4&f_TPR=r604800&f_WT=1%2C3%2C2&geoId=105146118&keywords=(software%20OR%20%22data%20Engineer%22%20OR%20Backend%20OR%20%22back%20End%22%20OR%20%22ai%20Engineer%22%20OR%20%22aritifical%20Inteligence%20Engineer%22%20OR%20%22ml%20Engineer%22)%20AND%20NOT%20(%22php%22%20OR%20%22full%20Stack%22%20OR%20%22kubernetes%22%20OR%20%22frontend%22%20OR%20%22android%22%20OR%20%22angular%22%20OR%20%22network%22%20OR%20%22manager%22%20OR%20%22research%22)&origin=JOB_SEARCH_PAGE_JOB_FILTER&refresh=True&sortBy=R'
SNGPR_SEARCH_URL = 'https://www.linkedin.com/jobs/search/?currentJobId=4317574441&f_E=3%2C4&f_TPR=r604800&f_WT=1%2C3%2C2&geoId=102454443&keywords=(software%20OR%20%22data%20Engineer%22%20OR%20Backend%20OR%20%22back%20End%22%20OR%20%22ai%20Engineer%22%20OR%20%22aritifical%20Inteligence%20Engineer%22%20OR%20%22ml%20Engineer%22)%20AND%20NOT%20(%22php%22%20OR%20%22full%20Stack%22%20OR%20%22kubernetes%22%20OR%20%22frontend%22%20OR%20%22android%22%20OR%20%22angular%22%20OR%20%22network%22%20OR%20%22manager%22%20OR%20%22research%22)&origin=JOB_SEARCH_PAGE_LOCATION_AUTOCOMPLETE&refresh=True&sortBy=R'
Philippines_SEARCH_URL = 'https://www.linkedin.com/jobs/search/?currentJobId=4316912580&f_E=3%2C4&f_TPR=r604800&f_WT=1%2C3%2C2&geoId=103121230&keywords=(software%20OR%20%22data%20Engineer%22%20OR%20Backend%20OR%20%22back%20End%22%20OR%20%22ai%20Engineer%22%20OR%20%22aritifical%20Inteligence%20Engineer%22%20OR%20%22ml%20Engineer%22)%20AND%20NOT%20(%22php%22%20OR%20%22full%20Stack%22%20OR%20%22kubernetes%22%20OR%20%22frontend%22%20OR%20%22android%22%20OR%20%22angular%22%20OR%20%22network%22%20OR%20%22manager%22%20OR%20%22research%22)&origin=JOB_SEARCH_PAGE_SEARCH_BUTTON&refresh=True&sortBy=R'
SEARCH_URLS = [ITA_SEARCH_URL, RM_SEARCH_URL, SRB_SEARCH_URL, EU_SEARCH_URL, THAI_SEARCH_URL, SNGPR_SEARCH_URL,
               Philippines_SEARCH_URL]

SHEET_HEADER = [
    'Company Name', 'Job Title', 'Location', 'Location Priority', 'Job Description', 'Job URL', 'Company URL',
    'Company overview', 'Sustainable company',
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
    Return priority score for sorting:
    1 = Italy
    2 = European Union
    3 = Serbia
    4 = Spain
    5 = Everything else
    """
    location_lower = location.lower()

    if 'italy' in location_lower or 'italia' in location_lower:
        return 1
    elif 'european union' in location_lower:
        return 2
    elif 'serbia' in location_lower:
        return 3
    elif 'spain' in location_lower or 'españa' in location_lower:
        return 4
    else:
        return 5


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
    
    # Check cache first for all companies
    remaining_companies = []
    for data in companies_data:
        name = data['company_name']
        if sheet:
            cached_result = get_sustainability_from_sheet(name, sheet)
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

    print(f"Checking sustainability in bulk for {len(remaining_companies)} companies...")

    # Try with primary key, then backup key
    api_keys = [
        ('primary', os.getenv("GEMINI_API_KEY")),
        ('backup', os.getenv("BACKUP_GEMINI_API_KEY"))
    ]

    for key_name, api_key in api_keys:
        if not api_key:
            continue

        try:
            client = genai.Client(api_key=api_key)
            
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
- Renewable energy, clean tech, environmental protection
- Healthcare, medical research, medical devices
- Education, academic institutions, learning platforms

Return is_sustainable: false for:
- Weapons, arms, defense contractors, military equipment
- Fossil fuels, oil & gas, petroleum, coal
- Tobacco, cigarettes, vaping products
- Gambling, casinos, betting
- Predatory lending, payday loans
- Harmful addictions or exploitative industries
- Providing services to any companies/industries above

Return is_sustainable: false for neutral industries (banking, tech, finance, insurance, investment) UNLESS they have an explicit and primary sustainability/ESG/impact focus.

You must respond with ONLY a JSON dictionary where keys are the exact company names provided above and values are objects with "is_sustainable" (boolean) and "reasoning" (string).
Example:
{{
  "Company A": {{"is_sustainable": true, "reasoning": "Solar energy manufacturer"}},
  "Company B": {{"is_sustainable": false, "reasoning": "Defense contractor"}}
}}"""

            rate_limit()
            response = client.models.generate_content(
                model='gemini-2.0-flash-exp',
                contents=prompt
            )

            response_text = response.text.strip()
            cleaned = response_text.replace('```json', '').replace('```', '').strip()
            batch_results = json.loads(cleaned)

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
                        print(f"  ⚠️  Bulk Sustainability check ({key_name} key): {name} -> False")
                        print(f"      Reason: {reason}")
                    else:
                        print(f"  ✓  Bulk Sustainability check ({key_name} key): {name} -> True")
                else:
                    print(f"Warning: Result for {name} missing from bulk API response")
                    results[name] = {'is_sustainable': None, 'reasoning': 'Missing from API response'}

            return results

        except Exception as e:
            print(f"Error with {key_name} key in bulk sustainability check: {e}")
            if key_name == 'primary':
                print(f"  → Trying backup key...")
                continue
            else:
                # If both failed, we'll mark them as None
                for data in remaining_companies:
                    results[data['company_name']] = {'is_sustainable': None, 'reasoning': 'API Error'}
                return results

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
        cached_result = get_sustainability_from_sheet(company_name, sheet)
        if cached_result is not None:
            # We already have a result in the sheet, no need to print anything or call API
            return cached_result == 'TRUE'

    if not company_overview or len(company_overview) < 50:
        return None

    print(f"Checking sustainability for: {company_name}")

    # Try with primary key, then backup key
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
                print(f"Warning: Both API keys not found, returning None")
                return None

        try:
            # Configure Gemini client
            client = genai.Client(api_key=api_key)

            # Prepare the prompt
            prompt = f"""Analyze if this company works on something sustainability-oriented:

Company Name: {company_name}

Company Overview: {company_overview}

Job Description: {job_description[:1000] if job_description else "Not available"}

Return True *ONLY* for companies in sustainable industries like:
- Renewable energy, *clean* tech
- Healthcare and medical 
- Education and learning

Return False for:
- Weapons, arms, defense contractors, military equipment
- Fossil fuels, oil & gas, petroleum, coal
- Tobacco, cigarettes, vaping products
- Gambling, casinos, betting
- Predatory lending, payday loans
- Harmful addictions or exploitative industries
- Providing services to any companies/industries above

Return False for neutral industries (banking, tech, finance, insurance, investment) UNLESS they have explicit sustainability/ESG/impact investing focus.

You must respond with ONLY a JSON object in this exact format:
{{
  "is_sustainable": True or False,
  "reasoning": "brief explanation"
}}"""

            # Call Gemini with rate limiting protection
            rate_limit()
            response = client.models.generate_content(
                model='gemini-2.0-flash-exp',
                contents=prompt
            )

            # Parse JSON response
            response_text = response.text.strip()
            # Remove markdown code blocks if present
            cleaned = response_text.replace('```json', '').replace('```', '').strip()
            result = json.loads(cleaned)

            is_sustainable = result.get("is_sustainable", True)
            reasoning = result.get("reasoning", "No reasoning provided")

            if not is_sustainable:
                print(f"  ⚠️  Sustainability check ({key_name} key): {company_name} -> False")
                print(f"      Reason: {reasoning}")
            else:
                print(f"  ✓  Sustainability check ({key_name} key): {company_name} -> True")

            return is_sustainable

        except Exception as e:
            if key_name == 'primary':
                print(f"Error with {key_name} key for {company_name}: {e}")
                print(f"  → Trying backup key...")
                continue  # Try backup key
            else:
                print(f"Error with {key_name} key for {company_name}: {e}")
                print(f"  → Both keys failed, returning None")
                return None

    # If both keys failed
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

    # Phase 1: Collect unique companies that need checking
    for row in all_rows:
        # Skip if already processed or filtered out
        if row.get('Fit score') in ['Poor fit', 'Very poor fit', 'Moderate fit', 'Questionable fit']:
            continue

        if row.get('Applied') == 'TRUE' or row.get('Bad analysis') == 'TRUE' or row.get(
                'Job posting expired') == 'TRUE':
            continue

        # Skip if already has definitive sustainable company value
        sustainable_value = row.get('Sustainable company', '').strip()
        if sustainable_value in ['TRUE', 'FALSE']:
            continue

        # Skip if no company overview yet
        company_overview = row.get('Company overview', '').strip()
        if not company_overview:
            continue

        company_name = row.get('Company Name', '').strip()
        if not company_name:
            continue

        if company_name in companies_seen:
            continue

        companies_seen.add(company_name)
        companies_to_check.append({
            'company_name': company_name,
            'company_overview': company_overview,
            'job_description': row.get('Job Description', '')
        })

    if not companies_to_check:
        print("No companies need sustainability validation.")
        return 0

    print(f"Found {len(companies_to_check)} companies to check for sustainability.")

    # Phase 2: Process in batches of 10
    batch_size = 10
    total_processed = 0

    for i in range(0, len(companies_to_check), batch_size):
        batch = companies_to_check[i:i + batch_size]
        print(f"\nProcessing batch {i // batch_size + 1} ({len(batch)} companies)...")

        batch_results = is_sustainable_company_bulk(batch, sheet=sheet)

        # Prepare bulk updates for the sheet
        bulk_updates = []
        
        # Get column indices
        sc_col = gspread.utils.rowcol_to_a1(1, get_column_index(sheet, 'Sustainable company'))[0]
        fs_col = gspread.utils.rowcol_to_a1(1, get_column_index(sheet, 'Fit score'))[0]
        fse_col = gspread.utils.rowcol_to_a1(1, get_column_index(sheet, 'Fit score enum'))[0]
        ja_col = gspread.utils.rowcol_to_a1(1, get_column_index(sheet, 'Job analysis'))[0]

        for company_name, result in batch_results.items():
            is_sustainable = result['is_sustainable']
            reasoning = result['reasoning']

            if is_sustainable is None:
                continue

            sustainability_value = 'TRUE' if is_sustainable else 'FALSE'
            
            # Find all rows with this company name and prepare updates
            for idx, row in enumerate(all_rows, start=2):
                if row.get('Company Name', '').strip().lower() == company_name.lower():
                    # Sustainability field
                    bulk_updates.append({
                        'range': f'{sc_col}{idx}',
                        'values': [[sustainability_value]]
                    })

                    # If unsustainable, mark as Very poor fit
                    if not is_sustainable and not row.get('Fit score'):
                        bulk_updates.extend([
                            {
                                'range': f'{fs_col}{idx}',
                                'values': [['Very poor fit']]
                            },
                            {
                                'range': f'{fse_col}{idx}',
                                'values': [[fit_score_to_enum('Very poor fit')]]
                            },
                            {
                                'range': f'{ja_col}{idx}',
                                'values': [[f'Unsustainable company: {reasoning}']]
                            }
                        ])
            
            total_processed += 1

        # Execute bulk update for the batch
        if bulk_updates:
            # Group updates by range to minimize API calls if possible, 
            # but batch_update already handles a list of range/values.
            # We should probably still chunk them if there are too many.
            chunk_size = 100
            for j in range(0, len(bulk_updates), chunk_size):
                chunk = bulk_updates[j:j + chunk_size]
                sheet.batch_update(chunk, value_input_option='USER_ENTERED')
                time.sleep(1) # Small delay between chunks

    print(f"\nSustainability validation completed. Processed {total_processed} companies.")
    return total_processed


def setup_driver():
    """Initialize and return a headless Chrome driver"""
    from selenium.webdriver.chrome.options import Options
    
    options = Options()
    # options.add_argument('--headless=new')
    from selenium import webdriver
    
    return webdriver.Chrome(options=options)


def setup_spreadsheet(client, user_name):
    """
    Open or create the spreadsheet.
    If client is None, uses local CSV storage instead of Google Sheets.
    """
    sheet_name = f"{user_name} LinkedIn Job Alerts"
    
    # Check if using local storage (client is None)
    if client is None:
        from local_storage import LocalSheet
        csv_path = f"./local_data/jobs.csv"
        sheet = LocalSheet(csv_path, SHEET_HEADER)
        print(f"Using local CSV storage: {csv_path}")
        return sheet
    
    # Use Google Sheets (existing behavior)
    try:
        sheet = client.open(sheet_name).sheet1
        return sheet
    except:
        # Create spreadsheet if it doesn't exist
        spreadsheet = client.create(sheet_name)
        sheet = spreadsheet.sheet1
        sheet.append_row(SHEET_HEADER)
        print("Created new spreadsheet: LinkedIn Job Alerts")
        return sheet


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


def update_cell(sheet, row_idx: int, column_name: str, value: str):
    """Helper to update a cell by column name"""
    col_idx = get_column_index(sheet, column_name)
    sheet.update_cell(row_idx, col_idx, value)


def get_column_index(sheet, column_name: str) -> int | Any:
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


def get_sustainability_from_sheet(company_name: str, sheet) -> str | None:
    """
    Check if sustainability status is already known for a company.

    Returns:
        'TRUE', 'FALSE', or None if not found
    """
    all_rows = sheet.get_all_records()
    for row in all_rows:
        if row.get('Company Name', '').strip() == company_name:
            sustainable = row.get('Sustainable company', '').strip()
            if sustainable in ['TRUE', 'FALSE']:
                return sustainable
    return None


def fetch_jobs_via_apify(search_url: str) -> list[dict]:
    """
    Fetch jobs from LinkedIn via Apify Actor using parameters extracted from search_url.
    """
    from main import APIFY_API_TOKEN
    
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
    
    print(f"Running Apify Actor for keywords: '{keywords}' in location: '{location}'")
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
        print(f"Error running Apify Actor: {e}")
        return []
