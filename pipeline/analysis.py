"""Single-job and batch job analysis (fit score via LLM)."""

import utils
from utils import fit_score_to_enum
from utils.gemini_analysis import analyze_jobs_batch
from utils.gemini_throttle import acquire_gemini_slot
from config import _get_job_filters

from .constants import ANALYSIS_BATCH_SIZE, CHECK_SUSTAINABILITY
from .filtering import check_and_process_filters, get_sustainability_keyword_matches
from .resumes import process_cover_letter, process_resume

# In-memory cache: (job_url, company_name, jd_hash) -> {fit_score, reasoning}
_analysis_cache: dict[tuple, dict] = {}


def _analysis_cache_key(row) -> tuple:
    """Cache key for avoiding re-analysis of the same job."""
    jd = (row.get('Job Description') or '').strip()
    return (
        (row.get('Job URL') or '').strip(),
        (row.get('Company Name') or '').strip(),
        hash(jd),
    )


def _apply_analysis_result(db, row, fit_score: str, reasoning: str, resume_json, filters) -> None:
    """Write analysis to DB and trigger resume/CL for Very good fit."""
    job_title = row.get('Job Title', '')
    company_name = row.get('Company Name', '')
    job_url = row.get('Job URL', '')
    _, _, sust_matches = get_sustainability_keyword_matches(
        job_title, company_name,
        row.get('Location') or '',
        row.get('Company overview') or '',
        filters,
    )
    updates = {
        'Fit score': fit_score,
        'Fit score enum': str(fit_score_to_enum(fit_score)),
        'Job analysis': reasoning,
        'Sustainability keyword matches': sust_matches or '',
    }
    if row.get('Bad analysis', '').strip() == 'TRUE':
        updates['Bad analysis'] = 'FALSE'
    db.update_job_by_key(job_url, company_name, updates)

    if fit_score == 'Very good fit':
        print("\n" + "*" * 60)
        print("🌟 GREAT FIT DETECTED! 🌟")
        print(f"Job: {job_title} @ {company_name}")
        print("Immediately processing resume and cover letter...")
        print("*" * 60 + "\n")
        try:
            process_cover_letter(db, row, resume_json)
            process_resume(db, row, resume_json)
            # Re-fetch by key (not row["_id"], which get_all_records() strips) so we see the
            # resume/CL url written above, not the stale pre-generation snapshot.
            refreshed = next(
                (
                    j for j in db.get_all_jobs()
                    if j.get('Job URL') == job_url and j.get('Company Name') == company_name
                ),
                row,
            )
            from utils.telegram_bot import application_is_ready

            if refreshed and application_is_ready(refreshed):
                from pipeline.telegram_notify import process_telegram_notifications

                process_telegram_notifications(db)
            else:
                print(
                    f"Very good fit for {job_title} @ {company_name}: "
                    "deferring Telegram until resume and cover letter are ready."
                )
        except Exception as e:
            print(f"Error immediately processing Very good fit job: {e}")
    elif fit_score in ['Good fit', 'Moderate fit']:
        print(f"Found a {fit_score}: {job_title} @ {company_name}")
    print(f"Added analysis for: {job_title} @ {company_name}")


def _job_details_from_row(row) -> dict:
    """Build job_details dict from a DB row for batch analysis."""
    return {
        'company_name': row.get('Company Name', ''),
        'job_title': row.get('Job Title', ''),
        'job_description': row.get('Job Description', ''),
        'location': row.get('Location', ''),
        'company_overview': row.get('Company overview', ''),
    }


def _row_key(row) -> str:
    """Canonical job_id for matching batch results to rows: Title @ Company."""
    return f"{row.get('Job Title', '')} @ {row.get('Company Name', '')}"


def _log_analysing(row, *, cached: bool = False) -> None:
    """Stdout line for activity.log / dashboard (British spelling matches historical logs)."""
    jt = (row.get("Job Title") or "").strip() or "?"
    cn = (row.get("Company Name") or "").strip() or "?"
    suffix = " (cached)" if cached else ""
    print(f"Analysing {jt} @ {cn}{suffix}")


def analyze_all_jobs(db, resume_json, target_jobs=None):
    """Analyze all jobs that don't have a fit score yet, in batches. Returns number analyzed."""
    print("\n" + "=" * 60)
    print("ANALYSIS LOOP: Analyzing all unprocessed jobs (batch)")
    print("=" * 60 + "\n")
    if target_jobs is not None:
        print(f"Scoped to dashboard default filter ({len(target_jobs)} jobs).\n")

    all_rows = db.get_all_records()
    skipped_reasons = {}
    skipped_example = {}
    breakdown = {}

    def _record_skip(reason, company_name, job_title, row_for_breakdown=None):
        skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1
        if reason not in skipped_example:
            skipped_example[reason] = (company_name or "?", job_title or "?")
        if row_for_breakdown is not None and reason == "Missing Job Description":
            if row_for_breakdown.get('Job posting expired') == 'TRUE':
                breakdown["missing_jd_also_expired"] = breakdown.get("missing_jd_also_expired", 0) + 1
            if str(row_for_breakdown.get('Sustainable company', '')).strip().upper() == 'FALSE':
                breakdown["missing_jd_unsustainable"] = breakdown.get("missing_jd_unsustainable", 0) + 1
        if row_for_breakdown is not None and reason == "Missing Company overview":
            if str(row_for_breakdown.get('CO fetch attempted', '')).strip().upper() == 'TRUE':
                breakdown["missing_co_fetch_attempted"] = breakdown.get("missing_co_fetch_attempted", 0) + 1

    def _would_analyze(row):
        if not row.get('Job Title'):
            return False
        job_url = row.get('Job URL', '').strip()
        company_name = row.get('Company Name', '').strip()
        if target_jobs is not None and (job_url, company_name) not in target_jobs:
            return False
        if row.get('Job posting expired') == 'TRUE':
            return False
        if not row.get('Job Description'):
            return False
        if CHECK_SUSTAINABILITY and not row.get('Company overview'):
            return False
        bad_analysis = row.get('Bad analysis', '').strip() == 'TRUE'
        if not bad_analysis:
            fit_score_val = (row.get('Fit score') or '').strip()
            if fit_score_val in ['Poor fit', 'Very poor fit', 'Moderate fit', 'Questionable fit']:
                return False
            if fit_score_val in ['Good fit', 'Very good fit'] or fit_score_val:
                return False
        if row.get('Applied') == 'TRUE':
            return False
        if CHECK_SUSTAINABILITY:
            sustainable_val = row.get('Sustainable company', '').strip().upper()
            if sustainable_val == 'FALSE' or sustainable_val != 'TRUE':
                return False
        return True

    # Collect rows to analyze and record skips for reporting
    to_analyze_rows: list[tuple] = []  # (row, job_details)
    analyzed_count = 0
    filters = _get_job_filters()
    for row in all_rows:
        if not row.get('Job Title'):
            continue

        job_url = row.get('Job URL', '').strip()
        company_name = row.get('Company Name', '').strip()
        if target_jobs is not None and (job_url, company_name) not in target_jobs:
            continue

        job_title = row.get('Job Title', '').strip()

        if row.get('Job posting expired') == 'TRUE':
            _record_skip("Job posting expired", company_name, job_title)
            continue

        if not row.get('Job Description'):
            _record_skip("Missing Job Description", company_name, job_title, row_for_breakdown=row)
            continue

        if CHECK_SUSTAINABILITY and not row.get('Company overview'):
            _record_skip("Missing Company overview", company_name, job_title, row_for_breakdown=row)
            continue

        filter_result = check_and_process_filters(
            job_title,
            company_name,
            row.get('Location', ''),
            row.get('Company overview', ''),
            row.get('Job Description', ''),
            db=db,
        )
        if filter_result.filtered:
            db.update_job_by_key(job_url, company_name, filter_result.row_updates(""))
            _record_skip(f"Keyword filter: {filter_result.analysis_reason}", company_name, job_title)
            continue

        bad_analysis = row.get('Bad analysis', '').strip() == 'TRUE'
        if not bad_analysis:
            fit_score_val = (row.get('Fit score') or '').strip()
            if fit_score_val in ['Poor fit', 'Very poor fit', 'Moderate fit', 'Questionable fit']:
                _record_skip("Already has non-good fit score (poor/moderate/questionable)", company_name, job_title)
                continue
            if fit_score_val in ['Good fit', 'Very good fit'] or fit_score_val:
                continue

        if row.get('Applied') == 'TRUE':
            _record_skip("Already applied", company_name, job_title)
            continue

        if CHECK_SUSTAINABILITY:
            sustainable_val = row.get('Sustainable company', '').strip().upper()
            if sustainable_val == 'FALSE':
                _record_skip("Company marked unsustainable (Sustainable=FALSE)", company_name, job_title)
                continue
            if sustainable_val != 'TRUE':
                _record_skip("Sustainability pending (missing overview or not yet validated)", company_name, job_title)
                continue

        cache_key = _analysis_cache_key(row)
        if cache_key in _analysis_cache:
            cached = _analysis_cache[cache_key]
            _log_analysing(row, cached=True)
            _apply_analysis_result(db, row, cached['fit_score'], cached['reasoning'], resume_json, filters)
            analyzed_count += 1
            continue

        to_analyze_rows.append((row, _job_details_from_row(row)))

    total = len([r for r in all_rows if r.get('Job Title')])
    print(f"Jobs about to be analyzed: {len(to_analyze_rows)} (of {total} job rows in db)\n")

    consecutive_batch_failures = 0
    for batch_start in range(0, len(to_analyze_rows), ANALYSIS_BATCH_SIZE):
        batch = to_analyze_rows[batch_start:batch_start + ANALYSIS_BATCH_SIZE]
        rows_batch = [r for r, _ in batch]
        job_details_batch = [j for _, j in batch]

        for row in rows_batch:
            _log_analysing(row)

        acquire_gemini_slot()
        batch_results = analyze_jobs_batch(resume_json, job_details_batch)

        if not batch_results:
            consecutive_batch_failures += 1
            if consecutive_batch_failures >= 5:
                print("Skipping further analysis due to 5 consecutive batch failures (e.g. rate limit).")
                break
            continue

        consecutive_batch_failures = 0
        result_by_id = {r['job_id']: r for r in batch_results}

        for row, job_details in batch:
            job_id = _row_key(row)
            res = result_by_id.get(job_id)
            if not res:
                continue

            fit_score = res['fit_score']
            reasoning = res.get('reasoning') or 'No reasoning provided'

            _apply_analysis_result(db, row, fit_score, reasoning, resume_json, filters)
            cache_key = _analysis_cache_key(row)
            _analysis_cache[cache_key] = {'fit_score': fit_score, 'reasoning': reasoning}
            analyzed_count += 1

    REPORT_ORDER = [
        "Company marked unsustainable (Sustainable=FALSE)",
        "Sustainability pending (missing overview or not yet validated)",
        "Already applied",
        "Already has non-good fit score (poor/moderate/questionable)",
        "Missing Company overview",
        "Missing Job Description",
        "Job posting expired",
    ]

    if skipped_reasons:
        print()
        print("Summary of skipped jobs in analysis (downstream gates first; pipeline checks expired before JD):")
        for reason in REPORT_ORDER:
            count = skipped_reasons.get(reason, 0)
            if count == 0:
                continue
            example = skipped_example.get(reason, (None, None))
            line = f"  - {count} jobs skipped: {reason}"
            if example[0] and example[1]:
                line += f" (e.g. {example[0]} – {example[1]})"
            if reason == "Missing Job Description" and (breakdown.get("missing_jd_also_expired") or breakdown.get("missing_jd_unsustainable")):
                parts = []
                if breakdown.get("missing_jd_also_expired"):
                    parts.append(f"{breakdown['missing_jd_also_expired']} also marked expired (pipeline bug if >0)")
                if breakdown.get("missing_jd_unsustainable"):
                    parts.append(f"{breakdown['missing_jd_unsustainable']} have Sustainable=FALSE (would be skipped later anyway)")
                if parts:
                    line += "\n      " + "; ".join(parts)
            if reason == "Missing Company overview" and breakdown.get("missing_co_fetch_attempted") is not None:
                line += f"\n      {breakdown['missing_co_fetch_attempted']} had CO fetch attempted (crawl/Apify failed or no overview found)"
            print(line)
        for reason, count in skipped_reasons.items():
            if reason not in REPORT_ORDER:
                example = skipped_example.get(reason, (None, None))
                if example[0] and example[1]:
                    print(f"  - {count} jobs skipped: {reason} (e.g. {example[0]} – {example[1]})")
                else:
                    print(f"  - {count} jobs skipped: {reason}")

    print(f"\nAnalysis loop completed. Analyzed {analyzed_count} jobs.")
    return analyzed_count
