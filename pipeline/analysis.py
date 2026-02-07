"""Single-job and batch job analysis (fit score via LLM)."""

import utils
from utils import parse_fit_score, fit_score_to_enum, html_to_markdown
from api_methods import get_job_analysis
from config import _get_job_filters

from .constants import CHECK_SUSTAINABILITY
from .filtering import get_sustainability_keyword_matches
from .resumes import process_cover_letter, process_resume


def analyze_single_job(sheet, row, resume_json) -> str | None:
    """Analyze a single job and update the database. Returns fit score if performed, None if skipped."""
    if row.get('Fit score') and row.get('Bad analysis', '').strip() != 'TRUE':
        return row.get('Fit score')

    job_title = row.get('Job Title', '')
    company_name = row.get('Company Name', '')
    job_url = row.get('Job URL', '')

    print(f"Analyzing: {job_title} @ {company_name}")

    job_details = {
        'company_name': company_name,
        'job_title': job_title,
        'job_description': row.get('Job Description', ''),
        'location': row.get('Location', ''),
        'company_overview': row.get('Company overview', ''),
    }

    try:
        job_analysis = get_job_analysis(resume_json, job_details)
        fit_score = parse_fit_score(job_analysis)

        filters = _get_job_filters()
        _, _, sust_matches = get_sustainability_keyword_matches(
            job_title, company_name, row.get('Location') or '', row.get('Company overview') or '', filters
        )
        updates = {
            'Fit score': fit_score,
            'Fit score enum': str(fit_score_to_enum(fit_score)),
            'Job analysis': html_to_markdown(job_analysis),
            'Sustainability keyword matches': sust_matches or '',
        }
        if row.get('Bad analysis', '').strip() == 'TRUE':
            updates['Bad analysis'] = 'FALSE'
        sheet.update_job_by_key(job_url, company_name, updates)

        if fit_score == 'Very good fit':
            print("\n" + "*" * 60)
            print("🌟 GREAT FIT DETECTED! 🌟")
            print(f"Job: {job_title} @ {company_name}")
            print("Immediately processing resume and cover letter...")
            print("*" * 60 + "\n")
            try:
                process_cover_letter(sheet, row, resume_json)
                process_resume(sheet, row, resume_json)
            except Exception as e:
                print(f"Error immediately processing Very good fit job: {e}")
        elif fit_score in ['Good fit', 'Moderate fit']:
            print(f"Found a {fit_score}: {job_title} @ {company_name}")

        print(f"Added analysis for: {job_title} @ {company_name}")
        return fit_score

    except Exception as e:
        error_message = str(e)
        if '429' in error_message or 'Rate limit' in error_message or 'ResourceExhausted' in error_message:
            utils.mark_gemini_rate_limit_hit()
            print(f"Gemini rate limit hit for job analysis: {row.get('Job Title')} @ {row.get('Company Name')}. Will retry after short wait.")
            return None


def analyze_all_jobs(sheet, resume_json, target_jobs=None):
    """Analyze all jobs that don't have a fit score yet. Returns number analyzed."""
    print("\n" + "=" * 60)
    print("ANALYSIS LOOP: Analyzing all unprocessed jobs")
    print("=" * 60 + "\n")

    all_rows = sheet.get_all_records()
    analyzed_count = 0
    consecutive_analysis_failure_count = 0
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

    for row in all_rows:
        if not row.get('Job Title'):
            break

        job_url = row.get('Job URL', '').strip()
        company_name = row.get('Company Name', '').strip()
        job_title = row.get('Job Title', '').strip()

        if target_jobs is not None:
            if (job_url, company_name) not in target_jobs:
                continue

        if row.get('Job posting expired') == 'TRUE':
            _record_skip("Job posting expired", company_name, job_title)
            continue

        if not row.get('Job Description'):
            _record_skip("Missing Job Description", company_name, job_title, row_for_breakdown=row)
            continue

        if not row.get('Company overview'):
            _record_skip("Missing Company overview", company_name, job_title, row_for_breakdown=row)
            continue

        # Re-analyze when user marked analysis as bad (ignore existing fit score)
        bad_analysis = row.get('Bad analysis', '').strip() == 'TRUE'
        if not bad_analysis:
            fit_score_val = (row.get('Fit score') or '').strip()
            if fit_score_val in ['Poor fit', 'Very poor fit', 'Moderate fit', 'Questionable fit']:
                _record_skip("Already has non-good fit score (poor/moderate/questionable)", company_name, job_title)
                continue
            if fit_score_val in ['Good fit', 'Very good fit'] or fit_score_val:
                continue

        # Primary exclusion: already-applied jobs hidden from default view
        if row.get('Applied') == 'TRUE':
            _record_skip("Already applied", company_name, job_title)
            continue

        # Sustainability gate: skip unless company is validated (LLM runs in sustainability validation phase first).
        if CHECK_SUSTAINABILITY:
            sustainable_val = row.get('Sustainable company', '').strip().upper()
            if sustainable_val == 'FALSE':
                _record_skip("Company marked unsustainable (Sustainable=FALSE)", company_name, job_title)
                continue
            if sustainable_val != 'TRUE':
                _record_skip("Sustainability pending (missing overview or not yet validated)", company_name, job_title)
                continue

        fit_score = analyze_single_job(sheet, row, resume_json)
        if fit_score:
            analyzed_count += 1
            consecutive_analysis_failure_count = 0
        else:
            consecutive_analysis_failure_count += 1
            if consecutive_analysis_failure_count >= 5:
                print(f"Skipping further analysis due to {consecutive_analysis_failure_count} consecutive analysis failures.")
                break

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
