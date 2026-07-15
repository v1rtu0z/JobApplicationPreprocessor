"""Geographic filters for job collection (EMEA scope, UK global-remote rule)."""

from __future__ import annotations

# Substrings that indicate a posting outside EMEA (location or title).
NON_EMEA_LOCATION_MARKERS = (
    "united states",
    " usa",
    "usa,",
    ", usa",
    "u.s.",
    "u.s.a",
    "north america",
    "latin america",
    "latam",
    "canada",
    "toronto",
    "vancouver",
    "singapore",
    "australia",
    "sydney",
    "melbourne",
    "india",
    "bangalore",
    "bengaluru",
    "mumbai",
    "china",
    "japan",
    "tokyo",
    "south korea",
    " korea",
    "mexico",
    "brazil",
    "argentina",
    "buenos aires",
    "philippines",
    "taguig",
    "thailand",
    "bangkok",
    "malaysia",
    "indonesia",
    "vietnam",
    "hong kong",
    "taiwan",
    "new york",
    "san francisco",
    "california",
    " texas",
    " tx",
    ", tx",
    "austin",
    " florida",
    "utah",
    " ut",
    ", ut",
    "salt lake",
    "marietta, ga",
    "north township, in",
    "san jose, ca",
    "relocation to",
    "relocation provided",
    "bangkok based",
    "east coast",
    "est only",
    "est time",
    "remote - us",
    "remote, us",
    "apac",
    "south africa",
    "santiago",
    " chile",
    "chile,",
)

# Explicit EMEA / Europe-wide remote scopes (checked before non-EMEA block).
EMEA_SCOPE_MARKERS = (
    "emea",
    "european union",
    "european economic area",
    " europe",
    "europe,",
    ", europe",
    " eu",
    "eu,",
    ", eu",
)

UK_LOCATION_MARKERS = (
    "united kingdom",
    " uk",
    "uk,",
    ", uk",
    "england",
    "scotland",
    "wales",
    "northern ireland",
    "london",
    "manchester",
    "birmingham",
    "edinburgh",
    "leeds",
    "bristol",
    "glasgow",
    "cambridge, england",
    "greater london",
)

GLOBAL_REMOTE_MARKERS = (
    "worldwide",
    "global remote",
    "work from anywhere",
    "anywhere in the world",
    "100% remote",
    "fully remote",
    "remote worldwide",
    "remote globally",
    "remote, uk and eu",
    "remote uk and eu",
    "uk and eu",
    "eu and uk",
    "remote, europe",
    "remote europe",
    "remote (remote)",
    "remote friendly",
)

# DE / ES / NL: must be remote and must not require local language (title/location/description).
LOCAL_LANGUAGE_FILTER_COUNTRIES: dict[str, tuple[str, ...]] = {
    "germany": (
        "germany",
        "deutschland",
        "berlin",
        "munich",
        "münchen",
        "frankfurt",
        "hamburg",
        "cologne",
        "köln",
        "rhineland",
        "bavaria",
        "north rhine",
    ),
    "spain": (
        "spain",
        "españa",
        "madrid",
        "barcelona",
        "valencia",
        "seville",
        "catalonia",
        "community of madrid",
        "andalusia",
    ),
    "netherlands": (
        "netherlands",
        "holland",
        "amsterdam",
        "rotterdam",
        "the hague",
        "utrecht",
        "eindhoven",
        "north holland",
    ),
}

LOCAL_LANGUAGE_REQUIREMENT_MARKERS: dict[str, tuple[str, ...]] = {
    "germany": (
        "german required",
        "fluent german",
        "native german",
        "german speaking",
        "german speaker",
        "german language",
        "german and english",
        "english and german",
        "deutsch",
        "deutschkenntnisse",
        "fließend deutsch",
    ),
    "spain": (
        "spanish required",
        "fluent spanish",
        "native spanish",
        "spanish speaking",
        "spanish speaker",
        "spanish language",
        "castellano",
        "español",
        "espanol",
    ),
    "netherlands": (
        "dutch required",
        "fluent dutch",
        "native dutch",
        "dutch speaking",
        "dutch speaker",
        "dutch language",
        "nederlands",
    ),
}

GENERIC_LOCAL_LANGUAGE_MARKERS = (
    "local language",
    "native speaker required",
    "must speak the local language",
)

# US-hours-only remote roles (candidate is CET/EET based in Italy).
INCOMPATIBLE_TIMEZONE_MARKERS = (
    "est only",
    "est hours",
    "pst only",
    "pst hours",
    "cst only",
    "mst only",
    "eastern time only",
    "pacific time only",
    "central time only",
    "us business hours",
    "us working hours",
    "u.s. business hours",
    "americas timezone",
    "americas time zone",
    "must be in the us",
    "must be located in the us",
    "us time zone",
    "us timezone",
    "within us",
    "9am-5pm est",
    "9am-5pm pst",
    "9-5 est",
    "9-5 pst",
    "east coast hours",
    "west coast hours",
    "pacific hours",
    "eastern hours",
)

ACCEPTABLE_TIMEZONE_MARKERS = (
    "emea",
    "cet",
    "cest",
    "europe time",
    "european hours",
    "utc+1",
    "utc+2",
    "utc +1",
    "utc +2",
    "central european",
    "flexible timezone",
    "flexible hours",
    "any timezone",
    "async first",
    "async-friendly",
)


def _combined_location_text(location: str, job_title: str = "") -> str:
    return f"{(location or '').lower()} {(job_title or '').lower()}".strip()


def _combined_filter_text(location: str, job_title: str = "", job_description: str = "") -> str:
    return " ".join(
        part for part in ((location or ""), (job_title or ""), (job_description or "")) if part
    ).lower()


def is_outside_emea(location: str, job_title: str = "") -> bool:
    """True when location/title clearly indicates outside EMEA."""
    text = _combined_location_text(location, job_title)
    if not text:
        return False
    if any(marker in text for marker in EMEA_SCOPE_MARKERS):
        return False
    return any(marker in text for marker in NON_EMEA_LOCATION_MARKERS)


def is_uk_location(location: str) -> bool:
    loc = (location or "").lower()
    if not loc:
        return False
    return any(marker in loc for marker in UK_LOCATION_MARKERS)


def is_globally_remote(location: str, job_title: str = "") -> bool:
    """True when the posting is clearly fully remote without a fixed office requirement."""
    text = _combined_location_text(location, job_title)
    if not text:
        return False
    if any(marker in text for marker in GLOBAL_REMOTE_MARKERS):
        return True
    if text.strip() == "remote":
        return True
    if "remote" in text and any(m in text for m in ("emea", "european union", "european economic area", " europe")):
        return True
    return False


def should_skip_uk_not_globally_remote(location: str, job_title: str = "") -> bool:
    """True for UK-tied postings that are not globally remote."""
    if not is_uk_location(location):
        return False
    text = _combined_location_text(location, job_title)
    if any(x in text for x in ("hybrid", "on-site", "on site", "(on-site)", "on site")):
        return True
    return not is_globally_remote(location, job_title)


def local_language_filter_country(location: str, job_title: str = "") -> str | None:
    """Return DE/ES/NL country key when the posting is tied to that market."""
    text = _combined_location_text(location, job_title)
    if not text:
        return None
    for country, markers in LOCAL_LANGUAGE_FILTER_COUNTRIES.items():
        if any(marker in text for marker in markers):
            return country
    return None


def requires_local_language(
    location: str,
    job_title: str = "",
    job_description: str = "",
) -> tuple[bool, str | None]:
    """True when a DE/ES/NL posting requires the local language."""
    country = local_language_filter_country(location, job_title)
    if not country:
        return False, None
    text = _combined_filter_text(location, job_title, job_description)
    markers = LOCAL_LANGUAGE_REQUIREMENT_MARKERS.get(country, ())
    if any(marker in text for marker in markers):
        return True, f"Requires local language ({country})"
    if any(marker in text for marker in GENERIC_LOCAL_LANGUAGE_MARKERS):
        return True, f"Requires local language ({country})"
    return False, None


def local_country_not_fully_remote(location: str, job_title: str = "") -> tuple[bool, str | None]:
    """True when a DE/ES/NL posting is hybrid, on-site, or not clearly remote."""
    country = local_language_filter_country(location, job_title)
    if not country:
        return False, None
    text = _combined_location_text(location, job_title)
    if any(x in text for x in ("hybrid", "on-site", "on site", "(on-site)", "onsite")):
        return True, f"Not fully remote in {country}"
    if "remote" not in text and not is_globally_remote(location, job_title):
        return True, f"Not fully remote in {country}"
    return False, None


def should_skip_incompatible_timezone(location: str, job_title: str = "") -> bool:
    """True for globally remote roles that require US-only working hours."""
    if not is_globally_remote(location, job_title):
        return False
    text = _combined_location_text(location, job_title)
    if any(marker in text for marker in ACCEPTABLE_TIMEZONE_MARKERS):
        return False
    return any(marker in text for marker in INCOMPATIBLE_TIMEZONE_MARKERS)


def apply_local_country_filters(
    location: str,
    job_title: str = "",
    job_description: str = "",
) -> tuple[bool, str | None]:
    """Remote + local-language rules for Germany, Spain, and Netherlands."""
    not_remote, reason = local_country_not_fully_remote(location, job_title)
    if not_remote:
        return True, reason
    needs_lang, lang_reason = requires_local_language(location, job_title, job_description)
    if needs_lang:
        return True, lang_reason
    return False, None


def apply_geo_filters(
    location: str,
    job_title: str = "",
    job_description: str = "",
) -> tuple[bool, str | None]:
    """Return (should_skip, reason) for geo, timezone, UK, and DE/ES/NL rules."""
    if is_globally_remote(location, job_title):
        if should_skip_incompatible_timezone(location, job_title):
            return True, "Incompatible timezone (US-hours-only remote)"
        if should_skip_uk_not_globally_remote(location, job_title):
            return True, "UK posting is not globally remote"
        local_skip, local_reason = apply_local_country_filters(location, job_title, job_description)
        if local_skip:
            return True, local_reason
        return False, None

    if is_outside_emea(location, job_title):
        return True, "Location outside EMEA"
    if should_skip_uk_not_globally_remote(location, job_title):
        return True, "UK posting is not globally remote"
    local_skip, local_reason = apply_local_country_filters(location, job_title, job_description)
    if local_skip:
        return True, local_reason
    return False, None
