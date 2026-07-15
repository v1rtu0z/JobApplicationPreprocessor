"""Environment variables and constants used across the main pipeline."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Batch sizes
BULK_FILTER_BATCH_SIZE = 100
COMPANY_OVERVIEW_BATCH_SIZE = 1000
JOB_DESCRIPTION_BATCH_SIZE = 100
SUSTAINABILITY_CHECK_BATCH_SIZE = 10
BULK_UPDATE_CHUNK_SIZE = 100
ANALYSIS_BATCH_SIZE = 5
JD_FIT_BATCH_SIZE = 12
JD_FIT_BATCH_MAX_RETRIES = 4
JD_FIT_MAX_CONSECUTIVE_BATCH_FAILURES = 8
JD_FIT_IDLE_SLEEP_SECONDS = 15

# Env
APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN")
email_address = os.getenv("EMAIL_ADDRESS")
linkedin_password = os.getenv("LINKEDIN_PASSWORD")
CHECK_SUSTAINABILITY = os.getenv("CHECK_SUSTAINABILITY", "false").lower() == "true"
CRAWL_LINKEDIN = os.getenv("CRAWL_LINKEDIN", "false").lower() == "true"
SKIP_JD_FETCH = os.getenv("SKIP_JD_FETCH", "false").lower() == "true"
SKIP_APIFY_COLLECTION = os.getenv("SKIP_APIFY_COLLECTION", "false").lower() == "true"

# Dashboard
DASHBOARD_URL = "http://localhost:8501"
DASHBOARD_LAUNCH_DELAY_SEC = 2.5

# Sleep / rate limit
BASE_SLEEP_INTERVAL_SECONDS = 3600  # 1 hour between checks when no work
GEMINI_RATE_LIMIT_SHORT_WAIT_SECONDS = 300  # 5 minutes
MANUAL_CO_PROMPT_SLEEP_SECONDS = 300  # 5 minutes between manual-CO prompt checks

# Activity log (must match dashboard.py)
ACTIVITY_LOG_PATH = Path("local_data") / "activity.log"
