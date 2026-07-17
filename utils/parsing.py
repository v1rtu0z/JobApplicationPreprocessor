"""Text parsing, location, fit score, company name, and URL helpers."""

import re
from datetime import datetime, timedelta, timezone
from typing import Any

import html2text

from config import _get_job_filters


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


_RELATIVE_POSTED_RE = re.compile(
    r"""
    ^(?:posted\s+|reposted\s+)?
    (?:
        (?P<just>just\s+now|today)
        |(?P<yesterday>yesterday)
        |(?P<num>\d+)\s*(?P<unit>minute|hour|day|week|month|year)s?\s*ago
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

_ISO_DATE_RE = re.compile(r'^(\d{4}-\d{2}-\d{2})')


def normalize_posted_at(raw: str | None, *, now: datetime | None = None) -> str:
    """Normalize Apify ``posted_at`` to ``YYYY-MM-DD`` for storage and sorting.

    Accepts ISO dates, date-times, and LinkedIn-style relative strings
    (``2 days ago``, ``Reposted 1 week ago``, ``Just now``). Returns ``""`` if unknown.
    """
    text = (raw or '').strip()
    if not text:
        return ''

    iso = _ISO_DATE_RE.match(text)
    if iso:
        try:
            datetime.strptime(iso.group(1), '%Y-%m-%d')
            return iso.group(1)
        except ValueError:
            pass

    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)

    match = _RELATIVE_POSTED_RE.match(text)
    if not match:
        return ''

    if match.group('just'):
        return ref.date().isoformat()
    if match.group('yesterday'):
        return (ref.date() - timedelta(days=1)).isoformat()

    num = int(match.group('num'))
    unit = match.group('unit').lower()
    delta = {
        'minute': timedelta(minutes=num),
        'hour': timedelta(hours=num),
        'day': timedelta(days=num),
        'week': timedelta(weeks=num),
        'month': timedelta(days=30 * num),
        'year': timedelta(days=365 * num),
    }.get(unit)
    if delta is None:
        return ''
    return (ref - delta).date().isoformat()


def normalize_easy_apply(value) -> str:
    """Normalize Easy Apply flags to ``TRUE`` / ``FALSE`` / ``""``."""
    if value is True:
        return 'TRUE'
    if value is False:
        return 'FALSE'
    text = str(value or '').strip().lower()
    if text in ('true', '1', 'yes', 'y'):
        return 'TRUE'
    if text in ('false', '0', 'no', 'n'):
        return 'FALSE'
    return ''


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
