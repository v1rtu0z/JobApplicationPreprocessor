from linkedin_scraper import JobSearch, Job
from typing import List
from time import sleep

from selenium.webdriver.common.by import By


class CustomJobSearch(JobSearch):
    """Extended JobSearch class that can scrape jobs from a direct URL"""

    def scroll_into_view(self, element):
        """Scroll an element into view using JavaScript"""
        self.driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", element)
        sleep(0.5)  # Give it a moment to scroll
        
    def scroll_element_to_bottom(self, element, pause_time=1):
        """Scroll a specific element (with its own scrollbar) to the bottom"""
        last_height = self.driver.execute_script("return arguments[0].scrollHeight", element)

        while True:
            # Scroll the element to bottom
            self.driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", element)
            sleep(pause_time)

            # Calculate new scroll height and compare with last scroll height
            new_height = self.driver.execute_script("return arguments[0].scrollHeight", element)
            if new_height == last_height:
                break
            last_height = new_height

    def scrape_from_url(self, url: str) -> List:
        """
        Navigate to a LinkedIn jobs URL and scrape all visible job listings

        Args:
            url: The full LinkedIn jobs URL to scrape

        Returns:
            List of Job objects
        """
        # Navigate to the URL
        self.driver.get(url)
        sleep(2)  # Wait for initial page load

        # Find the job listing container (the scrollable <ul> element)
        job_listing = None

        try:
            focused_list_element = self.wait_for_element_to_load(name="job-card-list")
            job_listing = focused_list_element.find_element(By.XPATH, "./ancestor::ul[1]")
        except:
            try:
                # Try to find the jobs list container directly
                job_listing = self.wait_for_element_to_load(name="scaffold-layout__list-container")
            except:
                try:
                    # Alternative: find by the list itself
                    job_listing = self.driver.find_element(By.CLASS_NAME, "jobs-search-results-list")
                except:
                    try:
                        # Another alternative: find the scrollable container
                        job_listing = self.driver.find_element(By.CSS_SELECTOR, "ul.scaffold-layout__list-container")
                    except:
                        print(f"Could not find job listing container at {url}")
                        return []

        if not job_listing:
            print(f"Could not find job listing container at {url}")
            return []

        # Scroll the job listing container to load all jobs
        print("Scrolling to load all jobs...")
        self.scroll_element_to_bottom(job_listing, pause_time=2)
        print("Finished scrolling")

        # Wait a bit for any final jobs to load
        sleep(2)

        # Scrape all job cards
        job_results = []

        # Try multiple possible selectors for job list items
        job_card_selectors = [
            ("CLASS_NAME", "jobs-search-results__list-item"),
            ("CLASS_NAME", "scaffold-layout__list-item"),
            ("CSS_SELECTOR", "li.jobs-search-results__list-item"),
            ("CSS_SELECTOR", "li[class*='job']"),
            ("CLASS_NAME", "job-card-list"),
            ("CLASS_NAME", "jobs-job-board-list__item"),
        ]

        for selector_type, selector_value in job_card_selectors:
            try:
                if selector_type == "CLASS_NAME":
                    job_cards = job_listing.find_elements(By.CLASS_NAME, selector_value)
                else:
                    job_cards = job_listing.find_elements(By.CSS_SELECTOR, selector_value)

                if job_cards:
                    print(f"Found {len(job_cards)} job cards")
                    for i, job_card in enumerate(job_cards):
                        try:
                            self.scroll_into_view(job_card)

                            job = self.scrape_job_card(job_card)
                            job_results.append(job)
                            print(f"Scraped job {i + 1}/{len(job_cards)}: {job.job_title}")
                        except Exception as e:
                            print(f"Error scraping job card {i + 1}: {e}")
                            continue
                    break  # If we found jobs with this selector, stop trying others
            except Exception as e:
                print(f"Selector {selector_value} failed: {e}")
                continue

        if not job_results:
            print("No jobs found with any selector. Printing available elements for debugging:")
            try:
                all_li = job_listing.find_elements(By.TAG_NAME, "li")
                print(f"Found {len(all_li)} <li> elements")
                if all_li:
                    print(f"First <li> classes: {all_li[0].get_attribute('class')}")
            except Exception as e:
                print(f"Debug failed: {e}")

        return job_results


    def scrape_job_card(self, base_element) -> Job:
        job_div = self.wait_for_element_to_load(By.CLASS_NAME, "job-card-list__title--link", base=base_element)
        job_title = job_div.text.strip()
        linkedin_url = job_div.get_attribute("href")
        company = base_element.find_element(By.CLASS_NAME, "artdeco-entity-lockup__subtitle").text
        location = base_element.find_element(By.CLASS_NAME, "job-card-container__metadata-wrapper").text
        job = Job(linkedin_url=linkedin_url, job_title=job_title, company=company, location=location, scrape=False, driver=self.driver)
        return job