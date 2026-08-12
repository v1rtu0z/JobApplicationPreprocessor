"""Regression tests: skip-keyword matching must be case-insensitive.

Mixed-case entries in location/company skip lists previously never matched,
because the keyword was compared as-written against a lower-cased string.
"""

import pytest

from pipeline.filtering import _apply_keyword_filters


def _filters(**overrides):
    base = {
        "job_title_skip_keywords": [],
        "job_title_skip_keywords_2": [],
        "company_skip_keywords": [],
        "location_skip_keywords": [],
    }
    base.update(overrides)
    return base


class TestLocationCaseInsensitive:
    # Locations chosen to pass the geo filter, so these tests isolate the
    # case-insensitivity of the location skip-keyword check.
    def test_mixed_case_location_keyword_matches(self):
        filters = _filters(location_skip_keywords=["Milan"])
        skip, reason = _apply_keyword_filters(
            "Backend Engineer", "Acme", "Milan, Italy", filters
        )
        assert skip is True
        assert reason == "Location not preferred"

    def test_lowercase_location_keyword_still_matches(self):
        filters = _filters(location_skip_keywords=["milan"])
        skip, _ = _apply_keyword_filters(
            "Backend Engineer", "Acme", "Milan, Italy", filters
        )
        assert skip is True

    def test_non_matching_location_not_filtered(self):
        filters = _filters(location_skip_keywords=["Milan"])
        skip, _ = _apply_keyword_filters(
            "Backend Engineer", "Acme", "Belgrade, Serbia", filters
        )
        assert skip is False


class TestCompanyCaseInsensitive:
    def test_mixed_case_company_keyword_matches(self):
        filters = _filters(company_skip_keywords=["Speechify"])
        skip, reason = _apply_keyword_filters(
            "Backend Engineer", "Speechify Inc", "Italy", filters
        )
        assert skip is True
        assert reason == "Company name contains unwanted keyword"

    def test_lowercase_company_keyword_still_matches(self):
        filters = _filters(company_skip_keywords=["speechify"])
        skip, _ = _apply_keyword_filters(
            "Backend Engineer", "Speechify Inc", "Italy", filters
        )
        assert skip is True

    def test_non_matching_company_not_filtered(self):
        filters = _filters(company_skip_keywords=["Speechify"])
        skip, _ = _apply_keyword_filters(
            "Backend Engineer", "Acme Corp", "Italy", filters
        )
        assert skip is False


class TestTitleCaseInsensitiveRegression:
    def test_mixed_case_title_keyword_matches_lowercase_title(self):
        filters = _filters(job_title_skip_keywords=["Voice Actor"])
        skip, reason = _apply_keyword_filters(
            "icelandic voice actor", "Acme", "Italy", filters
        )
        assert skip is True
        assert reason == "Job title contains unwanted technology"

    def test_mixed_case_title_word_keyword_matches(self):
        filters = _filters(job_title_skip_keywords_2=["SAP"])
        skip, _ = _apply_keyword_filters(
            "senior sap consultant", "Acme", "Italy", filters
        )
        assert skip is True
