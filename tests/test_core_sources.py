"""Unit tests for DataSource implementations (normalization only, no live API)."""

import pytest

from core.sources.base import DataSource
from core.sources.apify_source import ApifyDataSource, _normalize_apify_item
from core.sources.linkedin_source import _normalize_linkedin_job_obj
from core.factory import create_data_source, create_repository


class TestApifyNormalization:
    def test_normalize_apify_item(self):
        item = {
            "job_title": "Software Engineer",
            "company": "Acme Inc",
            "job_url": "https://linkedin.com/jobs/123",
            "location": "Remote",
            "description": "Build things.",
        }
        out = _normalize_apify_item(item)
        assert out["job_title"] == "Software Engineer"
        assert out["company_name"] == "Acme Inc"
        assert out["job_url"] == "https://linkedin.com/jobs/123"
        assert out["location"] == "Remote"
        assert out["job_description"] == "Build things."

    def test_normalize_apify_alternate_keys(self):
        item = {
            "title": "Dev",
            "company_name": "Corp",
            "url": "https://u",
            "jobDescriptionText": "JD here",
        }
        out = _normalize_apify_item(item)
        assert out["job_title"] == "Dev"
        assert out["company_name"] == "Corp"
        assert out["job_url"] == "https://u"
        assert out["job_description"] == "JD here"


class TestLinkedInNormalization:
    def test_normalize_job_obj_minimal(self):
        class Obj:
            job_title = "Engineer"
            company = "Acme"
            linkedin_url = "https://u"
            location = "NYC"
        out = _normalize_linkedin_job_obj(Obj())
        assert out is not None
        assert out["job_title"] == "Engineer"
        assert out["company_name"] == "Acme"
        assert out["job_url"] == "https://u"
        assert out["location"] == "NYC"
        assert out["job_description"] == ""

    def test_normalize_job_obj_missing_url_returns_none(self):
        class Obj:
            job_title = "E"
            company = "C"
            linkedin_url = ""
            location = ""
        assert _normalize_linkedin_job_obj(Obj()) is None


class TestFactory:
    def test_create_data_source_apify(self):
        src = create_data_source("apify")
        assert isinstance(src, ApifyDataSource)

    def test_create_data_source_linkedin(self):
        from core.sources import LinkedInDataSource
        src = create_data_source("linkedin")
        assert isinstance(src, LinkedInDataSource)

    def test_create_data_source_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown data source"):
            create_data_source("unknown")

    def test_create_repository(self):
        class S:
            def get_all_records(self):
                return []
        repo = create_repository(S())
        assert repo.get_all_records() == []
