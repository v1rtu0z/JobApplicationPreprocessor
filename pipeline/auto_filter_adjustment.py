"""Automatic filter adjustment when enough Good fit / Very good fit jobs are found."""

from collections import Counter
from copy import deepcopy
from datetime import datetime

from config import _get_job_filters, _save_job_filters


GOOD_FIT_SCORES = ("Good fit", "Very good fit")
MAX_NEW_LOCATIONS = 5
PRIORITY_FOR_NEW = 1


def maybe_auto_adjust_filters(sheet) -> bool:
    """
    If enabled and good-fit job count >= threshold, add top locations from those jobs
    to location_priorities and save. Stores previous state for revert. Returns True if adjusted.
    """
    filters = _get_job_filters()
    adj = filters.get("auto_filter_adjustment") or {}
    if not adj.get("enabled", False):
        return False
    try:
        threshold = int(adj.get("good_fit_threshold", 5))
    except (TypeError, ValueError):
        threshold = 5
    if threshold <= 0:
        return False

    records = sheet.get_all_records()
    good_fit = [
        r for r in records
        if (r.get("Fit score") or "").strip() in GOOD_FIT_SCORES
    ]
    if len(good_fit) < threshold:
        return False

    location_priorities = dict(filters.get("location_priorities") or {})
    existing_lower = {k.strip().lower() for k in location_priorities if k and str(k).strip()}

    # Count locations from good-fit jobs (normalize: strip, use as key)
    location_counts = Counter()
    for r in good_fit:
        loc = (r.get("Location") or "").strip()
        if not loc:
            continue
        location_counts[loc] += 1

    added = []
    for loc, _ in location_counts.most_common(MAX_NEW_LOCATIONS):
        if loc.lower() in existing_lower:
            continue
        if len(added) >= MAX_NEW_LOCATIONS:
            break
        location_priorities[loc] = PRIORITY_FOR_NEW
        existing_lower.add(loc.lower())
        added.append(loc)

    if not added:
        return False

    # Backup only location_priorities for revert (keeps YAML small)
    previous_loc = deepcopy(location_priorities)
    # Revert restores from the state *before* we added new locations
    for loc in added:
        previous_loc.pop(loc, None)

    filters["location_priorities"] = location_priorities
    if "auto_filter_adjustment" not in filters:
        filters["auto_filter_adjustment"] = {}
    filters["auto_filter_adjustment"]["last_run"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    filters["auto_filter_adjustment"]["previous_location_priorities"] = previous_loc

    _save_job_filters(filters)
    print(f"\nAuto-adjusted filters: added {len(added)} location(s) from {len(good_fit)} good-fit jobs: {added}")
    return True


def revert_auto_adjustment() -> bool:
    """Restore location_priorities from before last auto-adjustment. Returns True if reverted."""
    filters = _get_job_filters()
    adj = filters.get("auto_filter_adjustment") or {}
    previous_loc = adj.get("previous_location_priorities")
    if not previous_loc or not isinstance(previous_loc, dict):
        return False
    enabled = adj.get("enabled", False)
    threshold = adj.get("good_fit_threshold", 5)
    filters["location_priorities"] = deepcopy(previous_loc)
    filters["auto_filter_adjustment"] = {
        "enabled": enabled,
        "good_fit_threshold": threshold,
    }
    _save_job_filters(filters)
    return True
