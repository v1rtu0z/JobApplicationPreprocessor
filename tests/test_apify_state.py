"""Tests for Apify monthly limit state."""

import importlib
from unittest.mock import patch

import pytest

from utils.apify_state import ApifyStateManager, seconds_until_next_month

_apify_state_mod = importlib.import_module("utils.apify_state")


@pytest.fixture
def apify_mgr(tmp_path, monkeypatch):
    state_file = tmp_path / "apify_state.json"
    monkeypatch.setattr(_apify_state_mod, "STATE_FILE", state_file)
    mgr = ApifyStateManager()
    yield mgr
    mgr.reset()


class TestApifyMonthlyLimit:
    def test_mark_monthly_limit_persists(self, apify_mgr):
        apify_mgr.mark_monthly_limit_exhausted()
        assert apify_mgr.is_monthly_limited()
        assert not apify_mgr.is_available()

        reloaded = ApifyStateManager()
        assert reloaded.is_monthly_limited()

    def test_monthly_limit_error_detection(self):
        assert ApifyStateManager.is_monthly_limit_error("Monthly usage hard limit exceeded")
        assert not ApifyStateManager.is_monthly_limit_error("timeout")

    def test_handle_error_monthly(self, apify_mgr):
        apify_mgr.handle_error("Monthly usage hard limit exceeded")
        assert apify_mgr.is_monthly_limited()

    def test_clears_after_next_month(self, apify_mgr):
        apify_mgr.mark_monthly_limit_exhausted()
        with patch("utils.apify_state.seconds_until_next_month", return_value=0):
            assert not apify_mgr.is_monthly_limited()
            assert apify_mgr.is_available()

    def test_seconds_until_retry_when_monthly(self, apify_mgr):
        apify_mgr.mark_monthly_limit_exhausted()
        with patch("utils.apify_state.seconds_until_next_month", return_value=12345):
            assert apify_mgr.seconds_until_retry() == 12345

    def test_reset_clears_file(self, apify_mgr, tmp_path, monkeypatch):
        state_file = tmp_path / "apify_state.json"
        monkeypatch.setattr(_apify_state_mod, "STATE_FILE", state_file)
        apify_mgr.mark_monthly_limit_exhausted()
        assert state_file.is_file()
        apify_mgr.reset()
        assert not state_file.is_file()


class TestSecondsUntilNextMonth:
    def test_positive(self):
        assert seconds_until_next_month() > 0
