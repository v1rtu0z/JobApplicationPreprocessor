"""Unit tests for DataSource implementations (normalization only, no live API)."""

import pytest

from core.sources.base import DataSource
from core.sources.apify_source import ApifyDataSource, _normalize_apify_item
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


class TestFactory:
    def test_create_data_source_apify(self):
        src = create_data_source("apify")
        assert isinstance(src, ApifyDataSource)

    def test_create_data_source_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown data source"):
            create_data_source("linkedin")

    def test_create_repository(self):
        class S:
            def get_all_records(self):
                return []
        repo = create_repository(S())
        assert repo.get_all_records() == []
