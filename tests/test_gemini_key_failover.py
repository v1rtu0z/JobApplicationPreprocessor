"""Integration test: a Gemini call path fails over across configured keys."""

import pytest

import utils.gemini_analysis as ga


class _FakeResponse:
    def __init__(self, text):
        self.text = text


class _FakeModels:
    def __init__(self, api_key, tried):
        self._api_key = api_key
        self._tried = tried

    def generate_content(self, model, contents):
        self._tried.append(self._api_key)
        if self._api_key == "k1":
            raise Exception("429 RESOURCE_EXHAUSTED: quota exceeded")
        return _FakeResponse(
            '[{"job_id": "Backend @ Acme", "fit_score": "Good fit", "reasoning": "ok"}]'
        )


def _make_fake_genai_client(tried):
    class _FakeClient:
        def __init__(self, api_key):
            self.models = _FakeModels(api_key, tried)

    return _FakeClient


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for name in ("GEMINI_API_KEYS", "GEMINI_API_KEY", "BACKUP_GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    # Avoid touching the on-disk rate-limit state file during tests.
    monkeypatch.setattr(ga, "mark_gemini_rate_limit_hit", lambda: None)


def test_batch_analysis_fails_over_to_second_key(monkeypatch):
    tried = []
    monkeypatch.setattr(ga.genai, "Client", _make_fake_genai_client(tried))
    monkeypatch.setenv("GEMINI_API_KEYS", "k1,k2")

    result = ga.analyze_jobs_batch(
        {"name": "Test"},
        [{"job_title": "Backend", "company_name": "Acme"}],
    )

    assert tried == ["k1", "k2"]  # first key 429'd, failed over to second
    assert result == [
        {"job_id": "Backend @ Acme", "fit_score": "Good fit", "reasoning": "ok"}
    ]


def test_batch_analysis_single_key_unchanged(monkeypatch):
    tried = []
    monkeypatch.setattr(ga.genai, "Client", _make_fake_genai_client(tried))
    monkeypatch.setenv("GEMINI_API_KEY", "k2")

    result = ga.analyze_jobs_batch(
        {"name": "Test"},
        [{"job_title": "Backend", "company_name": "Acme"}],
    )

    assert tried == ["k2"]
    assert result[0]["fit_score"] == "Good fit"
