"""JD-only fit scoring when standard automation cannot make further progress."""

import time

from utils.gemini_jd_fit import score_jobs_by_jd_batch
from utils.gemini_throttle import acquire_gemini_slot
from utils.jd_fit import parse_jd_fit_score

from .constants import (
    CHECK_SUSTAINABILITY,
    JD_FIT_BATCH_MAX_RETRIES,
    JD_FIT_BATCH_SIZE,
    JD_FIT_MAX_CONSECUTIVE_BATCH_FAILURES,
)
from .dashboard_filter import row_passes_default_dashboard_filter


def _row_blocked_from_full_analysis(row) -> bool:
    """True when a job has a JD but cannot receive a full Fit score yet."""
    if not (row.get('Job Description') or '').strip():
        return False
    if (row.get('Fit score') or '').strip():
        return False
    if row.get('Applied') == 'TRUE' or row.get('Job posting expired') == 'TRUE':
        return False
    if (row.get('Bad analysis') or '').strip().upper() == 'TRUE':
        return False
    if CHECK_SUSTAINABILITY:
        if not (row.get('Company overview') or '').strip():
            return True
        if (row.get('Sustainable company') or '').strip().upper() != 'TRUE':
            return True
    return False


def _needs_jd_fit_score(row) -> bool:
    if not _row_blocked_from_full_analysis(row):
        return False
    return parse_jd_fit_score(row.get('JD fit score')) is None


def _has_pending_full_analysis(db) -> bool:
    """True when any job can still receive a full Fit score via the normal pipeline."""
    for row in db.get_all_records():
        if not row.get('Job Title') or row.get('Applied') == 'TRUE' or row.get('Job posting expired') == 'TRUE':
            continue
        has_fit = bool((row.get('Fit score') or '').strip())
        bad_analysis = (row.get('Bad analysis') or '').strip().upper() == 'TRUE'
        if has_fit and not bad_analysis:
            continue
        if not (row.get('Job Description') or '').strip():
            continue
        if CHECK_SUSTAINABILITY:
            if not (row.get('Company overview') or '').strip():
                continue
            if (row.get('Sustainable company') or '').strip().upper() != 'TRUE':
                continue
        return True
    return False


def jobs_need_jd_fit_scoring(db) -> bool:
    """Return True if any job still needs a JD-only fit score."""
    for row in db.get_all_records():
        if not row.get('Job Title'):
            continue
        if _needs_jd_fit_score(row):
            return True
    return False


def _has_actionable_pipeline_work(db) -> bool:
    """
    Work the standard pipeline can still progress on (excluding manual CO sourcing).
    CO fetch is only actionable until CO fetch attempted is set without an overview.
    """
    import utils

    for row in db.get_all_records():
        if not row.get('Job Title'):
            continue
        if row.get('Applied') == 'TRUE' or row.get('Bad analysis') == 'TRUE' or row.get('Job posting expired') == 'TRUE':
            continue

        if not (row.get('Job Description') or '').strip():
            if utils.apify_state.is_available():
                return True
            continue

        if not (row.get('Fit score') or '').strip():
            if not CHECK_SUSTAINABILITY:
                return True
            if (row.get('Company overview') or '').strip() and (row.get('Sustainable company') or '').strip().upper() == 'TRUE':
                return True

        if CHECK_SUSTAINABILITY and not (row.get('Company overview') or '').strip():
            co_attempted = (row.get('CO fetch attempted') or '').strip().upper() == 'TRUE'
            if not co_attempted:
                if utils.apify_state.is_available():
                    return True

    return False


def is_automation_idle(db) -> bool:
    """True when the standard pipeline has no actionable work left."""
    return not _has_actionable_pipeline_work(db) and not _has_pending_full_analysis(db)


def manual_co_work_pending(db) -> bool:
    """True when jobs have JDs but still need company overviews before full analysis."""
    if not CHECK_SUSTAINABILITY:
        return False
    for row in db.get_all_records():
        if not row_passes_default_dashboard_filter(row):
            continue
        if not row.get('Job Title'):
            continue
        if row.get('Applied') == 'TRUE' or row.get('Job posting expired') == 'TRUE':
            continue
        if not (row.get('Job Description') or '').strip():
            continue
        if (row.get('Fit score') or '').strip():
            continue
        if not (row.get('Company overview') or '').strip():
            return True
    return False


def should_run_jd_only_fit_scoring(db) -> bool:
    """
    Run JD-only scoring when automation is idle on standard paths but jobs need prioritization.
    """
    if not jobs_need_jd_fit_scoring(db):
        return False
    if _has_actionable_pipeline_work(db):
        return False
    return True


def _job_details_from_row(row) -> dict:
    return {
        'company_name': row.get('Company Name', ''),
        'job_title': row.get('Job Title', ''),
        'job_description': row.get('Job Description', ''),
        'location': row.get('Location', ''),
    }


def _row_key(row) -> str:
    return f"{row.get('Job Title', '')} @ {row.get('Company Name', '')}"


def _score_batch_with_retries(resume_json, batch_rows) -> list[dict]:
    job_details = [_job_details_from_row(row) for row in batch_rows]
    for attempt in range(JD_FIT_BATCH_MAX_RETRIES):
        acquire_gemini_slot()
        batch_results = score_jobs_by_jd_batch(resume_json, job_details)
        if batch_results:
            return batch_results
        if attempt < JD_FIT_BATCH_MAX_RETRIES - 1:
            wait = min(20 * (2 ** attempt), 180)
            print(f"  JD fit batch failed (attempt {attempt + 1}/{JD_FIT_BATCH_MAX_RETRIES}); retrying in {wait}s...")
            time.sleep(wait)
    return []


def score_jobs_by_jd_fit(db, resume_json) -> int:
    """Score unscored jobs in batches and persist JD fit score + reasoning. Returns count updated."""
    to_score = []
    for row in db.get_all_records():
        if not row.get('Job Title'):
            continue
        if not _needs_jd_fit_score(row):
            continue
        to_score.append(row)

    if not to_score:
        return 0

    total_batches = (len(to_score) + JD_FIT_BATCH_SIZE - 1) // JD_FIT_BATCH_SIZE
    print("\n" + "=" * 60)
    print(
        f"JD-ONLY FIT SCORING: {len(to_score)} jobs in up to {total_batches} batches "
        f"(batch size {JD_FIT_BATCH_SIZE})"
    )
    print("=" * 60 + "\n")

    scored = 0
    consecutive_failures = 0
    for batch_index, batch_start in enumerate(range(0, len(to_score), JD_FIT_BATCH_SIZE), start=1):
        batch_rows = to_score[batch_start:batch_start + JD_FIT_BATCH_SIZE]
        print(f"  Batch {batch_index}/{total_batches} ({len(batch_rows)} jobs)...")

        batch_results = _score_batch_with_retries(resume_json, batch_rows)
        if not batch_results:
            consecutive_failures += 1
            print(f"  Batch {batch_index} failed after retries; skipping to next batch.")
            if consecutive_failures >= JD_FIT_MAX_CONSECUTIVE_BATCH_FAILURES:
                print(
                    f"  Stopping JD fit scoring after {consecutive_failures} consecutive batch failures."
                )
                break
            continue

        consecutive_failures = 0
        result_by_id = {item['job_id']: item for item in batch_results if item.get('job_id')}
        batch_scored = 0
        for row in batch_rows:
            res = result_by_id.get(_row_key(row))
            if not res:
                continue
            db.update_job_by_key(
                row.get('Job URL', '').strip(),
                row.get('Company Name', '').strip(),
                {
                    'JD fit score': str(res['jd_fit_score']),
                    'JD fit reasoning': res.get('reasoning', ''),
                },
            )
            batch_scored += 1
            scored += 1

        print(f"  Batch {batch_index} done: scored {batch_scored}/{len(batch_rows)} (total {scored}/{len(to_score)})")

    print(f"\nJD-only fit scoring completed. Scored {scored}/{len(to_score)} jobs.")
    return scored
