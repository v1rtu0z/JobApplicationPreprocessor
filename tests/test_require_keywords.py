"""Tests for positive keyword/technology targeting (require-keyword filters)."""

import pytest

from pipeline.filtering import _apply_keyword_filters, _require_keywords_matched


def _filters(**overrides):
    """Baseline filters dict with all keyword lists empty, plus any overrides."""
    base = {
        "job_title_skip_keywords": [],
        "job_title_skip_keywords_2": [],
        "company_skip_keywords": [],
        "location_skip_keywords": [],
        "job_title_require_keywords": [],
        "job_require_keywords": [],
    }
    base.update(overrides)
    return base


class TestRequireKeywordsDisabled:
    def test_empty_lists_keep_everything(self):
        skip, reason = _apply_keyword_filters(
            "Marketing Coordinator", "Acme", "Italy", _filters()
        )
        assert skip is False
        assert reason is None

    def test_missing_keys_are_backward_compatible(self):
        # A filters dict without the require keys at all must not filter anything.
        filters = {
            "job_title_skip_keywords": [],
            "job_title_skip_keywords_2": [],
            "company_skip_keywords": [],
            "location_skip_keywords": [],
        }
        skip, _ = _apply_keyword_filters("Anything Goes", "Acme", "Italy", filters)
        assert skip is False


class TestTitleRequireKeywords:
    def test_title_matches_required_keyword_kept(self):
        filters = _filters(job_title_require_keywords=["python", "backend"])
        skip, _ = _apply_keyword_filters(
            "Senior Python Engineer", "Acme", "Italy", filters
        )
        assert skip is False

    def test_title_missing_required_keyword_filtered(self):
        filters = _filters(job_title_require_keywords=["python", "backend"])
        skip, reason = _apply_keyword_filters(
            "Senior Java Engineer", "Acme", "Italy", filters
        )
        assert skip is True
        assert reason == "Job does not match required keywords"

    def test_case_insensitive_match(self):
        filters = _filters(job_title_require_keywords=["Python"])
        skip, _ = _apply_keyword_filters(
            "senior python engineer", "Acme", "Italy", filters
        )
        assert skip is False


class TestDescriptionRequireKeywords:
    def test_description_match_keeps_job(self):
        filters = _filters(job_require_keywords=["kubernetes"])
        skip, _ = _apply_keyword_filters(
            "Platform Engineer",
            "Acme",
            "Italy",
            filters,
            job_description="We run workloads on Kubernetes and Postgres.",
        )
        assert skip is False

    def test_description_no_match_filtered(self):
        filters = _filters(job_require_keywords=["kubernetes"])
        skip, reason = _apply_keyword_filters(
            "Platform Engineer",
            "Acme",
            "Italy",
            filters,
            job_description="We run everything on bare-metal servers.",
        )
        assert skip is True
        assert reason == "Job does not match required keywords"

    def test_description_keyword_also_matches_title(self):
        # job_require_keywords searches title + description, so a title hit suffices.
        filters = _filters(job_require_keywords=["rust"])
        skip, _ = _apply_keyword_filters(
            "Rust Engineer", "Acme", "Italy", filters, job_description=""
        )
        assert skip is False


class TestSkipWinsOverRequire:
    def test_skip_keyword_beats_require_keyword(self):
        filters = _filters(
            job_title_skip_keywords=["manager"],
            job_title_require_keywords=["engineer"],
        )
        # Title matches a require keyword ("engineer") but also a skip keyword.
        skip, reason = _apply_keyword_filters(
            "Engineering Manager", "Acme", "Italy", filters
        )
        assert skip is True
        assert reason == "Job title contains unwanted technology"


class TestHelperDirectly:
    def test_no_lists_returns_matched(self):
        matched, reason = _require_keywords_matched("Anything", "", _filters())
        assert matched is True
        assert reason is None

    def test_either_list_can_satisfy_match(self):
        filters = _filters(
            job_title_require_keywords=["python"],
            job_require_keywords=["rust"],
        )
        # Title matches the title-list only -> kept.
        matched, _ = _require_keywords_matched("Python Developer", "", filters)
        assert matched is True
        # Description matches the desc-list only -> kept.
        matched, _ = _require_keywords_matched(
            "Backend Developer", "We use Rust heavily", filters
        )
        assert matched is True
        # Neither list matches -> filtered.
        matched, reason = _require_keywords_matched(
            "Backend Developer", "We use Go", filters
        )
        assert matched is False
        assert reason == "Job does not match required keywords"
