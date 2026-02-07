"""Setup, shutdown handlers, processing cycle, and main loop."""

import os
import time
from datetime import datetime

from dotenv import load_dotenv
import utils
from utils import (
    get_user_name,
    setup_spreadsheet,
    get_column_index,
    validate_sustainability_for_unprocessed_jobs,
)

from .constants import (
    CRAWL_LINKEDIN,
    SKIP_JD_FETCH,
    CHECK_SUSTAINABILITY,
    GEMINI_RATE_LIMIT_SHORT_WAIT_SECONDS,
)
from .logging_dashboard import _setup_log_capture, _launch_dashboard_once
from .filtering import _build_company_overview_cache
from .bulk_ops import bulk_filter_collected_jobs, bulk_fetch_missing_job_descriptions, fetch_company_overviews
from .collection import (
    process_collection_phase,
    process_new_jobs_pipeline,
    process_linkedin_collection,
)
from .analysis import analyze_all_jobs
from .resumes import process_resumes_and_cover_letters
from config import _get_job_filters, _save_job_filters, CONFIG_FILE


def setup_and_validate():
    """Perform initial setup validation and load environment variables."""
    load_dotenv()
    critical_vars = ['SERVER_URL', 'API_KEY', 'GEMINI_API_KEY']
    missing_vars = [v for v in critical_vars if not os.getenv(v)]
    if missing_vars:
        print(f"CRITICAL ERROR: Missing environment variables: {', '.join(missing_vars)}")
        print("Please check your .env file. Refer to .env.example and setup_guide.md.")
        return False
    return True


def setup_signal_handlers():
    """Set up signal handlers for graceful shutdown. Returns shutdown_requested dict."""
    import signal

    shutdown_requested = {'flag': False}

    def signal_handler(signum, frame):
        print("\n\nShutdown signal received. Finishing current operation and exiting...")
        shutdown_requested['flag'] = True

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    if hasattr(signal, 'SIGBREAK'):
        signal.signal(signal.SIGBREAK, signal_handler)

    return shutdown_requested


def initialize_job_preferences():
    """Ensure job_preferences.yaml exists."""
    if not os.path.exists(CONFIG_FILE):
        import shutil
        example_file = 'job_preferences.yaml.example'
        if os.path.exists(example_file):
            print(f"Creating {CONFIG_FILE} from example...")
            shutil.copy(example_file, CONFIG_FILE)
        else:
            print(f"Creating default {CONFIG_FILE}...")
            filters = _get_job_filters()
            _save_job_filters(filters)


def initialize_storage(user_name: str):
    """Initialize local SQLite storage. Returns sheet (db)."""
    print("\n" + "!" * 60)
    print("Using local storage mode (SQLite database).")
    print("Note: To view your jobs, use the Streamlit dashboard: streamlit run dashboard.py")
    print("!" * 60 + "\n")
    from local_storage import ensure_local_directories
    ensure_local_directories()
    sheet = setup_spreadsheet(user_name)
    return sheet


def check_incomplete_jobs(sheet) -> bool:
    """Return True if there are jobs with missing data that can be fetched."""
    all_rows = sheet.get_all_records()
    for row in all_rows:
        if not row.get('Job Title') or row.get('Applied') == 'TRUE' or row.get('Bad analysis') == 'TRUE' or row.get('Job posting expired') == 'TRUE':
            continue
        needs_jd = not row.get('Job Description') and CRAWL_LINKEDIN
        needs_co = not row.get('Company overview') and utils.apify_state.is_available()
        can_get_jd = row.get('Job Description') or CRAWL_LINKEDIN
        can_get_co = row.get('Company overview') or utils.apify_state.is_available()
        needs_analysis = not row.get('Fit score') and can_get_jd and can_get_co
        if needs_jd or needs_co or needs_analysis:
            return True
    return False


def _handle_sleep_logic(has_incomplete_jobs, progress_made_in_cycle, last_check_time,
                        current_sleep_interval, base_sleep_interval, shutdown_requested):
    """Handle sleep with exponential backoff or short wait on Gemini rate limit. Returns new interval."""
    time_since_last_check = time.time() - last_check_time
    should_sleep = (not has_incomplete_jobs or (not progress_made_in_cycle and last_check_time > 0)) and time_since_last_check < current_sleep_interval

    if not progress_made_in_cycle and utils.gemini_rate_limit_hit and has_incomplete_jobs:
        sleep_time = GEMINI_RATE_LIMIT_SHORT_WAIT_SECONDS
        print(f"\nGemini rate limit was hit. Short wait of {sleep_time / 60:.1f} minutes before retry...")
        print("(Press Ctrl+C to interrupt and exit)")
        sleep_chunk = 5
        slept = 0
        while slept < sleep_time and not shutdown_requested['flag']:
            time.sleep(min(sleep_chunk, sleep_time - slept))
            slept += sleep_chunk
        return current_sleep_interval

    if should_sleep:
        sleep_time = current_sleep_interval - time_since_last_check
        if not has_incomplete_jobs:
            print(f"All jobs complete. Sleeping for {sleep_time / 60:.1f} minutes until next check...")
        else:
            print(f"No progress made on incomplete jobs. Sleeping for {sleep_time / 60:.1f} minutes to avoid tight loop (exponential backoff: {current_sleep_interval / 3600:.1f}h)...")
        print("(Press Ctrl+C to interrupt and exit)")
        sleep_chunk = 5
        slept = 0
        while slept < sleep_time and not shutdown_requested['flag']:
            time.sleep(min(sleep_chunk, sleep_time - slept))
            slept += sleep_chunk

        if not progress_made_in_cycle and last_check_time > 0:
            new_interval = current_sleep_interval * 2
            if new_interval > 86400:
                new_interval = 86400
            print(f"Exponential backoff: Next sleep interval will be {new_interval / 3600:.1f}h")
            return new_interval

        if shutdown_requested['flag']:
            print("\nShutdown requested during sleep, exiting...")

    return current_sleep_interval


def _run_processing_cycle(sheet, resume_json, company_overview_cache, shutdown_requested):
    """Run a single processing cycle. Returns True if any progress was made."""
    utils.reset_gemini_rate_limit_flag()
    progress_made_in_cycle = False

    if not SKIP_JD_FETCH:
        if bulk_fetch_missing_job_descriptions(sheet) > 0:
            progress_made_in_cycle = True

    # Company overview fetch uses public LinkedIn company pages (no login). Run every cycle.
    if fetch_company_overviews(sheet, company_overview_cache) > 0:
        progress_made_in_cycle = True

    collected_jobs, total_new_jobs, _ = process_collection_phase(
        sheet, resume_json, shutdown_requested, company_overview_cache
    )

    if total_new_jobs > 0:
        progress_made_in_cycle = True

    if collected_jobs:
        print(f"\nProcessing {len(collected_jobs)} total new jobs collected in this cycle...")
        if process_new_jobs_pipeline(sheet, resume_json, collected_jobs, company_overview_cache):
            progress_made_in_cycle = True

    print("\nFinalizing processing cycle (processing leftover batches)...")
    if bulk_filter_collected_jobs(sheet, resume_json, force_process=True) > 0:
        progress_made_in_cycle = True

    print("\nFinal pass: Processing all pending jobs in the database...")
    if CHECK_SUSTAINABILITY:
        if validate_sustainability_for_unprocessed_jobs(sheet) > 0:
            progress_made_in_cycle = True
    if analyze_all_jobs(sheet, resume_json) > 0:
        progress_made_in_cycle = True
    if process_resumes_and_cover_letters(sheet, resume_json) > 0:
        progress_made_in_cycle = True

    print(f"\nCycle summary:")
    print(f" - New jobs collected: {len(collected_jobs)}")

    if process_linkedin_collection(sheet, resume_json, company_overview_cache, shutdown_requested):
        progress_made_in_cycle = True

    if not progress_made_in_cycle:
        print("\nUseless cycle (no progress made).")

    print("\nFinalizing processing cycle...")
    print("\nSorting database by fit score and location priority...")
    sheet.sort((get_column_index(sheet, 'Fit score enum'), 'des'),
               (get_column_index(sheet, 'Location Priority'), 'asc'))

    from .auto_filter_adjustment import maybe_auto_adjust_filters
    if maybe_auto_adjust_filters(sheet):
        progress_made_in_cycle = True

    print(f"\nProcessing cycle completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return progress_made_in_cycle


def main():
    """Main loop that runs continuously."""
    from setup_server import get_app_root, run_setup_if_needed
    from api_methods import get_resume_json

    if not run_setup_if_needed():
        print("Configuration incomplete. Exiting.")
        return
    load_dotenv(get_app_root() / ".env")
    os.chdir(get_app_root())

    if not setup_and_validate():
        return

    _setup_log_capture()
    shutdown_requested = setup_signal_handlers()
    resume_json = get_resume_json()
    initialize_job_preferences()
    user_name = get_user_name(resume_json)
    sheet = initialize_storage(user_name)

    last_check_time = 0
    progress_made_in_cycle = True
    base_sleep_interval = 3600
    current_sleep_interval = base_sleep_interval
    company_overview_cache = _build_company_overview_cache(sheet)
    dashboard_launched = {"launched": False}

    _launch_dashboard_once(sheet, dashboard_launched)

    while not shutdown_requested['flag']:
        try:
            has_incomplete_jobs = check_incomplete_jobs(sheet)
            nothing_else_to_do = not has_incomplete_jobs and not CRAWL_LINKEDIN and not utils.apify_state.is_available()
            if nothing_else_to_do:
                print("\n" + "!" * 60)
                print("NOTHING ELSE TO DO: Apify is unavailable, LinkedIn crawling is disabled, and no pending jobs found.")
                print("Stopping application.")
                print("!" * 60 + "\n")
                shutdown_requested['flag'] = True
                break

            current_sleep_interval = _handle_sleep_logic(
                has_incomplete_jobs, progress_made_in_cycle, last_check_time,
                current_sleep_interval, base_sleep_interval, shutdown_requested
            )

            if shutdown_requested['flag']:
                break

            if has_incomplete_jobs:
                print("Found jobs with missing data. Processing immediately...")

            _launch_dashboard_once(sheet, dashboard_launched)

            print(f"\n{'=' * 60}")
            print(f"Starting new processing cycle at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'=' * 60}\n")

            last_check_time = time.time()

            if shutdown_requested['flag']:
                break

            progress_made_in_cycle = _run_processing_cycle(
                sheet, resume_json, company_overview_cache, shutdown_requested
            )

            if shutdown_requested['flag']:
                break

            if progress_made_in_cycle and current_sleep_interval != base_sleep_interval:
                print(f"\nProgress made! Resetting sleep interval to {base_sleep_interval / 3600:.1f}h")
                current_sleep_interval = base_sleep_interval

        except KeyboardInterrupt:
            print("\n\nKeyboard interrupt received. Shutting down gracefully...")
            shutdown_requested['flag'] = True
            break
        except Exception as e:
            if shutdown_requested['flag']:
                break
            print(f"\n\nAn error occurred: {e}")
            import traceback
            traceback.print_exc()
            if shutdown_requested['flag']:
                break
            continue

    print("\nShutdown complete. Goodbye!")
