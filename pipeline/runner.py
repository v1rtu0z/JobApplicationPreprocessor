"""Setup, shutdown handlers, processing cycle, and main loop."""

import os
import time
from datetime import datetime

from dotenv import load_dotenv
import utils
from utils import (
    get_user_name,
    setup_database,
    validate_sustainability_for_unprocessed_jobs,
)

from .constants import (
    BASE_SLEEP_INTERVAL_SECONDS,
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
    """Ensure job_preferences.yaml exists with empty defaults (no placeholders)."""
    if not os.path.exists(CONFIG_FILE):
        print(f"Creating {CONFIG_FILE} with empty defaults...")
        filters = _get_job_filters()
        _save_job_filters(filters)


def initialize_storage(user_name: str):
    """Initialize local SQLite storage. Returns the job database."""
    print("\n" + "!" * 60)
    print("Using local storage mode (SQLite database).")
    print("Note: To view your jobs, use the Streamlit dashboard: streamlit run dashboard.py")
    print("!" * 60 + "\n")
    from local_storage import ensure_local_directories
    ensure_local_directories()
    db = setup_database(user_name)
    return db


def check_incomplete_jobs(db) -> bool:
    """Return True if there are jobs with missing data that can be fetched."""
    all_rows = db.get_all_records()
    for row in all_rows:
        if not row.get('Job Title') or row.get('Applied') == 'TRUE' or row.get('Bad analysis') == 'TRUE' or row.get('Job posting expired') == 'TRUE':
            continue
        needs_jd = not row.get('Job Description') and CRAWL_LINKEDIN
        needs_co = (
            CHECK_SUSTAINABILITY
            and not row.get('Company overview')
            and utils.apify_state.is_available()
        )
        can_get_jd = row.get('Job Description') or CRAWL_LINKEDIN
        can_get_co = (
            row.get('Company overview')
            or (utils.apify_state.is_available() if CHECK_SUSTAINABILITY else True)
        )
        needs_analysis = not row.get('Fit score') and can_get_jd and can_get_co
        if needs_jd or needs_co or needs_analysis:
            return True
    return False


def has_pending_analysis(db) -> bool:
    """Return True if any job still needs analysis: no Fit score yet, or marked Bad analysis (re-run).
    Uses a broad definition (JD + no fit/bad) so we never exit when analysis was skipped (e.g. rate limit)."""
    all_rows = db.get_all_records()
    for row in all_rows:
        if not row.get('Job Title') or row.get('Applied') == 'TRUE' or row.get('Job posting expired') == 'TRUE':
            continue
        # Needs analysis if: no fit score yet, or user marked analysis as bad (re-analyze)
        has_fit = bool((row.get('Fit score') or '').strip())
        bad_analysis = (row.get('Bad analysis') or '').strip().upper() == 'TRUE'
        if has_fit and not bad_analysis:
            continue
        if not (row.get('Job Description') or '').strip():
            continue
        # When sustainability is on, only count jobs we can actually analyze (have CO + Sustainable)
        if CHECK_SUSTAINABILITY:
            if not (row.get('Company overview') or '').strip():
                continue
            if (row.get('Sustainable company') or '').strip().upper() != 'TRUE':
                continue
        return True
    return False


class SleepController:
    """Handles sleep duration, Gemini rate-limit short wait, and exponential backoff."""

    def __init__(self, base_interval_seconds: float):
        self.base_interval = base_interval_seconds
        self.current_interval = base_interval_seconds

    def run(
        self,
        has_work: bool,
        progress_made_in_cycle: bool,
        last_check_time: float,
        shutdown_requested: dict,
    ) -> float:
        """Maybe sleep (rate-limit short wait or normal/backoff), then return current interval (possibly updated)."""
        time_since_last_check = time.time() - last_check_time
        should_sleep = (
            (not has_work or (not progress_made_in_cycle and last_check_time > 0))
            and time_since_last_check < self.current_interval
        )

        if not progress_made_in_cycle and utils.gemini_rate_limit.gemini_rate_limit_hit and has_work:
            self._sleep(GEMINI_RATE_LIMIT_SHORT_WAIT_SECONDS, shutdown_requested,
                       f"Gemini rate limit was hit. Short wait of {GEMINI_RATE_LIMIT_SHORT_WAIT_SECONDS / 60:.1f} minutes before retry...")
            return self.current_interval

        if should_sleep:
            sleep_time = self.current_interval - time_since_last_check
            if not has_work:
                msg = f"All jobs complete. Sleeping for {sleep_time / 60:.1f} minutes until next check..."
            else:
                msg = f"No progress made. Sleeping for {sleep_time / 60:.1f} minutes to avoid tight loop (exponential backoff: {self.current_interval / 3600:.1f}h)..."
            self._sleep(sleep_time, shutdown_requested, msg)

            if not progress_made_in_cycle and last_check_time > 0:
                self.current_interval = min(self.current_interval * 2, 86400)
                print(f"Exponential backoff: Next sleep interval will be {self.current_interval / 3600:.1f}h")
                return self.current_interval

            if shutdown_requested.get('flag'):
                print("\nShutdown requested during sleep, exiting...")

        return self.current_interval

    def _sleep(self, sleep_time: float, shutdown_requested: dict, message: str) -> None:
        print(f"\n{message}")
        print("(Press Ctrl+C to interrupt and exit)")
        sleep_chunk = 5
        slept = 0
        while slept < sleep_time and not shutdown_requested.get('flag'):
            time.sleep(min(sleep_chunk, sleep_time - slept))
            slept += sleep_chunk

    def reset_to_base(self) -> None:
        """Reset current interval to base (e.g. after progress was made)."""
        self.current_interval = self.base_interval


def _run_processing_cycle(db, resume_json, company_overview_cache, shutdown_requested):
    """Run a single processing cycle. Returns True if any progress was made."""
    utils.reset_gemini_rate_limit_flag()
    progress_made_in_cycle = False

    if not SKIP_JD_FETCH:
        if bulk_fetch_missing_job_descriptions(db) > 0:
            progress_made_in_cycle = True

    # Company overview fetch only when sustainability is enabled (COs used only for sustainability).
    if CHECK_SUSTAINABILITY and fetch_company_overviews(db, company_overview_cache) > 0:
        progress_made_in_cycle = True

    collected_jobs, total_new_jobs, _ = process_collection_phase(
        db, resume_json, shutdown_requested, company_overview_cache
    )

    if total_new_jobs > 0:
        progress_made_in_cycle = True

    if collected_jobs:
        print(f"\nProcessing {len(collected_jobs)} total new jobs collected in this cycle...")
        if process_new_jobs_pipeline(db, resume_json, collected_jobs, company_overview_cache):
            progress_made_in_cycle = True

    print("\nFinalizing processing cycle (processing leftover batches)...")
    if bulk_filter_collected_jobs(db, resume_json, force_process=True) > 0:
        progress_made_in_cycle = True

    print("\nFinal pass: Processing all pending jobs in the database...")
    if CHECK_SUSTAINABILITY:
        if validate_sustainability_for_unprocessed_jobs(db) > 0:
            progress_made_in_cycle = True
    if analyze_all_jobs(db, resume_json) > 0:
        progress_made_in_cycle = True
    if process_resumes_and_cover_letters(db, resume_json) > 0:
        progress_made_in_cycle = True

    print(f"\nCycle summary:")
    print(f" - New jobs collected: {len(collected_jobs)}")

    if process_linkedin_collection(db, resume_json, company_overview_cache, shutdown_requested):
        progress_made_in_cycle = True

    if not progress_made_in_cycle:
        print("\nUseless cycle (no progress made).")

    print("\nFinalizing processing cycle...")
    print("\nSorting database by fit score and location priority...")
    db.sort_by([('Fit score enum', False), ('Location Priority', True)])

    from .auto_filter_adjustment import maybe_auto_adjust_filters
    if maybe_auto_adjust_filters(db):
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
    db = initialize_storage(user_name)

    last_check_time = 0
    progress_made_in_cycle = True
    sleep_controller = SleepController(base_interval_seconds=BASE_SLEEP_INTERVAL_SECONDS)
    company_overview_cache = _build_company_overview_cache(db)
    dashboard_launched = {"launched": False}

    _launch_dashboard_once(db, dashboard_launched)

    while not shutdown_requested['flag']:
        try:
            has_incomplete_jobs = check_incomplete_jobs(db)
            has_pending = has_pending_analysis(db)
            has_work = has_incomplete_jobs or has_pending
            nothing_else_to_do = (
                not has_work
                and not CRAWL_LINKEDIN
                and not utils.apify_state.is_available()
            )
            if nothing_else_to_do:
                print("\n" + "!" * 60)
                print("NOTHING ELSE TO DO: Apify is unavailable, LinkedIn crawling is disabled, and no pending jobs found.")
                print("Stopping application.")
                print("!" * 60 + "\n")
                shutdown_requested['flag'] = True
                break

            sleep_controller.run(
                has_work=has_work,
                progress_made_in_cycle=progress_made_in_cycle,
                last_check_time=last_check_time,
                shutdown_requested=shutdown_requested,
            )

            if shutdown_requested['flag']:
                break

            if has_work:
                print("Found jobs with missing data or pending analysis. Processing...")

            _launch_dashboard_once(db, dashboard_launched)

            print(f"\n{'=' * 60}")
            print(f"Starting new processing cycle at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'=' * 60}\n")

            last_check_time = time.time()

            if shutdown_requested['flag']:
                break

            progress_made_in_cycle = _run_processing_cycle(
                db, resume_json, company_overview_cache, shutdown_requested
            )

            if shutdown_requested['flag']:
                break

            if progress_made_in_cycle and sleep_controller.current_interval != sleep_controller.base_interval:
                print(f"\nProgress made! Resetting sleep interval to {sleep_controller.base_interval / 3600:.1f}h")
                sleep_controller.reset_to_base()

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
