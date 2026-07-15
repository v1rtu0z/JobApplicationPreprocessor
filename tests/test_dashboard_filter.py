"""Tests for shared dashboard default filter logic."""

from pipeline.dashboard_filter import (
    DEFAULT_EXCLUDED_FIT_SCORES,
    default_dashboard_job_keys,
    row_passes_default_dashboard_filter,
)


def _row(**extra):
    base = {
        "Job URL": "https://example.com/job",
        "Company Name": "Acme",
        "Applied": "",
        "Job posting expired": "",
        "Bad analysis": "",
        "Fit score": "",
        "Sustainable company": "",
    }
    base.update(extra)
    return base


def test_row_passes_default_dashboard_filter_excludes_unsustainable(monkeypatch):
    monkeypatch.setattr("pipeline.dashboard_filter.CHECK_SUSTAINABILITY", True)
    assert row_passes_default_dashboard_filter(_row(**{"Sustainable company": "FALSE"})) is False
    assert row_passes_default_dashboard_filter(_row(**{"Sustainable company": "TRUE"})) is True
    assert row_passes_default_dashboard_filter(_row()) is True


def test_row_passes_default_dashboard_filter_excludes_poor_fit():
    for fit in DEFAULT_EXCLUDED_FIT_SCORES:
        assert row_passes_default_dashboard_filter(_row(**{"Fit score": fit})) is False
    assert row_passes_default_dashboard_filter(_row(**{"Fit score": "Moderate fit"})) is False


def test_default_dashboard_job_keys(monkeypatch):
    monkeypatch.setattr("pipeline.dashboard_filter.CHECK_SUSTAINABILITY", True)

    class _FakeDb:
        def get_all_records(self):
            return [
                _row(**{"Job URL": "https://example.com/1", "Company Name": "Visible Co"}),
                _row(
                    **{
                        "Job URL": "https://example.com/2",
                        "Company Name": "Hidden Co",
                        "Sustainable company": "FALSE",
                    }
                ),
            ]

    keys = default_dashboard_job_keys(_FakeDb())
    assert ("https://example.com/1", "Visible Co") in keys
    assert ("https://example.com/2", "Hidden Co") not in keys
