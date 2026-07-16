"""Tests for per-search serial processing in process_collection_phase (#23)."""

from unittest.mock import MagicMock

import pytest
import yaml

from utils.apify_search_cache import mark_apify_search_fetched
from utils.apify_client import _build_apify_jobs_run_input


@pytest.fixture
def isolated_job_filters(tmp_path, monkeypatch):
    config_path = tmp_path / "job_preferences.yaml"
    config_path.write_text("search_parameters: []\napify_search_cache: {}\n", encoding="utf-8")
    monkeypatch.setattr("config.CONFIG_FILE", str(config_path))
    return config_path


@pytest.fixture(autouse=True)
def reset_apify_state():
    from utils.apify_client import apify_state

    apify_state.reset()
    yield
    apify_state.reset()


@pytest.fixture(autouse=True)
def force_apify_collection_enabled(monkeypatch):
    """Local .env may set SKIP_APIFY_COLLECTION=true; these tests exercise the collection path."""
    monkeypatch.setattr("pipeline.constants.SKIP_APIFY_COLLECTION", False)


SEARCH_A = {"keywords": "Python Engineer", "location": "Remote"}
SEARCH_B = {"keywords": "Data Engineer", "location": "Remote"}


@pytest.fixture
def two_search_config(isolated_job_filters):
    config = {
        "search_parameters": [SEARCH_A, SEARCH_B],
        "apify_search_cache": {},
    }
    isolated_job_filters.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return config


class TestSerialPerSearchProcessing:
    def test_pipeline_drains_after_each_search_before_next_collect(
        self, two_search_config, isolated_job_filters, monkeypatch
    ):
        """process_new_jobs_pipeline must run for search A's jobs before search B is collected."""
        call_order = []

        def fake_collect(db, params=None, search_url=None):
            call_order.append(("collect", params.get("keywords")))
            return [(f"https://example.com/{params.get('keywords')}", "Acme")]

        def fake_process(db, resume_json, collected_jobs, cache):
            call_order.append(("process", collected_jobs))
            return True

        monkeypatch.setattr("pipeline.collection.collect_jobs_via_apify", fake_collect)
        monkeypatch.setattr("pipeline.collection.process_new_jobs_pipeline", fake_process)

        from pipeline.collection import process_collection_phase

        db = MagicMock()
        db.get_all_records.return_value = []
        shutdown_requested = {"flag": False}

        collected, total_new, _ = process_collection_phase(
            db, resume_json={}, shutdown_requested=shutdown_requested, company_overview_cache={}
        )

        assert total_new == 2
        # Each search's collect must be immediately followed by its own process call,
        # not batched at the end.
        assert call_order == [
            ("collect", "Python Engineer"),
            ("process", [("https://example.com/Python Engineer", "Acme")]),
            ("collect", "Data Engineer"),
            ("process", [("https://example.com/Data Engineer", "Acme")]),
        ]

    def test_no_processing_call_when_search_finds_nothing(
        self, two_search_config, isolated_job_filters, monkeypatch
    ):
        process_mock = MagicMock(return_value=False)
        monkeypatch.setattr("pipeline.collection.collect_jobs_via_apify", MagicMock(return_value=[]))
        monkeypatch.setattr("pipeline.collection.process_new_jobs_pipeline", process_mock)
        monkeypatch.setattr("pipeline.collection.get_search_parameters", MagicMock(return_value=[]))

        from pipeline.collection import process_collection_phase

        db = MagicMock()
        db.get_all_records.return_value = []
        shutdown_requested = {"flag": False}

        process_collection_phase(
            db, resume_json={}, shutdown_requested=shutdown_requested, company_overview_cache={}
        )

        process_mock.assert_not_called()

    def test_shutdown_flag_stops_before_next_search(
        self, two_search_config, isolated_job_filters, monkeypatch
    ):
        collect_mock = MagicMock(return_value=[("https://example.com/1", "Acme")])
        process_mock = MagicMock(return_value=True)
        monkeypatch.setattr("pipeline.collection.collect_jobs_via_apify", collect_mock)
        monkeypatch.setattr("pipeline.collection.process_new_jobs_pipeline", process_mock)

        from pipeline.collection import process_collection_phase

        db = MagicMock()
        db.get_all_records.return_value = []
        # Flip shutdown after the first search's collect+process pair completes.
        shutdown_requested = {"flag": False}

        real_process = process_mock.side_effect

        def process_then_shutdown(*args, **kwargs):
            shutdown_requested["flag"] = True
            return True

        process_mock.side_effect = process_then_shutdown

        process_collection_phase(
            db, resume_json={}, shutdown_requested=shutdown_requested, company_overview_cache={}
        )

        assert collect_mock.call_count == 1
        assert process_mock.call_count == 1
