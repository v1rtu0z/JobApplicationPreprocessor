"""Tests for cover letter text normalization."""

from utils.cover_letter_format import normalize_cover_letter_body


def test_strips_subject_line():
    raw = (
        "Subject: Application for Engineer – Nikola Mandić\n\n"
        "Dear Hiring Team at Acme Corp,\n\nI am interested..."
    )
    result = normalize_cover_letter_body(raw)
    assert result.startswith("Dear Hiring Team,")
    assert "Subject:" not in result
    assert "Nikola Mandić" not in result.split("\n", 1)[0]


def test_normalizes_salutation():
    raw = "Dear Hiring Manager at Example Inc,\n\nBody text."
    result = normalize_cover_letter_body(raw)
    assert result.startswith("Dear Hiring Team,")
    assert "Body text." in result
