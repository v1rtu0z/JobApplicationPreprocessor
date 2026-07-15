"""Helpers for rendering individual job rows in the Jobs view."""

import math
from datetime import datetime

import pandas as pd


def format_date_added(value: str) -> str:
    """Format Date added (YYYY-MM-DD) for compact display in job card headers."""
    raw = (value or "").strip()
    if not raw:
        return ""
    try:
        dt = datetime.strptime(raw[:10], "%Y-%m-%d")
        return dt.strftime("%b %d, %Y")
    except ValueError:
        return raw[:10] if len(raw) >= 10 else raw


def get_row_value(row, col_name: str, column_index_map: dict, default: str = "") -> str:
    """Get value from itertuples row using column index map.
    itertuples(index=False) returns tuples where columns are in order.
    """
    if col_name not in column_index_map:
        return default
    col_idx = column_index_map[col_name]
    try:
        value = row[col_idx]
        if value is None:
            return default
        if isinstance(value, float) and math.isnan(value):
            return default
        try:
            if pd.isna(value):
                return default
        except (TypeError, ValueError):
            pass
        return str(value)
    except (IndexError, AttributeError, TypeError):
        return default
