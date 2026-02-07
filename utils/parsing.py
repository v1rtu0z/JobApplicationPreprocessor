"""Text parsing, location, fit score, company name, and URL helpers."""

import re
from typing import Any

import html2text

from config import _get_job_filters


def column_index_to_letter(col_index: int) -> str:
    """
    Convert a 1-indexed column number to column letter(s).
    E.g., 1 -> 'A', 2 -> 'B', 27 -> 'AA'
    """
    result = ""
    while col_index > 0:
        col_index, remainder = divmod(col_index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def html_to_markdown(html_text: str) -> str:
    """Convert HTML to Markdown"""
    h = html2text.HTML2Text()
    h.ignore_links = False
    h.body_width = 0  # Don't wrap text
    return h.handle(html_text)


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
    Return priority score for sorting based on configuration in filters.yaml.
    """
    filters = _get_job_filters()
    location_priorities = filters.get('location_priorities', {})

    location_lower = location.lower()

    # Sort priorities by score to ensure we check them in order if needed,
    # but here we just look for matches.
    for loc, priority in sorted(location_priorities.items(), key=lambda x: x[1]):
        if loc.lower() in location_lower:
            return priority

    # Default priority if no match found
    return max(location_priorities.values()) + 1 if location_priorities else 5


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


def normalize_company_name(company_name: str) -> str:
    """
    Normalize company name for case-insensitive matching and caching.
    Strips whitespace and converts to lowercase.

    Args:
        company_name: Company name string

    Returns:
        Normalized company name (lowercase, stripped)
    """
    if not company_name:
        return ''
    return company_name.strip().lower()


def extract_job_id(url: str | None) -> str | None:
    """Extract numerical job ID from a LinkedIn job URL."""
    if not url:
        return None
    match = re.search(r'view/(\d+)', url)
    if match:
        return match.group(1)
    match = re.search(r'currentJobId=(\d+)', url)
    if match:
        return match.group(1)
    return None
