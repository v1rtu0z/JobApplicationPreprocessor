"""Regression tests for confirmed high-severity bugs."""

import sqlite3
from unittest.mock import Mock

import pytest

from local_storage import JobDatabase
from utils.apify_client import fetch_jobs_via_apify, match_job_to_apify_result, apify_jobs_search_is_cached
from utils.schema import SHEET_HEADER
from utils.sustainability import is_sustainable_company, validate_sustainability_for_unprocessed_jobs


@pytest.fixture
def job_db(tmp_path):
    db = JobDatabase(str(tmp_path / "jobs.db"), SHEET_HEADER)
    return db


@pytest.fixture
def isolated_job_filters(tmp_path, monkeypatch):
    config_path = tmp_path / "job_preferences.yaml"
    config_path.write_text("search_parameters: []\napify_search_cache: {}\n", encoding="utf-8")
    monkeypatch.setattr("config.CONFIG_FILE", str(config_path))
    return config_path


def _sample_job(company, title, url, **extra):
    row = {col: "" for col in SHEET_HEADER}
    row.update({
        "Company Name": company,
        "Job Title": title,
        "Job URL": url,
        "Job Description": extra.get("jd", "Build things."),
        "Company overview": extra.get("co", "We build things."),
        **{k: v for k, v in extra.items() if k not in ("jd", "co")},
    })
    return row


SAMPLE_PARAMS = {
    "keywords": "Python Engineer",
    "location": "Remote",
    "remote": "remote",
    "experienceLevel": "mid_senior",
    "sort": "recent",
    "date_posted": "week",
    "limit": 100,
}


class TestSortByDataSafety:
    def test_sort_by_preserves_jobs_when_reinsert_fails(self, job_db):
        job_db.add_jobs([
            _sample_job("Acme", "Engineer", "https://example.com/1"),
            _sample_job("Beta", "Developer", "https://example.com/2"),
        ])
        original_count = job_db.count()

        conn = job_db._get_connection()
        try:
            conn.execute(
                "CREATE TRIGGER block_jobs_reinsert "
                "BEFORE INSERT ON jobs BEGIN "
                "SELECT RAISE(ABORT, 'simulated insert failure'); END;"
            )
            conn.commit()
        finally:
            conn.close()

        with pytest.raises(sqlite3.Error):
            job_db.sort_by([("Fit score enum", False), ("Location Priority", True)])

        assert job_db.count() == original_count


class TestApifyEmptyResultCache:
    def test_empty_apify_result_does_not_mark_cache(
        self, isolated_job_filters, monkeypatch
    ):
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        monkeypatch.setattr("utils.apify_client.rate_limit", lambda: None)

        class FakeDataset:
            def iterate_items(self):
                return iter([])

        class FakeActor:
            def call(self, run_input=None):
                return {"defaultDatasetId": "ds1", "defaultKeyValueStoreId": "kvs1"}

        class FakeClient:
            def __init__(self, token):
                self.token = token

            def actor(self, name):
                return FakeActor()

            def dataset(self, dataset_id):
                return FakeDataset()

        monkeypatch.setattr("utils.apify_client.ApifyClient", FakeClient)

        items = fetch_jobs_via_apify(params=SAMPLE_PARAMS)

        assert items == []
        assert apify_jobs_search_is_cached(params=SAMPLE_PARAMS) is False


class TestSustainabilityDefaults:
    def test_missing_is_sustainable_key_is_not_treated_as_true(self, monkeypatch):
        monkeypatch.setattr(
            "utils.sustainability._call_gemini_for_sustainability",
            lambda *args, **kwargs: {"reasoning": "unclear"},
        )

        result = is_sustainable_company("Raytheon", "Defense contractor", "Build missiles")

        assert result is not True


class TestSustainabilityCompanyMatching:
    def test_substring_company_match_does_not_cross_contaminate(self, job_db, monkeypatch):
        job_db.add_jobs([
            _sample_job("Meta", "Engineer", "https://example.com/meta"),
            _sample_job("Metamorphic Labs", "Scientist", "https://example.com/metamorphic"),
        ])

        monkeypatch.setattr(
            "utils.sustainability.is_sustainable_company_bulk",
            lambda companies, db=None: {
                "Metamorphic Labs": {
                    "is_sustainable": False,
                    "reasoning": "Not sustainable",
                }
            },
        )

        validate_sustainability_for_unprocessed_jobs(job_db)

        rows = {r["Job URL"]: r for r in job_db.get_all_records()}
        assert rows["https://example.com/metamorphic"]["Sustainable company"] == "FALSE"
        assert rows["https://example.com/meta"].get("Sustainable company", "") != "FALSE"


class TestApifyJobMatching:
    def test_engineer_does_not_match_senior_software_engineer(self):
        job = {"title": "Engineer", "company": "Acme Corp"}
        item = {
            "job_info": {"title": "Senior Software Engineer"},
            "company_info": {"name": "Acme Corp"},
        }

        assert match_job_to_apify_result(job, item) is False

    def test_exact_title_and_company_still_match(self):
        job = {"title": "Senior Software Engineer", "company": "Acme Corp"}
        item = {
            "job_info": {"title": "Senior Software Engineer"},
            "company_info": {"name": "Acme Corp"},
        }

        assert match_job_to_apify_result(job, item) is True


class TestEmptyJobTitleStopsPipeline:
    def test_analyze_all_jobs_continues_after_blank_title_row(self, job_db, monkeypatch):
        job_db.add_jobs([
            _sample_job("Acme", "", "https://example.com/blank"),
            _sample_job("Beta", "Engineer", "https://example.com/good", jd="Python role"),
        ])
        job_db.update_job_by_key(
            "https://example.com/good", "Beta", {"Sustainable company": "TRUE"}
        )

        monkeypatch.setattr("pipeline.analysis.CHECK_SUSTAINABILITY", True)
        monkeypatch.setattr(
            "pipeline.analysis.analyze_jobs_batch",
            lambda resume_json, job_details_list: [
                {"job_id": "Engineer @ Beta", "fit_score": "Good fit", "reasoning": "ok"},
            ],
        )
        monkeypatch.setattr("pipeline.analysis.acquire_gemini_slot", lambda: None)

        from pipeline.analysis import analyze_all_jobs

        count = analyze_all_jobs(job_db, resume_json={})

        assert count == 1
        updated = job_db.get_all_records()
        good = next(r for r in updated if r["Job URL"] == "https://example.com/good")
        assert good["Fit score"] == "Good fit"


class TestBulkFilterErrorHandling:
    def test_bulk_filter_error_does_not_mark_jobs_filtered(self, job_db, monkeypatch):
        from pipeline.bulk_ops import bulk_filter_collected_jobs
        from pipeline.constants import BULK_FILTER_BATCH_SIZE

        jobs = [
            _sample_job("Co", f"Title {i}", f"https://example.com/{i}", jd="Python work")
            for i in range(BULK_FILTER_BATCH_SIZE)
        ]
        job_db.add_jobs(jobs)

        def raise_error(*args, **kwargs):
            raise RuntimeError("bulk filter failed")

        monkeypatch.setattr("pipeline.bulk_ops.bulk_filter_jobs", raise_error)

        bulk_filter_collected_jobs(job_db, {}, force_process=True)

        for row in job_db.get_all_records():
            assert row.get("Bulk filtered") != "TRUE"


class TestJdApifyFallback:
    def test_small_crawl_failures_use_apify_fallback(self, job_db, monkeypatch):
        from pipeline.bulk_ops import bulk_fetch_missing_job_descriptions

        job_db.add_jobs([
            _sample_job(
                "Acme",
                "Engineer",
                "https://www.linkedin.com/jobs/view/1234567890/",
                jd="",
            ),
        ])

        crawl_result = ([], [], [{
            "job_url": "https://www.linkedin.com/jobs/view/1234567890/",
            "company": "Acme",
            "title": "Engineer",
        }])
        monkeypatch.setattr(
            "utils.fetch_job_descriptions_via_crawling",
            lambda *args, **kwargs: crawl_result,
        )
        monkeypatch.setattr("utils.APIFY_AVAILABLE", True)
        monkeypatch.setattr(
            "utils.fetch_job_details_bulk_via_apify",
            lambda job_ids: [{
                "job_info": {"title": "Engineer", "description": "Detailed JD from Apify"},
                "company_info": {"name": "Acme"},
            }],
        )

        updated = bulk_fetch_missing_job_descriptions(job_db)

        assert updated == 1
        row = job_db.get_all_records()[0]
        assert row["Job Description"] == "Detailed JD from Apify"
        assert row["JD crawl attempted"] == "TRUE"


class TestCompanyOverviewFallback:
    def test_linkedin_co_fallback_when_apify_misses(self, job_db, monkeypatch):
        from pipeline.bulk_ops import fetch_company_overviews

        job_db.add_jobs([
            _sample_job(
                "Obscure Startup",
                "Engineer",
                "https://example.com/job",
                jd="Role details",
                co="",
            ),
        ])

        monkeypatch.setattr("pipeline.bulk_ops.CHECK_SUSTAINABILITY", True)
        monkeypatch.setattr("pipeline.bulk_ops.CRAWL_LINKEDIN", True)
        monkeypatch.setattr("utils.apify_client.apify_state.is_available", lambda: True)
        monkeypatch.setattr(
            "pipeline.bulk_ops.get_company_overviews_bulk_via_apify",
            lambda names: {},
        )
        crawl = Mock(return_value=({"Obscure Startup": "We build climate tech."}, []))
        monkeypatch.setattr("pipeline.bulk_ops.fetch_company_overviews_via_crawling", crawl)

        fetch_company_overviews(job_db, {})

        crawl.assert_called_once()
        row = job_db.get_all_records()[0]
        assert row["Company overview"] == "We build climate tech."


class TestSustainabilityBulkNameMatching:
    def test_bulk_sustainability_accepts_normalized_name_variant(self, job_db, monkeypatch):
        job_db.add_jobs([
            _sample_job("Acme", "Engineer", "https://example.com/acme", co="Green energy company"),
        ])

        monkeypatch.setattr(
            "utils.sustainability._call_gemini_for_sustainability",
            lambda *args, **kwargs: {
                "Acme Inc.": {"is_sustainable": True, "reasoning": "Clean energy"},
            },
        )

        validate_sustainability_for_unprocessed_jobs(job_db)

        assert job_db.get_all_records()[0]["Sustainable company"] == "TRUE"


class TestLinkedInBulkFilter:
    def test_linkedin_collection_bulk_filters_small_batches(self, monkeypatch):
        captured = {}

        def fake_bulk_filter(db, resume_json, target_jobs=None, force_process=False):
            captured["force_process"] = force_process
            captured["target_count"] = len(target_jobs or [])
            return 0

        jobs = [("https://example.com/1", "Acme")]
        import pipeline.collection as collection_module

        monkeypatch.setattr("pipeline.constants.CRAWL_LINKEDIN", True)
        monkeypatch.setattr(collection_module, "setup_driver", lambda: object())
        monkeypatch.setattr(collection_module, "validate_jobs_and_fetch_missing_data", lambda *args, **kwargs: 0)
        monkeypatch.setattr(collection_module, "collect_and_filter_jobs", lambda *args, **kwargs: jobs)
        monkeypatch.setattr(collection_module, "bulk_filter_collected_jobs", fake_bulk_filter)
        monkeypatch.setattr(collection_module, "fetch_company_overviews", lambda *args, **kwargs: 0)
        monkeypatch.setattr(collection_module, "analyze_all_jobs", lambda *args, **kwargs: 0)
        monkeypatch.setattr(collection_module, "process_resumes_and_cover_letters", lambda *args, **kwargs: 0)

        login_mock = Mock()
        actions_mock = Mock(login=login_mock)
        monkeypatch.setitem(__import__("sys").modules, "linkedin_scraper", Mock(actions=actions_mock))

        db = Mock()
        db.get_all_records.return_value = []

        collection_module.process_linkedin_collection(db, {}, {}, {"flag": False})

        assert captured["force_process"] is True
        assert captured["target_count"] == 1
