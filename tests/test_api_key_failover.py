"""Tests for multi-key API-key resolution and quota failover (utils.api_keys)."""

import pytest

from utils.api_keys import (
    AllKeysExhaustedError,
    get_apify_api_tokens,
    get_gemini_api_keys,
    get_gemini_labeled_keys,
    is_quota_or_rate_limit_error,
    run_with_key_failover,
)

GEMINI_ENV = ("GEMINI_API_KEYS", "GEMINI_API_KEY", "BACKUP_GEMINI_API_KEY")
APIFY_ENV = ("APIFY_API_TOKENS", "APIFY_API_TOKEN")


@pytest.fixture(autouse=True)
def _clear_key_env(monkeypatch):
    for name in GEMINI_ENV + APIFY_ENV:
        monkeypatch.delenv(name, raising=False)


class TestGeminiKeyResolution:
    def test_single_legacy_key_backward_compatible(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "solo")
        assert get_gemini_api_keys() == ["solo"]
        assert get_gemini_labeled_keys() == [("key 1", "solo")]

    def test_primary_and_backup_combined(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "primary")
        monkeypatch.setenv("BACKUP_GEMINI_API_KEY", "backup")
        assert get_gemini_api_keys() == ["primary", "backup"]

    def test_csv_list_takes_precedence_and_merges(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEYS", "k1, k2 , k3")
        monkeypatch.setenv("GEMINI_API_KEY", "k2")  # duplicate, dropped
        monkeypatch.setenv("BACKUP_GEMINI_API_KEY", "k4")
        assert get_gemini_api_keys() == ["k1", "k2", "k3", "k4"]

    def test_blanks_and_duplicates_removed(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEYS", "k1, , k1 ,k2,")
        assert get_gemini_api_keys() == ["k1", "k2"]

    def test_no_keys_returns_empty(self):
        assert get_gemini_api_keys() == []
        assert get_gemini_labeled_keys() == []


class TestApifyTokenResolution:
    def test_single_legacy_token_backward_compatible(self, monkeypatch):
        monkeypatch.setenv("APIFY_API_TOKEN", "tok")
        assert get_apify_api_tokens() == ["tok"]

    def test_csv_list_merges_with_single(self, monkeypatch):
        monkeypatch.setenv("APIFY_API_TOKENS", "t1,t2")
        monkeypatch.setenv("APIFY_API_TOKEN", "t3")
        assert get_apify_api_tokens() == ["t1", "t2", "t3"]

    def test_duplicate_token_deduped(self, monkeypatch):
        monkeypatch.setenv("APIFY_API_TOKENS", "t1,t2")
        monkeypatch.setenv("APIFY_API_TOKEN", "t1")
        assert get_apify_api_tokens() == ["t1", "t2"]


class TestRetryableClassification:
    @pytest.mark.parametrize("msg", [
        "429 Too Many Requests",
        "RESOURCE_EXHAUSTED: quota exceeded",
        "Rate limit reached for model",
        "503 Service Unavailable",
    ])
    def test_retryable_messages(self, msg):
        assert is_quota_or_rate_limit_error(Exception(msg)) is True

    def test_non_retryable_message(self):
        assert is_quota_or_rate_limit_error(ValueError("bad JSON")) is False

    def test_status_code_attribute(self):
        exc = Exception("boom")
        exc.status_code = 429
        assert is_quota_or_rate_limit_error(exc) is True


class _QuotaError(Exception):
    pass


class TestRunWithKeyFailover:
    def test_single_key_success(self):
        calls = []
        result = run_with_key_failover(["k1"], lambda k: calls.append(k) or f"ok:{k}")
        assert result == "ok:k1"
        assert calls == ["k1"]

    def test_first_key_quota_fails_over_to_second(self):
        seen = []

        def fn(key):
            seen.append(key)
            if key == "k1":
                raise _QuotaError("429 quota exceeded")
            return f"done:{key}"

        result = run_with_key_failover(["k1", "k2"], fn)
        assert result == "done:k2"
        assert seen == ["k1", "k2"]

    def test_all_keys_exhausted_raises_once(self, capsys):
        attempts = []

        def fn(key):
            attempts.append(key)
            raise _QuotaError("rate limit")

        with pytest.raises(AllKeysExhaustedError) as exc_info:
            run_with_key_failover(["k1", "k2", "k3"], fn, label="Gemini")

        assert attempts == ["k1", "k2", "k3"]
        assert "All 3 Gemini keys exhausted" in str(exc_info.value)
        # The exhaustion summary is logged exactly once.
        assert capsys.readouterr().out.count("All 3 Gemini keys exhausted") == 1

    def test_non_retryable_error_raised_immediately(self):
        seen = []

        def fn(key):
            seen.append(key)
            raise ValueError("malformed request")

        with pytest.raises(ValueError):
            run_with_key_failover(["k1", "k2"], fn)
        # Should not have tried the second key for a non-retryable error.
        assert seen == ["k1"]

    def test_no_keys_configured_raises(self):
        with pytest.raises(AllKeysExhaustedError):
            run_with_key_failover([], lambda k: k)

    def test_custom_is_retryable_predicate(self):
        seen = []

        def fn(key):
            seen.append(key)
            if key == "k1":
                raise RuntimeError("please retry")
            return key

        # "please retry" is not a default-retryable message, but the custom
        # predicate makes it one.
        result = run_with_key_failover(
            ["k1", "k2"], fn, is_retryable=lambda e: "retry" in str(e)
        )
        assert result == "k2"
        assert seen == ["k1", "k2"]
