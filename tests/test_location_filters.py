"""Tests for EMEA / UK geographic filters."""

from pipeline.filtering import _apply_keyword_filters, _title_has_ai_ml_in_title
from pipeline.location_filters import (
    apply_geo_filters,
    apply_local_country_filters,
    is_globally_remote,
    is_outside_emea,
    is_uk_location,
    local_country_not_fully_remote,
    requires_local_language,
    should_skip_incompatible_timezone,
    should_skip_uk_not_globally_remote,
)


class TestOutsideEmea:
    def test_us(self):
        assert is_outside_emea("San Francisco, CA, United States") is True

    def test_singapore(self):
        assert is_outside_emea("Singapore") is True

    def test_italy(self):
        assert is_outside_emea("Italy") is False

    def test_emea_scope_wins_over_us_marker(self):
        assert is_outside_emea("Remote - EMEA", "Backend Engineer") is False

    def test_santiago_chile(self):
        assert is_outside_emea("Santiago Metropolitan Area") is True

    def test_apac(self):
        assert is_outside_emea("APAC") is True


class TestUkGlobalRemote:
    def test_detects_uk(self):
        assert is_uk_location("London, England, United Kingdom") is True

    def test_hybrid_uk_skipped(self):
        assert should_skip_uk_not_globally_remote(
            "London, England, United Kingdom (Hybrid)"
        ) is True

    def test_uk_worldwide_remote_ok(self):
        assert should_skip_uk_not_globally_remote(
            "Remote worldwide, United Kingdom"
        ) is False

    def test_plain_remote_ok(self):
        assert is_globally_remote("Remote", "") is True

    def test_uk_only_remote_skipped(self):
        assert should_skip_uk_not_globally_remote("Remote, United Kingdom") is True

    def test_apply_geo_uk_office(self):
        skip, reason = apply_geo_filters("London, England, United Kingdom", "Backend Engineer")
        assert skip is True
        assert reason == "UK posting is not globally remote"


class TestLocalCountryFilters:
    def test_germany_hybrid_blocked(self):
        skip, reason = apply_local_country_filters("Munich, Bavaria, Germany (Hybrid)", "Backend Engineer")
        assert skip is True
        assert "Not fully remote" in reason

    def test_germany_remote_ok(self):
        skip, _ = apply_local_country_filters("Remote, Germany", "Backend Engineer")
        assert skip is False

    def test_germany_fluent_german_blocked(self):
        skip, reason = apply_local_country_filters(
            "Remote, Germany",
            "Backend Engineer",
            "Must have fluent German and English.",
        )
        assert skip is True
        assert "local language" in reason.lower()

    def test_spain_office_blocked(self):
        not_remote, _ = local_country_not_fully_remote("Madrid, Spain", "Engineer")
        assert not_remote is True

    def test_serbia_not_subject_to_local_language_filter(self):
        skip, _ = apply_local_country_filters("Belgrade, Serbia", "Backend Engineer", "Fluent Serbian")
        assert skip is False


class TestWorldwideTimezone:
    def test_worldwide_us_hours_blocked(self):
        skip, reason = apply_geo_filters("Remote worldwide", "Backend Engineer - EST hours only")
        assert skip is True
        assert "timezone" in reason.lower()

    def test_worldwide_emea_ok(self):
        skip, _ = apply_geo_filters("Remote worldwide", "Backend Engineer - EMEA timezone")
        assert skip is False

    def test_us_location_worldwide_title_not_blocked_by_emea(self):
        skip, _ = apply_geo_filters("Remote worldwide", "Senior Python Engineer")
        assert skip is False

    def test_incompatible_timezone_helper(self):
        assert should_skip_incompatible_timezone("Remote worldwide", "PST only") is True


class TestLeadAiAcceptance:
    def test_lead_ai_in_title(self):
        assert _title_has_ai_ml_in_title("Lead AI Engineer") is True

    def test_lead_ai_not_blocked(self):
        filters = {
            "job_title_skip_keywords": ["Lead AI Engineer", "DevOps"],
            "job_title_skip_keywords_2": [],
            "company_skip_keywords": [],
            "location_skip_keywords": [],
        }
        skip, _ = _apply_keyword_filters("Lead AI Engineer", "Acme", "Italy", filters)
        assert skip is False

    def test_lead_agentic_not_blocked(self):
        filters = {
            "job_title_skip_keywords": ["Lead Agentic", "DevOps"],
            "job_title_skip_keywords_2": [],
            "company_skip_keywords": [],
            "location_skip_keywords": [],
        }
        skip, _ = _apply_keyword_filters("Lead Agentic AI Engineer", "Acme", "Italy", filters)
        assert skip is False
