"""Dashboard default filter — shared between pipeline and Streamlit (no Streamlit imports)."""

from __future__ import annotations

from .constants import CHECK_SUSTAINABILITY

# Matches dashboard default fit multiselect (excludes poor/questionable/moderate fits).
DEFAULT_EXCLUDED_FIT_SCORES = frozenset(
    {"Poor fit", "Very poor fit", "Questionable fit", "Moderate fit"}
)


def row_passes_default_dashboard_filter(row: dict) -> bool:
    """True when a job row matches the dashboard's default sidebar filter."""
    if row.get("Applied") == "TRUE":
        return False
    if row.get("Job posting expired") == "TRUE":
        return False
    if row.get("Bad analysis") == "TRUE":
        return False

    fit = (row.get("Fit score") or "").strip()
    if fit and fit in DEFAULT_EXCLUDED_FIT_SCORES:
        return False

    if CHECK_SUSTAINABILITY:
        sustainable = (row.get("Sustainable company") or "").strip().upper()
        if sustainable == "FALSE":
            return False

    return bool((row.get("Job URL") or "").strip() and (row.get("Company Name") or "").strip())


def default_dashboard_job_keys(db) -> set[tuple[str, str]]:
    """Return (job_url, company_name) keys visible under dashboard default filters."""
    keys: set[tuple[str, str]] = set()
    for row in db.get_all_records():
        if not row_passes_default_dashboard_filter(row):
            continue
        keys.add((row.get("Job URL", "").strip(), row.get("Company Name", "").strip()))
    return keys


def default_dashboard_mask(df):
    """Vectorized boolean mask (pandas Series) — same semantics as row_passes_default_dashboard_filter.

    Single source of truth: the dashboard UI's "Apply defaults" and the backend automation scope
    (Telegram prompts, JD-fit idle detection, final pipeline pass) must always agree on which jobs
    are "in scope". Import this instead of re-deriving the same conditions with pandas masks.
    """
    return df.apply(lambda row: row_passes_default_dashboard_filter(row.to_dict()), axis=1)
