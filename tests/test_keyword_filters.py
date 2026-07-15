"""Tests for job title keyword filtering."""

import pytest

from pipeline.filtering import (
    _apply_keyword_filters,
    _normalize_title_for_filter,
    _title_has_ai_ml_in_title,
    _title_is_senior_ml_specialist,
    _title_matches_junior_entry_nextjs,
    _title_should_filter_ml_seniority,
)


@pytest.fixture
def filters():
    return {
        "job_title_skip_keywords": [
            "Junior", "Entry Level", "entry level", "next.js", "nextjs", "next js",
        ],
        "job_title_skip_keywords_2": [],
        "company_skip_keywords": [],
        "location_skip_keywords": [],
    }


class TestTitleNormalization:
    def test_hyphens_become_spaces(self):
        assert _normalize_title_for_filter("Entry-Level Developer") == "entry level developer"


class TestJuniorEntryNextjsMatcher:
    def test_junior_ai_engineer(self):
        assert _title_matches_junior_entry_nextjs("Junior AI Engineer") is True

    def test_jr_word(self):
        assert _title_matches_junior_entry_nextjs("Jr Backend developer") is True

    def test_entry_level_hyphenated(self, filters):
        skip, reason = _apply_keyword_filters("Entry-Level SRE", "Acme", "Remote", filters)
        assert skip is True

    def test_junior_in_title(self, filters):
        skip, _ = _apply_keyword_filters("Junior AI Engineer", "Acme", "Remote", filters)
        assert skip is True

    def test_nextjs_in_title(self, filters):
        skip, _ = _apply_keyword_filters("Junior Next.js Developer", "Acme", "Remote", filters)
        assert skip is True

    def test_nextjs_standalone(self, filters):
        skip, _ = _apply_keyword_filters("Web Developer (Next.js)", "Acme", "Remote", filters)
        assert skip is True

    def test_senior_not_filtered(self, filters):
        skip, _ = _apply_keyword_filters("Senior Python Engineer", "Acme", "Remote", filters)
        assert skip is False

    def test_euronext_not_filtered_by_nextjs(self, filters):
        skip, _ = _apply_keyword_filters("Euronext Clearing Specialist", "Acme", "Remote", filters)
        assert skip is False

    def test_lead_engineer_not_blocked_by_skip_list(self, filters):
        skip, _ = _apply_keyword_filters("Lead Backend Engineer", "Acme", "Remote", filters)
        assert skip is False

    def test_staff_engineer_not_blocked(self, filters):
        skip, _ = _apply_keyword_filters("Staff Software Engineer", "Acme", "Remote", filters)
        assert skip is False

    def test_principal_engineer_not_blocked(self, filters):
        skip, _ = _apply_keyword_filters("Principal Python Engineer", "Acme", "Remote", filters)
        assert skip is False


class TestSeniorMlSpecialistMatcher:
    def test_senior_machine_learning_engineer(self):
        assert _title_should_filter_ml_seniority("Senior Machine Learning Engineer") is True

    def test_senior_ml_pipe_title(self):
        assert _title_should_filter_ml_seniority(
            "Senior Machine Learning Engineer | Python | PyTorch | RAG"
        ) is True

    def test_plain_ml_engineer_not_filtered(self, filters):
        assert _title_should_filter_ml_seniority("Machine Learning Engineer- (100% Remote)") is False
        skip, _ = _apply_keyword_filters("Machine Learning Engineer", "Acme", "Italy", filters)
        assert skip is False

    def test_junior_ml_not_filtered(self):
        assert _title_should_filter_ml_seniority("Junior Machine Learning Engineer") is False

    def test_medior_ml_not_filtered(self):
        assert _title_should_filter_ml_seniority("Medior ML Engineer") is False

    def test_senior_backend_with_ai_mention_not_filtered(self, filters):
        skip, _ = _apply_keyword_filters(
            "Senior Software Engineer - Python, AI (Perm, Italy)", "Acme", "Italy", filters
        )
        assert skip is False

    def test_senior_artificial_intelligence_not_filtered(self, filters):
        assert _title_should_filter_ml_seniority("Senior Artificial Intelligence Engineer") is False
        skip, _ = _apply_keyword_filters(
            "Senior Artificial Intelligence Engineer", "Acme", "Italy", filters
        )
        assert skip is False

    def test_senior_ai_ml_in_title_not_filtered(self):
        assert _title_has_ai_ml_in_title("Senior AI/ML Engineer") is True
        assert _title_should_filter_ml_seniority("Senior AI/ML Engineer") is False

    def test_staff_ai_ml_in_title_not_filtered(self):
        assert _title_should_filter_ml_seniority("Staff AI ML Engineer") is False

    def test_staff_ml_engineer_filtered(self):
        assert _title_should_filter_ml_seniority("Staff Machine Learning Engineer") is True
        assert _title_is_senior_ml_specialist("Staff Machine Learning Engineer") is True

    def test_lead_ml_engineer_filtered(self):
        assert _title_should_filter_ml_seniority("Lead Machine Learning Engineer") is True

    def test_lead_ai_engineer_passes_keyword_filter(self, filters):
        skip, _ = _apply_keyword_filters("Lead AI Engineer", "Acme", "Italy", filters)
        assert skip is False

    def test_lead_agentic_passes_keyword_filter(self, filters):
        skip, _ = _apply_keyword_filters("Lead Agentic Engineer", "Acme", "Italy", filters)
        assert skip is False

    def test_founding_ai_engineer_not_filtered(self):
        assert _title_should_filter_ml_seniority("Founding AI Software Engineer") is False


class TestGeoFiltersInKeywordPipeline:
    def test_us_location_filtered(self, filters):
        skip, reason = _apply_keyword_filters(
            "Senior Python Engineer", "Acme", "San Francisco, CA, United States", filters
        )
        assert skip is True
        assert "EMEA" in reason

    def test_singapore_filtered(self, filters):
        skip, reason = _apply_keyword_filters(
            "Backend Engineer", "Acme", "Singapore", filters
        )
        assert skip is True
        assert "EMEA" in reason

    def test_italy_passes(self, filters):
        skip, _ = _apply_keyword_filters("Senior Python Engineer", "Acme", "Italy", filters)
        assert skip is False

    def test_uk_hybrid_filtered(self, filters):
        skip, reason = _apply_keyword_filters(
            "Backend Engineer", "Acme", "London, England, United Kingdom (Hybrid)", filters
        )
        assert skip is True
        assert "globally remote" in reason.lower()

    def test_uk_worldwide_remote_passes(self, filters):
        skip, _ = _apply_keyword_filters(
            "Backend Engineer", "Acme", "Remote worldwide, United Kingdom", filters
        )
        assert skip is False

    def test_apac_filtered(self, filters):
        skip, reason = _apply_keyword_filters(
            "Lead Backend Engineer", "Acme", "APAC", filters
        )
        assert skip is True
        assert "EMEA" in reason

    def test_south_africa_filtered(self, filters):
        skip, reason = _apply_keyword_filters(
            "Backend Lead Engineer", "Acme", "South Africa", filters
        )
        assert skip is True
        assert "EMEA" in reason


class TestRemovedLevelKeywordRestore:
    def test_detects_lead_only_match(self):
        from pipeline.filtering import _was_filtered_only_by_removed_level_keywords

        assert _was_filtered_only_by_removed_level_keywords("Lead Backend Engineer") is True

    def test_devops_still_blocks_restore(self):
        from pipeline.filtering import _was_filtered_only_by_removed_level_keywords

        assert _was_filtered_only_by_removed_level_keywords("Lead DevOps Engineer") is False


class TestAncientNonSweExpiry:
    def test_non_swe_structural(self):
        from pipeline.filtering import _title_looks_non_swe, _title_looks_swe

        assert _title_looks_non_swe("Lead Structural Engineer") is True
        assert _title_looks_swe("Lead Structural Engineer") is False

    def test_swe_lead_backend(self):
        from pipeline.filtering import _title_looks_non_swe, _title_looks_swe

        assert _title_looks_swe("Lead Backend Engineer") is True
        assert _title_looks_non_swe("Lead Backend Engineer") is False

    def test_solutions_engineer_non_swe(self):
        from pipeline.filtering import _title_looks_non_swe

        assert _title_looks_non_swe("Principal Solutions Engineer") is True

    def test_ultra_ancient_even_if_swe(self):
        from pipeline.filtering import _job_is_ancient

        row = {"_id": 500, "Date added": "", "Job Title": "Staff Backend Engineer"}
        assert _job_is_ancient(row) is True

    def test_pre_probe_swe_not_ancient(self):
        from pipeline.filtering import _job_is_ancient

        row = {"_id": 1500, "Date added": "", "Job Title": "Lead Software Engineer"}
        assert _job_is_ancient(row) is False


class TestAddCompanySkipKeyword:
    def test_adds_normalized_company(self, tmp_path, monkeypatch):
        yaml_path = tmp_path / "job_preferences.yaml"
        yaml_path.write_text("company_skip_keywords:\n- existing\n", encoding="utf-8")
        monkeypatch.setattr("config.CONFIG_FILE", str(yaml_path))

        from config import add_company_skip_keyword, _get_job_filters

        assert add_company_skip_keyword("Speechify") is True
        assert add_company_skip_keyword("speechify") is False
        keywords = [k.lower() for k in _get_job_filters()["company_skip_keywords"]]
        assert "speechify" in keywords
        assert "existing" in keywords
