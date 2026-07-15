"""Tests for JD fit score parsing/formatting."""

import math

import pandas as pd
import pytest

from utils.jd_fit import format_jd_fit_score, parse_jd_fit_score


@pytest.mark.parametrize(
    "value,expected",
    [
        ("8", 8),
        (8, 8),
        (8.6, 9),
        ("", None),
        (None, None),
        ("nan", None),
        ("NaN", None),
        (float("nan"), None),
        (pd.NA, None),
        ("0", None),
        ("11", None),
        ("not-a-number", None),
    ],
)
def test_parse_jd_fit_score(value, expected):
    assert parse_jd_fit_score(value) == expected


def test_format_jd_fit_score():
    assert format_jd_fit_score("7") == "7"
    assert format_jd_fit_score(float("nan")) == ""
    assert format_jd_fit_score("nan") == ""
    assert format_jd_fit_score(None) == ""


def test_get_row_value_handles_nan():
    from dashboard.job_cards import get_row_value

    column_index_map = {"JD fit score": 0}
    row = (float("nan"),)
    assert get_row_value(row, "JD fit score", column_index_map, default="") == ""
    assert math.isnan(row[0])
