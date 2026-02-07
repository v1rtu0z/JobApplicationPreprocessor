"""Keyword filters, sustainability check, and company overview cache."""

from config import _get_job_filters
from utils import (
    fit_score_to_enum,
    is_sustainable_company,
    normalize_company_name,
)

from .constants import CHECK_SUSTAINABILITY


def _apply_keyword_filters(job_title, company_name, raw_location, filters):
    """Apply keyword-based filters to determine if a job should be skipped."""
    should_skip_location = any(keyword in raw_location.lower() for keyword in filters['location_skip_keywords'])
    should_skip_title = any(keyword in job_title.lower() for keyword in filters['job_title_skip_keywords'])
    should_skip_title_2 = any(
        keyword in job_title.lower().split(' ') for keyword in filters['job_title_skip_keywords_2'])
    should_skip_company = any(keyword in normalize_company_name(company_name) for keyword in filters['company_skip_keywords'])

    if should_skip_title or should_skip_title_2:
        return True, 'Job title contains unwanted technology'
    elif should_skip_location:
        return True, 'Location not preferred'
    elif should_skip_company:
        return True, 'Company name contains unwanted keyword'

    return False, None


def _check_and_process_filters(job_title, company_name, raw_location, company_overview='', job_description='',
                               sheet=None):
    """
    Checks job details against skip keywords and prepares analysis data.
    Returns (fit_score, fit_score_enum, analysis_reason, sustainability_status, bulk_filtered).
    """
    filters = _get_job_filters()

    should_skip, skip_reason = _apply_keyword_filters(job_title, company_name, raw_location, filters)

    if should_skip:
        fit_score = 'Poor fit'
        fit_score_enum = fit_score_to_enum(fit_score)
        print(f"Skipping job due to filter: {job_title} @ {company_name}. Reason: {skip_reason}")
        return fit_score, fit_score_enum, skip_reason, None, 'TRUE'

    is_sustainable = None
    if CHECK_SUSTAINABILITY and company_overview:
        is_sustainable = is_sustainable_company(company_name, company_overview, job_description, sheet)

    if is_sustainable is False:
        fit_score = 'Very poor fit'
        fit_score_enum = fit_score_to_enum(fit_score)
        analysis_reason = 'Unsustainable company (weapons/fossil fuels/harmful industries)'
        print(f"Skipping job due to filter: {job_title} @ {company_name}. Reason: {analysis_reason}")
        return fit_score, fit_score_enum, analysis_reason, False, 'TRUE'

    return '', '', '', is_sustainable, 'FALSE'


def _normalize_job_title(job_title):
    """Cleans up the job title."""
    if not job_title or not isinstance(job_title, str):
        return ''
    job_title = job_title.strip()
    if not job_title:
        return ''

    lines = job_title.split('\n')
    if len(lines) == 1:
        return job_title

    first_line = lines[0]
    is_duplicate = (len(set(lines)) == 1 or first_line in lines[1] or lines[1] in first_line)

    return first_line if is_duplicate else job_title


def _build_company_overview_cache(sheet):
    """Build a dictionary of company name -> company overview from existing sheet data."""
    all_rows = sheet.get_all_records()
    cache = {}
    for row in all_rows:
        company_name = row.get('Company Name', '').strip()
        company_overview = row.get('Company overview', '').strip()
        if company_name and company_overview:
            company_key = normalize_company_name(company_name)
            if company_key not in cache:
                cache[company_key] = company_overview
    return cache
