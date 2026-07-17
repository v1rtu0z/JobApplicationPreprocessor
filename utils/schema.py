"""Job table schema and column definitions."""

from datetime import datetime, timezone

JOB_COLUMNS = [
    'Company Name', 'Job Title', 'Location', 'Location Priority', 'Job Description', 'Job URL', 'Company URL',
    'Company overview', 'Sustainable company', 'Sustainability keyword matches', 'CO fetch attempted', 'JD crawl attempted',
    'Fit score', 'Fit score enum', 'JD fit score', 'JD fit reasoning', 'Bulk filtered', 'Job analysis', 'Tailored resume url', 'Tailored resume json',
    'Resume feedback',
    'Resume feedback addressed', 'Tailored cover letter (to be humanized)', 'CL feedback',
    'CL feedback addressed', 'Applied', 'Applied at', 'Bad analysis', 'Bad analysis reported at',
    'Job posting expired', 'Expired at', 'Date added', 'Date posted', 'Easy apply', 'Last expiration check',
    'Telegram notified', 'Telegram app completed'
]

# Flag column → timestamp column written when the flag changes.
# TODO: Refactor Applied / Bad analysis / Job posting expired (and these timestamps)
# into event objects with timestamps later on (append-only event log / history).
STATUS_TIMESTAMP_FIELDS = {
    'Applied': 'Applied at',
    'Bad analysis': 'Bad analysis reported at',
    'Job posting expired': 'Expired at',
}


def utc_now_iso() -> str:
    """UTC timestamp string for status event columns (ISO-8601, Z suffix)."""
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def with_status_timestamps(updates: dict) -> dict:
    """Attach or clear timestamp columns when status flags are present in *updates*.

    When a flag is set to TRUE, its companion ``* at`` column is stamped with now.
    When the flag is cleared (FALSE / empty), the companion timestamp is cleared.
    Flags not present in *updates* are left alone.
    """
    out = dict(updates)
    now = None
    for flag, ts_col in STATUS_TIMESTAMP_FIELDS.items():
        if flag not in out:
            continue
        val = (out.get(flag) or '').strip().upper()
        if val == 'TRUE':
            if now is None:
                now = utc_now_iso()
            out[ts_col] = now
        else:
            out[ts_col] = ''
    return out
