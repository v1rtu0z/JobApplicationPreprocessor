"""Tests for Apify company overview identifier/parsing helpers."""

from utils.apify_company import (
    extract_company_overview_from_apify_item,
    linkedin_company_identifier_candidates,
)


def test_linkedin_company_identifier_candidates_prefers_url_slug():
    candidates = linkedin_company_identifier_candidates(
        "OpenVPN Inc.",
        "https://www.linkedin.com/company/openvpn/",
    )
    assert candidates[0] == "openvpn"
    assert "https://www.linkedin.com/company/openvpn/" in candidates


def test_linkedin_company_identifier_candidates_includes_first_word():
    candidates = linkedin_company_identifier_candidates("Hopla! Software", "")
    assert "hopla" in candidates
    assert "hopla-software" in candidates


def test_extract_company_overview_from_basic_info_description():
    item = {
        "input_identifier": "openvpn",
        "basic_info": {"description": "We build secure networking."},
    }
    assert extract_company_overview_from_apify_item(item) == "We build secure networking."


def test_extract_company_overview_empty_when_missing():
    assert extract_company_overview_from_apify_item({"basic_info": {"description": ""}}) == ""
