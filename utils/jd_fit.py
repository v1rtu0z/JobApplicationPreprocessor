"""Helpers for parsing and formatting JD-only fit scores (1-10)."""

from __future__ import annotations

import math

import pandas as pd


def parse_jd_fit_score(value) -> int | None:
    """Return integer 1-10, or None for missing/invalid/NaN values."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    text = str(value).strip().lower()
    if not text or text in {"nan", "none", "<na>", "null"}:
        return None

    try:
        score = int(round(float(text)))
    except (TypeError, ValueError):
        return None

    if 1 <= score <= 10:
        return score
    return None


def format_jd_fit_score(value) -> str:
    """Return a display string like '8', or '' when no valid score exists."""
    score = parse_jd_fit_score(value)
    return str(score) if score is not None else ""
