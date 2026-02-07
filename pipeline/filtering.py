"""Keyword filters, sustainability check, and company overview cache."""

from dataclasses import dataclass

from config import _get_job_filters
from utils import (
    fit_score_to_enum,
    is_sustainable_company,
    normalize_company_name,
)

from .constants import CHECK_SUSTAINABILITY


@dataclass(frozen=True)
class FilterResult:
    """Result of applying keyword and sustainability filters to a job."""

    fit_score: str
    fit_score_enum: int
    analysis_reason: str
    is_sustainable: bool | None
    bulk_filtered: str
    sustainability_keyword_matches: str

    @property
    def filtered(self) -> bool:
        """True if the job was filtered out (should be marked with fit score / analysis)."""
        return bool(self.fit_score)

    def row_updates(self, last_expiration_check: str) -> dict:
        """Updates to persist for this job (fit score, analysis, keyword matches, last check)."""
        updates = {
            "Sustainability keyword matches": self.sustainability_keyword_matches or "",
            "Last expiration check": last_expiration_check,
        }
        if self.filtered:
            updates.update({
                "Fit score": self.fit_score,
                "Fit score enum": str(self.fit_score_enum),
                "Job analysis": self.analysis_reason,
                "Bulk filtered": self.bulk_filtered,
            })
        return updates


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


def get_sustainability_keyword_matches(job_title, company_name, raw_location, company_overview, filters):
    """
    Check sustainability_criteria positive/negative keywords (substring, case-insensitive).
    Returns (should_skip_by_negative, reason_if_skip, matches_str).
    matches_str: "negative: X" if skipped, else "positive: A, B" or "".
    """
    criteria = (filters.get('sustainability_criteria') or {})
    neg_list = criteria.get('negative')
    pos_list = criteria.get('positive')
    negative = [str(k).strip() for k in (neg_list if isinstance(neg_list, list) else [])]
    positive = [str(k).strip() for k in (pos_list if isinstance(pos_list, list) else [])]
    if not negative and not positive:
        return False, None, ''

    use_overview = criteria.get('use_company_overview_for_sustainability_keywords', True)
    search_parts = [job_title or '', (company_name or '').lower(), (raw_location or '').lower()]
    if use_overview and (company_overview or '').strip():
        search_parts.append((company_overview or '').lower())
    search_text = ' '.join(search_parts).lower()

    for kw in negative:
        if not kw:
            continue
        if kw.lower() in search_text:
            return True, f'Sustainability negative keyword: {kw}', f'negative: {kw}'

    found_positive = [kw for kw in positive if kw and kw.lower() in search_text]
    matches_str = f'positive: {", ".join(found_positive)}' if found_positive else ''
    return False, None, matches_str


def _apply_sustainability_keyword_filters(job_title, company_name, raw_location, company_overview, filters):
    """Apply sustainability keyword lists. Returns (should_skip, reason, matches_str)."""
    should_skip, reason, matches_str = get_sustainability_keyword_matches(
        job_title, company_name, raw_location, company_overview, filters
    )
    return should_skip, reason, matches_str


def check_and_process_filters(
    job_title: str,
    company_name: str,
    raw_location: str,
    company_overview: str = "",
    job_description: str = "",
    sheet=None,
) -> FilterResult:
    """
    Check job details against skip keywords and sustainability. Returns a FilterResult.
    """
    filters = _get_job_filters()

    should_skip, skip_reason = _apply_keyword_filters(job_title, company_name, raw_location, filters)
    if should_skip:
        print(f"Skipping job due to filter: {job_title} @ {company_name}. Reason: {skip_reason}")
        return FilterResult(
            fit_score="Poor fit",
            fit_score_enum=fit_score_to_enum("Poor fit"),
            analysis_reason=skip_reason,
            is_sustainable=None,
            bulk_filtered="TRUE",
            sustainability_keyword_matches="",
        )

    should_skip_sust, sust_reason, sustainability_keyword_matches = _apply_sustainability_keyword_filters(
        job_title, company_name, raw_location, company_overview or "", filters
    )
    if should_skip_sust:
        print(f"Skipping job due to filter: {job_title} @ {company_name}. Reason: {sust_reason}")
        return FilterResult(
            fit_score="Very poor fit",
            fit_score_enum=fit_score_to_enum("Very poor fit"),
            analysis_reason=sust_reason,
            is_sustainable=False,
            bulk_filtered="TRUE",
            sustainability_keyword_matches=sustainability_keyword_matches,
        )

    is_sustainable = None
    if CHECK_SUSTAINABILITY and company_overview:
        is_sustainable = is_sustainable_company(company_name, company_overview, job_description, sheet)

    if is_sustainable is False:
        analysis_reason = "Unsustainable company (weapons/fossil fuels/harmful industries)"
        print(f"Skipping job due to filter: {job_title} @ {company_name}. Reason: {analysis_reason}")
        return FilterResult(
            fit_score="Very poor fit",
            fit_score_enum=fit_score_to_enum("Very poor fit"),
            analysis_reason=analysis_reason,
            is_sustainable=False,
            bulk_filtered="TRUE",
            sustainability_keyword_matches=sustainability_keyword_matches,
        )

    return FilterResult(
        fit_score="",
        fit_score_enum=fit_score_to_enum(""),
        analysis_reason="",
        is_sustainable=is_sustainable,
        bulk_filtered="FALSE",
        sustainability_keyword_matches=sustainability_keyword_matches,
    )


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
