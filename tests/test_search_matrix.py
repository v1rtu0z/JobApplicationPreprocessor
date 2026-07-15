"""Tests for search_matrix → search_parameters expansion."""

from config import expand_search_matrix, _get_job_filters


def test_cartesian_product_count():
    matrix = {
        "keywords": ["A", "B"],
        "locations": ["X", "Y", "Z"],
        "defaults": {"remote": "remote", "limit": 50},
    }
    params = expand_search_matrix(matrix)
    assert len(params) == 6
    assert params[0] == {
        "remote": "remote",
        "limit": 50,
        "date_posted": "week",
        "experienceLevel": "mid_senior",
        "sort": "recent",
        "keywords": "A",
        "location": "X",
    }


def test_month_overrides():
    matrix = {
        "keywords": ["AI Engineer", "Backend Engineer"],
        "locations": ["Italy", "Serbia"],
        "month_date_posted_keywords": ["AI Engineer"],
        "month_date_posted_locations": ["Serbia"],
    }
    params = expand_search_matrix(matrix)
    by_key = {(p["keywords"], p["location"]): p["date_posted"] for p in params}
    assert by_key[("AI Engineer", "Italy")] == "month"
    assert by_key[("AI Engineer", "Serbia")] == "month"
    assert by_key[("Backend Engineer", "Italy")] == "week"
    assert by_key[("Backend Engineer", "Serbia")] == "month"


def test_job_preferences_expands_to_54():
    filters = _get_job_filters()
    params = filters.get("search_parameters") or []
    assert len(params) == 54
    keywords = {p["keywords"] for p in params}
    locations = {p["location"] for p in params}
    assert len(keywords) == 6
    assert len(locations) == 9
