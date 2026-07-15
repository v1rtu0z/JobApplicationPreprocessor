"""LinkedIn company overview fetching helpers for Apify linkedin-company-detail."""

from __future__ import annotations

import os
import re
import unicodedata
from urllib.parse import urlparse

from apify_client import ApifyClient

from .apify_state import ApifyStateManager, apify_state

_LEGAL_SUFFIXES = re.compile(
    r"\b("
    r"inc\.?|incorporated|llc|l\.?l\.?c\.?|ltd\.?|limited|corp\.?|corporation|"
    r"gmbh|ag|s\.?p\.?a\.?|s\.?l\.?|s\.?r\.?l\.?|s\.?a\.?|b\.?v\.?|pty\.?|plc"
    r")\b",
    re.IGNORECASE,
)
_LINKEDIN_COMPANY_PATH = re.compile(r"/company/([^/?#]+)")


def _ascii_slug(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def _slug_from_linkedin_url(company_url: str) -> str:
    url = (company_url or "").strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url.lstrip("/")
    match = _LINKEDIN_COMPANY_PATH.search(urlparse(url).path)
    return match.group(1).strip("/") if match else ""


def linkedin_company_identifier_candidates(company_name: str, company_url: str = "") -> list[str]:
    """Ordered Apify identifiers to try for a company (slug, URL, display name)."""
    seen: set[str] = set()
    candidates: list[str] = []

    def _add(value: str) -> None:
        value = (value or "").strip()
        if not value:
            return
        key = value.lower()
        if key in seen:
            return
        seen.add(key)
        candidates.append(value)

    url_slug = _slug_from_linkedin_url(company_url)
    if url_slug:
        _add(url_slug)
    if company_url.strip():
        _add(company_url.strip())

    core = _LEGAL_SUFFIXES.sub("", (company_name or "").strip()).strip(" ,.-")
    words = re.findall(r"[a-z0-9]+", core.lower())
    if words:
        _add(words[0])
        if len(words) > 1:
            _add("-".join(words))
            _add("".join(words))

    slug = _ascii_slug(core)
    _add(slug)
    _add((company_name or "").strip())
    return candidates


def extract_company_overview_from_apify_item(item: dict) -> str:
    """Pull the best available overview/description text from an Apify company item."""
    if not isinstance(item, dict):
        return ""

    basic_info = item.get("basic_info") or {}
    if not isinstance(basic_info, dict):
        basic_info = {}

    for key in ("description", "about", "overview", "tagline"):
        text = (basic_info.get(key) or item.get(key) or "").strip()
        if text:
            return text

    for key in ("description", "about", "overview"):
        text = ((item.get("links") or {}).get(key) or "").strip()
        if text:
            return text

    return ""


def _fetch_company_item(identifier: str) -> dict | None:
    token = os.getenv("APIFY_API_TOKEN")
    if not token:
        return None
    client = ApifyClient(token)
    run = client.actor("apimaestro/linkedin-company-detail").call(
        run_input={"identifier": [identifier], "maxResults": 1},
    )
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    return items[0] if items else None


def fetch_company_overview_via_apify(company_name: str, company_url: str = "") -> str | None:
    """Fetch one company overview, trying several LinkedIn identifier forms."""
    if not apify_state.is_available():
        return None

    from .apify_client import rate_limit

    tried: list[str] = []
    for identifier in linkedin_company_identifier_candidates(company_name, company_url):
        tried.append(identifier)
        rate_limit()
        try:
            item = _fetch_company_item(identifier)
        except Exception as exc:
            if ApifyStateManager.is_monthly_limit_error(str(exc)):
                apify_state.handle_error(str(exc))
            continue
        overview = extract_company_overview_from_apify_item(item or {})
        if overview:
            return overview

    if tried:
        preview = ", ".join(tried[:4])
        if len(tried) > 4:
            preview += f", +{len(tried) - 4} more"
        print(f"  Apify returned no overview text for {company_name} (tried: {preview})")
    return None


def get_company_overviews_bulk_via_apify(
    companies: list[tuple[str, str]] | list[str],
) -> dict[str, str]:
    """
    Fetch company overviews via Apify.

    Accepts either:
    - list of (display_name, company_url) tuples, or
    - legacy list of display names only.
    """
    if not companies:
        return {}

    if not apify_state.is_available():
        print("Apify is currently unavailable (usage limit reached). Skipping company overview fetch.")
        return {}

    normalized: list[tuple[str, str]] = []
    for entry in companies:
        if isinstance(entry, tuple):
            normalized.append((entry[0], entry[1] if len(entry) > 1 else ""))
        else:
            normalized.append((str(entry), ""))

    print(f"Fetching {len(normalized)} company overviews via Apify...")
    company_map: dict[str, str] = {}
    for display_name, company_url in normalized:
        overview = fetch_company_overview_via_apify(display_name, company_url)
        if overview:
            company_map[display_name] = overview

    print(f"Successfully fetched {len(company_map)}/{len(normalized)} company overviews")
    return company_map
