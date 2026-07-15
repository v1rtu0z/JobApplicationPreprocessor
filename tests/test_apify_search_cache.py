"""Tests for Apify job-search request cache and integration."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
import yaml

from utils.apify_client import (
    _build_apify_jobs_run_input,
    apify_jobs_search_is_cached,
    apify_state,
    fetch_jobs_via_apify,
)
from utils.apify_search_cache import (
    APIFY_SEARCH_CACHE_TTL_DAYS,
    get_search_cache,
    mark_apify_search_fetched,
    normalize_run_input,
    search_fingerprint,
    should_skip_apify_search,
)


@pytest.fixture
def isolated_job_filters(tmp_path, monkeypatch):
    config_path = tmp_path / "job_preferences.yaml"
    config_path.write_text("search_parameters: []\napify_search_cache: {}\n", encoding="utf-8")
    monkeypatch.setattr("config.CONFIG_FILE", str(config_path))
    return config_path


@pytest.fixture(autouse=True)
def reset_apify_state():
    apify_state.reset()
    yield
    apify_state.reset()


@pytest.fixture
def no_rate_limit(monkeypatch):
    monkeypatch.setattr("utils.apify_client.rate_limit", lambda: None)


SAMPLE_PARAMS = {
    "keywords": "Python Engineer",
    "location": "Remote",
    "remote": "remote",
    "experienceLevel": "mid_senior",
    "sort": "recent",
    "date_posted": "week",
    "limit": 100,
}


class TestApifySearchCacheCore:
    def test_normalize_run_input_applies_defaults(self):
        out = normalize_run_input({"keywords": "Python", "location": "Remote"})
        assert out["keywords"] == "Python"
        assert out["location"] == "Remote"
        assert out["sort"] == ""
        assert out["limit"] == 100
        assert out["page"] == 1

    def test_search_fingerprint_stable_and_page_sensitive(self):
        base = {
            "keywords": "Python",
            "location": "Remote",
            "remote": "remote",
            "experienceLevel": "mid_senior",
            "sort": "recent",
            "date_posted": "week",
            "easy_apply": "",
            "limit": 100,
            "page": 1,
        }
        assert search_fingerprint(base) == search_fingerprint(dict(base))
        page_two = dict(base, page=2)
        assert search_fingerprint(base) != search_fingerprint(page_two)

    def test_should_skip_within_ttl(self, isolated_job_filters):
        run_input = normalize_run_input(SAMPLE_PARAMS)
        now = datetime(2026, 6, 6, tzinfo=timezone.utc)
        mark_apify_search_fetched(run_input, fetched_at=now - timedelta(days=3))

        assert should_skip_apify_search(run_input, now=now) is True

    def test_should_not_skip_after_ttl(self, isolated_job_filters):
        run_input = normalize_run_input(SAMPLE_PARAMS)
        now = datetime(2026, 6, 6, tzinfo=timezone.utc)
        mark_apify_search_fetched(run_input, fetched_at=now - timedelta(days=APIFY_SEARCH_CACHE_TTL_DAYS))

        assert should_skip_apify_search(run_input, now=now) is False

    def test_mark_prunes_expired_entries(self, isolated_job_filters):
        old_input = normalize_run_input({"keywords": "Old", "location": "Remote"})
        new_input = normalize_run_input({"keywords": "New", "location": "Remote"})
        now = datetime(2026, 6, 6, tzinfo=timezone.utc)
        mark_apify_search_fetched(old_input, fetched_at=now - timedelta(days=20))
        mark_apify_search_fetched(new_input, fetched_at=now)

        assert should_skip_apify_search(old_input, now=now) is False
        assert should_skip_apify_search(new_input, now=now) is True
        assert len(get_search_cache()) == 1

    def test_mark_persists_to_job_preferences_yaml(self, isolated_job_filters):
        run_input = normalize_run_input(SAMPLE_PARAMS)
        mark_apify_search_fetched(run_input, fetched_at=datetime(2026, 6, 6, tzinfo=timezone.utc))

        with open(isolated_job_filters, encoding="utf-8") as handle:
            saved = yaml.safe_load(handle)

        fingerprint = search_fingerprint(run_input)
        assert fingerprint in saved["apify_search_cache"]


class TestBuildApifyJobsRunInput:
    def test_build_from_params(self):
        run_input = _build_apify_jobs_run_input(params=SAMPLE_PARAMS)
        assert run_input["keywords"] == "Python Engineer"
        assert run_input["location"] == "Remote"
        assert run_input["sort"] == "recent"
        assert run_input["date_posted"] == "week"
        assert run_input["limit"] == 100
        assert run_input["page"] == 1

    def test_build_from_search_url(self):
        search_url = (
            "https://www.linkedin.com/jobs/search/?keywords=Data%20Engineer"
            "&geoId=Remote&f_WT=2&f_E=4&sortBy=DD&f_TPR=r604800&page=2"
        )
        run_input = _build_apify_jobs_run_input(search_url=search_url)
        assert run_input["keywords"] == "Data Engineer"
        assert run_input["location"] == "Remote"
        assert run_input["remote"] == "remote"
        assert run_input["experienceLevel"] == "mid_senior"
        assert run_input["sort"] == "recent"
        assert run_input["date_posted"] == "week"
        assert run_input["page"] == "2"

    def test_apify_jobs_search_is_cached_reflects_ttl(self, isolated_job_filters):
        assert apify_jobs_search_is_cached(params=SAMPLE_PARAMS) is False

        mark_apify_search_fetched(_build_apify_jobs_run_input(params=SAMPLE_PARAMS))
        assert apify_jobs_search_is_cached(params=SAMPLE_PARAMS) is True


class TestFetchJobsViaApifyCache:
    def test_skips_apify_call_when_cached(self, isolated_job_filters, no_rate_limit, monkeypatch):
        mark_apify_search_fetched(_build_apify_jobs_run_input(params=SAMPLE_PARAMS))
        mock_client = MagicMock()
        monkeypatch.setattr("utils.apify_client.ApifyClient", mock_client)
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")

        items = fetch_jobs_via_apify(params=SAMPLE_PARAMS)

        assert items == []
        mock_client.assert_not_called()

    def test_calls_apify_and_marks_cache_on_success(
        self, isolated_job_filters, no_rate_limit, monkeypatch
    ):
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")

        fake_items = [{"job_title": "Engineer", "company": "Acme", "job_url": "https://example.com/j/1"}]

        class FakeDataset:
            def iterate_items(self):
                return iter(fake_items)

        class FakeActor:
            def call(self, run_input=None):
                self.last_run_input = run_input
                return {"defaultDatasetId": "ds1", "defaultKeyValueStoreId": "kvs1"}

        captured = {}

        class FakeClient:
            def __init__(self, token):
                self.token = token
                self.actor_obj = FakeActor()

            def actor(self, name):
                assert name == "apimaestro/linkedin-jobs-scraper-api"
                return self.actor_obj

            def dataset(self, dataset_id):
                assert dataset_id == "ds1"
                return FakeDataset()

        def fake_client_factory(token):
            client = FakeClient(token)
            captured["client"] = client
            return client

        monkeypatch.setattr("utils.apify_client.ApifyClient", fake_client_factory)

        items = fetch_jobs_via_apify(params=SAMPLE_PARAMS)

        assert items == fake_items
        assert apify_jobs_search_is_cached(params=SAMPLE_PARAMS) is True
        assert "page" not in captured["client"].actor_obj.last_run_input

    def test_does_not_mark_cache_on_apify_error(
        self, isolated_job_filters, no_rate_limit, monkeypatch
    ):
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")

        class FakeActor:
            def call(self, run_input=None):
                raise RuntimeError("Apify actor failed")

        class FakeClient:
            def __init__(self, token):
                self.token = token

            def actor(self, name):
                return FakeActor()

        monkeypatch.setattr("utils.apify_client.ApifyClient", FakeClient)

        items = fetch_jobs_via_apify(params=SAMPLE_PARAMS)

        assert items == []
        assert apify_jobs_search_is_cached(params=SAMPLE_PARAMS) is False

    def test_second_fetch_within_ttl_skips_after_first_success(
        self, isolated_job_filters, no_rate_limit, monkeypatch
    ):
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        call_count = {"n": 0}

        class FakeDataset:
            def iterate_items(self):
                return iter([{"job_title": "Engineer", "company": "Acme", "job_url": "https://example.com/j/1"}])

        class FakeActor:
            def call(self, run_input=None):
                call_count["n"] += 1
                return {"defaultDatasetId": "ds1", "defaultKeyValueStoreId": "kvs1"}

        class FakeClient:
            def __init__(self, token):
                self.token = token

            def actor(self, name):
                return FakeActor()

            def dataset(self, dataset_id):
                return FakeDataset()

        monkeypatch.setattr("utils.apify_client.ApifyClient", FakeClient)

        first = fetch_jobs_via_apify(params=SAMPLE_PARAMS)
        second = fetch_jobs_via_apify(params=SAMPLE_PARAMS)

        assert len(first) == 1
        assert second == []
        assert call_count["n"] == 1


class TestProcessCollectionPhaseCache:
    @pytest.fixture
    def collection_config(self, isolated_job_filters):
        config = {
            "search_parameters": [SAMPLE_PARAMS],
            "apify_search_cache": {},
        }
        isolated_job_filters.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        return config

    def test_does_not_regenerate_params_when_all_searches_cached(
        self, collection_config, isolated_job_filters, monkeypatch
    ):
        mark_apify_search_fetched(_build_apify_jobs_run_input(params=SAMPLE_PARAMS))

        regenerate = MagicMock(return_value=[{"keywords": "New", "location": "Italy"}])
        collect = MagicMock(return_value=[])
        monkeypatch.setattr("pipeline.collection.get_search_parameters", regenerate)
        monkeypatch.setattr("pipeline.collection.collect_jobs_via_apify", collect)

        from pipeline.collection import process_collection_phase

        db = MagicMock()
        db.get_all_records.return_value = []
        shutdown_requested = {"flag": False}

        collected, total_new, _ = process_collection_phase(
            db, resume_json={}, shutdown_requested=shutdown_requested, company_overview_cache={}
        )

        assert collected == []
        assert total_new == 0
        regenerate.assert_not_called()
        collect.assert_called_once_with(db, params=SAMPLE_PARAMS)

    def test_regenerates_params_when_apify_ran_and_found_no_new_jobs(
        self, collection_config, isolated_job_filters, monkeypatch
    ):
        new_params = [{"keywords": "Fresh query", "location": "Italy", "limit": 100}]
        regenerate = MagicMock(return_value=new_params)
        collect = MagicMock(return_value=[])
        monkeypatch.setattr("pipeline.collection.get_search_parameters", regenerate)
        monkeypatch.setattr("pipeline.collection.collect_jobs_via_apify", collect)

        from pipeline.collection import process_collection_phase

        db = MagicMock()
        db.get_all_records.return_value = []
        shutdown_requested = {"flag": False}

        collected, total_new, _ = process_collection_phase(
            db, resume_json={}, shutdown_requested=shutdown_requested, company_overview_cache={}
        )

        assert collected == []
        assert total_new == 0
        regenerate.assert_called_once()
        assert collect.call_count == 2
        collect.assert_any_call(db, params=SAMPLE_PARAMS)
        collect.assert_any_call(db, params=new_params[0])

        with open(isolated_job_filters, encoding="utf-8") as handle:
            saved = yaml.safe_load(handle)
        assert saved["search_parameters"] == new_params
