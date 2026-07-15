#!/usr/bin/env python3
"""Small Apify job fetch for filter review — reports usage and filter pass/fail."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from config import _get_job_filters
from core.sources.apify_source import _normalize_apify_item
from local_storage import JobDatabase
from pipeline.collection import _normalized_to_row_data
from pipeline.filtering import _apply_keyword_filters, _apply_sustainability_keyword_filters, _normalize_job_title
from utils import SHEET_HEADER, get_existing_job_keys, apify_state
from utils.apify_client import fetch_jobs_via_apify, format_apify_usage, get_apify_usage_summary


def _usage_line(label: str, summary: dict) -> str:
    return f"{label}: {format_apify_usage(summary)}"


def run_probe_search(
    *,
    param_index: int,
    base_params: dict,
    limit: int,
    filters: dict,
    db: JobDatabase,
    existing: set[str],
) -> dict:
    """Fetch one Apify search, apply filters, insert new rows. Returns run stats."""
    params = dict(base_params)
    params["limit"] = limit

    print("\n" + "-" * 60)
    print(f"Search #{param_index}: keywords='{params.get('keywords')}' location='{params.get('location')}'")
    print(f"Limit: {limit}")

    raw_items = fetch_jobs_via_apify(params=params)
    if not raw_items:
        return {
            "param_index": param_index,
            "raw": 0,
            "duplicates": 0,
            "rejected": 0,
            "added": 0,
            "accepted": [],
            "rejected_samples": [],
            "fetch_ok": apify_state.is_available(),
        }

    accepted: list[tuple[str, str, str]] = []
    rejected: list[tuple[str, str, str]] = []
    duplicates: list[tuple[str, str]] = []
    new_rows = []
    date_idx = SHEET_HEADER.index("Date added")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for item in raw_items:
        norm = _normalize_apify_item(item)
        title = norm.get("job_title", "")
        company = norm.get("company_name", "")
        location = norm.get("location", "")
        job_key = f"{_normalize_job_title(title)} @ {company}"

        if job_key in existing:
            duplicates.append((title, company))
            continue

        skip, reason = _apply_keyword_filters(title, company, location, filters, norm.get("job_description", ""))
        if not skip:
            skip_sust, reason_sust, _ = _apply_sustainability_keyword_filters(
                title, company, location, "", filters
            )
            if skip_sust:
                skip, reason = True, reason_sust

        if skip:
            rejected.append((title, company, reason or "filtered"))
            continue

        row_data = _normalized_to_row_data(norm, filters)
        if not row_data:
            rejected.append((title, company, "normalized row rejected"))
            continue
        if not (row_data[date_idx] or "").strip():
            row_data[date_idx] = today
        new_rows.append(row_data)
        existing.add(job_key)
        accepted.append((title, company, location))

    if new_rows:
        db.append_rows(new_rows)

    print(f"  Raw: {len(raw_items)} | dupes: {len(duplicates)} | filtered: {len(rejected)} | added: {len(new_rows)}")
    for title, company, location in accepted[:10]:
        loc = f" ({location})" if location else ""
        print(f"    ✓ {title} @ {company}{loc}")
    for title, company, reason in rejected[:8]:
        print(f"    ✗ {title} @ {company} — {reason}")
    if len(rejected) > 8:
        print(f"    ... and {len(rejected) - 8} more filtered")

    return {
        "param_index": param_index,
        "raw": len(raw_items),
        "duplicates": len(duplicates),
        "rejected": len(rejected),
        "added": len(new_rows),
        "accepted": accepted,
        "rejected_samples": rejected[:15],
        "fetch_ok": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch a small batch of jobs via Apify for filter review.")
    parser.add_argument("--limit", type=int, default=20, help="Max jobs per search (default: 20)")
    parser.add_argument("--param", type=int, default=0, help="Index into job_preferences search_parameters")
    parser.add_argument("--all", action="store_true", help="Run --limit jobs for every saved search")
    parser.add_argument("--reset-apify-state", action="store_true", help="Clear persisted monthly-limit flag")
    args = parser.parse_args()

    if args.reset_apify_state:
        apify_state.reset()
        print("Reset local Apify availability state (cleared monthly-limit flag).")

    filters = _get_job_filters()
    params_list = filters.get("search_parameters") or []
    if not params_list:
        print("No search_parameters in job_preferences.yaml — run the pipeline once to generate them.")
        return 1

    if args.all:
        indices = list(range(len(params_list)))
    else:
        if args.param < 0 or args.param >= len(params_list):
            print(f"Invalid --param {args.param}; have {len(params_list)} parameter set(s).")
            return 1
        indices = [args.param]

    print("\n" + "=" * 60)
    print("APIFY PROBE FETCH")
    print("=" * 60)
    print(f"Searches: {len(indices)} | limit per search: {args.limit}")
    print(f"CHECK_SUSTAINABILITY: {__import__('os').getenv('CHECK_SUSTAINABILITY', 'false')}")
    print()

    before = get_apify_usage_summary()
    print(_usage_line("Before", before))

    db_path = ROOT / "local_data" / "jobs.db"
    db = JobDatabase(str(db_path), SHEET_HEADER)
    existing = get_existing_job_keys(db)

    totals = {"raw": 0, "duplicates": 0, "rejected": 0, "added": 0}
    run_stats = []
    for idx in indices:
        stats = run_probe_search(
            param_index=idx,
            base_params=params_list[idx],
            limit=args.limit,
            filters=filters,
            db=db,
            existing=existing,
        )
        run_stats.append(stats)
        if not stats["fetch_ok"] and stats["raw"] == 0:
            print("\nApify fetch failed — account may still be marked unavailable locally. Try --reset-apify-state.")
            return 1
        for key in totals:
            totals[key] += stats[key]

    print("\n" + "=" * 60)
    print("PROBE SUMMARY")
    print("=" * 60)
    for stats in run_stats:
        p = params_list[stats["param_index"]]
        print(
            f"  #{stats['param_index']} {p.get('keywords')} @ {p.get('location')}: "
            f"+{stats['added']} added, {stats['rejected']} filtered, {stats['duplicates']} dupes"
        )
    print(
        f"\nTotal: raw={totals['raw']} dupes={totals['duplicates']} "
        f"filtered={totals['rejected']} added={totals['added']}"
    )

    after = get_apify_usage_summary()
    print()
    print(_usage_line("After", after))
    if before and after:
        delta = after.get("total_usd", 0) - before.get("total_usd", 0)
        print(f"This run cost (approx): ${delta:.4f}")
    print("\nOpen the dashboard to review new jobs (sustainability filter is off).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
