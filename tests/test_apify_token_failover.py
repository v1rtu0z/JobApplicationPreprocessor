"""Integration test: fetch_jobs_via_apify fails over across Apify tokens."""

import pytest

import utils.apify_client as ac


class _FakeDataset:
    def __init__(self, items):
        self._items = items

    def iterate_items(self):
        return iter(self._items)


class _FakeActor:
    def __init__(self, token, tried):
        self._token = token
        self._tried = tried

    def call(self, run_input=None):
        self._tried.append(self._token)
        if self._token == "bad-token":
            raise Exception("429 Too Many Requests: rate limit exceeded")
        return {"defaultDatasetId": "ds-1", "defaultKeyValueStoreId": "kv-1"}


def _make_fake_client(tried):
    class _FakeClient:
        def __init__(self, token):
            self._token = token

        def actor(self, actor_id):
            return _FakeActor(self._token, tried)

        def dataset(self, dataset_id):
            return _FakeDataset([{"job_info": {"title": "Backend Engineer"}}])

    return _FakeClient


@pytest.fixture
def apify_env(monkeypatch):
    tried = []
    monkeypatch.setattr(ac, "ApifyClient", _make_fake_client(tried))
    monkeypatch.setattr(ac, "APIFY_AVAILABLE", True)
    monkeypatch.setattr(ac, "rate_limit", lambda: None)
    monkeypatch.setattr(ac, "should_skip_apify_search", lambda run_input: False)
    monkeypatch.setattr(ac, "mark_apify_search_fetched", lambda run_input: None)
    return tried


def test_fails_over_from_exhausted_token_to_working_token(apify_env, monkeypatch):
    monkeypatch.setattr(ac, "get_apify_api_tokens", lambda: ["bad-token", "good-token"])

    items = ac.fetch_jobs_via_apify(params={"keywords": "python", "location": "Italy"})

    assert len(items) == 1
    # First token was tried and failed, then it failed over to the good token.
    assert apify_env == ["bad-token", "good-token"]


def test_single_working_token_unchanged(apify_env, monkeypatch):
    monkeypatch.setattr(ac, "get_apify_api_tokens", lambda: ["good-token"])

    items = ac.fetch_jobs_via_apify(params={"keywords": "python", "location": "Italy"})

    assert len(items) == 1
    assert apify_env == ["good-token"]


def test_all_tokens_exhausted_returns_empty(apify_env, monkeypatch):
    # Both tokens raise a retryable 429 -> failover exhausts and returns [].
    monkeypatch.setattr(ac, "get_apify_api_tokens", lambda: ["bad-token", "bad-token"])

    items = ac.fetch_jobs_via_apify(params={"keywords": "python", "location": "Italy"})

    assert items == []
