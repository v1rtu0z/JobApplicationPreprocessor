"""Keyword filters, sustainability check, and company overview cache."""

from dataclasses import dataclass

from config import _get_job_filters
from utils import (
    fit_score_to_enum,
    is_sustainable_company,
    normalize_company_name,
)

from .constants import CHECK_SUSTAINABILITY
from .location_filters import apply_geo_filters


@dataclass(frozen=True)
class FilterResult:
    """Result of applying keyword and sustainability filters to a job."""

    fit_score: str
    fit_score_enum: int
    analysis_reason: str
    is_sustainable: bool | None
    bulk_filtered: str
    sustainability_keyword_matches: str

    @property
    def filtered(self) -> bool:
        """True if the job was filtered out (should be marked with fit score / analysis)."""
        return bool(self.fit_score)

    def row_updates(self, last_expiration_check: str) -> dict:
        """Updates to persist for this job (fit score, analysis, keyword matches, last check)."""
        updates = {
            "Sustainability keyword matches": self.sustainability_keyword_matches or "",
            "Last expiration check": last_expiration_check,
        }
        if self.filtered:
            updates.update({
                "Fit score": self.fit_score,
                "Fit score enum": str(self.fit_score_enum),
                "Job analysis": self.analysis_reason,
                "Bulk filtered": self.bulk_filtered,
            })
        return updates


def _normalize_title_for_filter(title: str) -> str:
    """Lowercase title with hyphens/slashes collapsed to spaces for keyword matching."""
    t = (title or "").lower().replace("-", " ").replace("/", " ").replace("_", " ")
    return " ".join(t.split())


def _title_matches_junior_entry_nextjs(title: str) -> bool:
    """True when title indicates junior/entry-level or Next.js (for targeted retroactive cleanup)."""
    t = _normalize_title_for_filter(title)
    if not t:
        return False
    blocked = (
        "junior",
        "entry level",
        "early career",
        "next.js",
        "nextjs",
        "next js",
    )
    if any(p in t for p in blocked):
        return True
    words = t.split()
    return "jr" in words or "jr." in words


def _title_has_ai_ml_in_title(title: str) -> bool:
    """True when AI/ML appears in the title — exempt from pure-ML seniority filtering."""
    t = _normalize_title_for_filter(title)
    if not t:
        return False
    if "ai/ml" in t or "ai ml" in t:
        return True
    if "artificial intelligence" in t:
        return True
    if " ai engineer" in f" {t} " or " ai developer" in f" {t} ":
        return True
    if " ai " in f" {t} " and "ml" in t.split():
        return True
    if "lead ai" in t or "lead artificial intelligence" in t:
        return True
    return False


def _title_has_pure_ml_role(title: str) -> bool:
    """ML specialist title without an AI/ML exemption."""
    if _title_has_ai_ml_in_title(title):
        return False
    t = _normalize_title_for_filter(title)
    if not t:
        return False
    if "machine learning" in t:
        return True
    if "ml engineer" in t:
        return True
    words = t.split()
    return "ml" in words and "engineer" in words


def _title_has_junior_or_medior_level(title: str) -> bool:
    t = _normalize_title_for_filter(title)
    if not t:
        return False
    if "junior" in t or "medior" in t:
        return True
    if "mid level" in t or "midlevel" in t or "mid-level" in (title or "").lower():
        return True
    words = t.split()
    return "jr" in words or "jr." in words


def _title_has_ml_seniority_above_medior(title: str) -> bool:
    """Seniority above junior/medior (senior, staff, principal, lead, …)."""
    if _title_has_junior_or_medior_level(title):
        return False
    t = _normalize_title_for_filter(title)
    if not t:
        return False
    markers = ("senior", "staff", "principal", "lead", "head of", "director")
    if any(m in t for m in markers):
        return True
    words = t.split()
    return "sr" in words or "sr." in words


def _title_should_filter_ml_seniority(title: str) -> bool:
    """Filter pure ML roles unless junior/medior; AI/ML titles always pass."""
    if not _title_has_pure_ml_role(title):
        return False
    return _title_has_ml_seniority_above_medior(title)


# Backwards-compatible alias used in tests / older call sites.
def _title_is_senior_ml_specialist(title: str) -> bool:
    return _title_should_filter_ml_seniority(title)


# Skip keywords that name acceptable AI leadership roles — never filter these titles out.
TITLE_SKIP_KEYWORDS_NEVER_SKIP = frozenset({"lead ai engineer", "lead agentic"})


def _title_skip_keyword_applies(keyword: str, title_norm: str, job_title: str) -> bool:
    kw = (keyword or "").lower().strip()
    if not kw:
        return False
    if kw not in title_norm:
        return False
    if kw in TITLE_SKIP_KEYWORDS_NEVER_SKIP:
        return False
    if kw == "lead ml engineer" and _title_has_ai_ml_in_title(job_title):
        return False
    return True


def _normalize_require_keywords(raw) -> list[str]:
    """Lowercase, strip, and drop empties from a require-keyword list."""
    return [kw for kw in (str(k).lower().strip() for k in (raw or [])) if kw]


def _require_keywords_matched(job_title, job_description, filters):
    """Positive targeting: only keep jobs that match configured require-keywords.

    Returns (matched, reason). A job passes (matched=True) when no require lists
    are configured, or when it matches at least one require keyword:
      * job_title_require_keywords -> substring match against the title
      * job_require_keywords       -> substring match against title + description
    Matching is case-insensitive. Empty lists disable the check (backward compatible).
    """
    title_require = _normalize_require_keywords(filters.get("job_title_require_keywords"))
    desc_require = _normalize_require_keywords(filters.get("job_require_keywords"))
    if not title_require and not desc_require:
        return True, None

    title_l = (job_title or "").lower()
    if title_require and any(kw in title_l for kw in title_require):
        return True, None

    if desc_require:
        haystack = f"{title_l} {(job_description or '').lower()}"
        if any(kw in haystack for kw in desc_require):
            return True, None

    return False, "Job does not match required keywords"


def _apply_keyword_filters(job_title, company_name, raw_location, filters, job_description=""):
    """Apply keyword-based filters to determine if a job should be skipped."""
    title_norm = _normalize_title_for_filter(job_title)
    if _title_should_filter_ml_seniority(job_title):
        return True, "ML role above medior seniority (junior/medior OK)"
    geo_skip, geo_reason = apply_geo_filters(
        raw_location or "", job_title or "", job_description or ""
    )
    if geo_skip:
        return True, geo_reason
    location_norm = (raw_location or "").lower()
    should_skip_location = any(keyword in location_norm for keyword in filters['location_skip_keywords'])
    should_skip_title = any(
        _title_skip_keyword_applies(keyword, title_norm, job_title)
        for keyword in filters['job_title_skip_keywords']
    )
    title_words = title_norm.split()
    should_skip_title_2 = any(
        keyword.lower() in title_words for keyword in filters['job_title_skip_keywords_2']
    )
    should_skip_company = any(
        keyword in normalize_company_name(company_name) for keyword in filters['company_skip_keywords']
    )

    if should_skip_title or should_skip_title_2:
        return True, 'Job title contains unwanted technology'
    elif should_skip_location:
        return True, 'Location not preferred'
    elif should_skip_company:
        return True, 'Company name contains unwanted keyword'

    # Positive targeting: after skip keywords (which always win), drop jobs that
    # don't match any configured require-keyword. No-op when require lists are empty.
    require_matched, require_reason = _require_keywords_matched(
        job_title, job_description, filters
    )
    if not require_matched:
        return True, require_reason

    return False, None


REMOVED_LEVEL_TITLE_KEYWORDS = frozenset({"lead", "staff", "principal"})


def _other_title_skip_keyword_matches(title_norm: str, title_words: list[str], filters: dict) -> bool:
    """True when a non-removed skip keyword still matches the title."""
    for keyword in filters.get("job_title_skip_keywords") or []:
        if keyword.lower() in REMOVED_LEVEL_TITLE_KEYWORDS:
            continue
        if keyword.lower() in title_norm:
            return True
    for keyword in filters.get("job_title_skip_keywords_2") or []:
        if keyword.lower() in title_words:
            return True
    return False


def _was_filtered_only_by_removed_level_keywords(title: str, filters: dict | None = None) -> bool:
    """True when Lead/Staff/Principal were the only title skip keywords that matched."""
    filters = filters or _get_job_filters()
    title_norm = _normalize_title_for_filter(title)
    if not title_norm:
        return False
    if _other_title_skip_keyword_matches(title_norm, title_norm.split(), filters):
        return False
    if not any(kw in title_norm for kw in REMOVED_LEVEL_TITLE_KEYWORDS):
        return False
    skip, _ = _apply_keyword_filters(title, "", "", filters)
    return not skip


def restore_jobs_filtered_by_removed_level_keywords(db) -> int:
    """Clear Poor-fit keyword marks on jobs that were filtered only by Lead/Staff/Principal."""
    filters = _get_job_filters()
    restored = 0
    for row in db.get_all_jobs():
        if not row.get("Job Title"):
            continue
        if row.get("Applied") == "TRUE" or row.get("Job posting expired") == "TRUE":
            continue

        analysis = (row.get("Job analysis") or "").strip()
        fit = (row.get("Fit score") or "").strip()
        if fit not in ("Poor fit", "Very poor fit", "Questionable fit"):
            continue
        if "Senior machine learning specialist" in analysis or "ML role above medior" in analysis:
            continue
        if analysis and "unwanted technology" not in analysis.lower():
            continue
        if not _was_filtered_only_by_removed_level_keywords(row.get("Job Title", ""), filters):
            continue

        job_url = row.get("Job URL", "").strip()
        company_name = row.get("Company Name", "").strip()
        if not job_url or not company_name:
            continue

        db.update_job_by_key(
            job_url,
            company_name,
            {
                "Fit score": "",
                "Fit score enum": str(fit_score_to_enum("")),
                "Job analysis": "",
                "Bulk filtered": "FALSE",
            },
        )
        restored += 1
        print(f"  Restored: {row.get('Job Title')} @ {company_name}")

    if restored:
        print(f"Lead/Staff/Principal restore: cleared keyword filter on {restored} job(s).")
    return restored


# Pre-probe batch: jobs collected before 2026-07-13 Apify probe (ids 3618+).
PRE_PROBE_BATCH_MAX_ID = 3617
ULTRA_ANCIENT_MAX_ID = 999

SWE_TITLE_MARKERS = (
    "software engineer",
    "software developer",
    "backend engineer",
    "backend developer",
    "back end engineer",
    "frontend engineer",
    "front end engineer",
    "full stack",
    "fullstack",
    "data engineer",
    "platform engineer",
    "machine learning engineer",
    "ml engineer",
    "ai engineer",
    "ai/ml engineer",
    "devops",
    "site reliability",
    " sre",
    "cloud engineer",
    "python engineer",
    "distributed systems",
    "technical staff",
    "technical lead",
    "engineering lead",
    "staff engineer",
    "principal software",
    "lead software",
    "lead backend",
    "lead data engineer",
    "lead data engineer",
    "backend lead",
    "software ai engineer",
    "software/ai engineer",
    "agentic ai",
    "trading systems",
    "trading service",
    "elasticsearch",
    "databricks engineer",
    "web 3 lead engineer",
    "member of technical staff",
    "performance engineer",
    "innovation engineer",
    "ai ops engineer",
    "ai platform lead",
)

NON_SWE_TITLE_MARKERS = (
    "structural engineer",
    "piping project",
    "civil project",
    "hotel & real estate",
    "real estate segment",
    "industrial engineer",
    "manufacturing process",
    "lead mfg eng",
    "lead engineer, electrical",
    "lead engineer, manufacturing",
    "e&i lead",
    "fleet cross",
    "functional verification",
    "principal dft",
    "dft engineer",
    "technicien de maintenance",
    "excitation systems",
    "contact centre",
    "contact center",
    "service team leader",
    "group contact centre",
    "itsm lead",
    "segment lead, east asia",
    "smart manufacturing",
    "data scientist",
    "applied scientist",
    "product gtm",
    "operations lead, search",
    "quality assurance automation lead",
    "lead service engineer",
    "squad lead",  # often non-engineering team lead without software in title
)


def _title_looks_swe(title: str) -> bool:
    """True when the title clearly indicates a software/data engineering role."""
    t = _normalize_title_for_filter(title)
    if not t:
        return False
    return any(marker in t for marker in SWE_TITLE_MARKERS)


def _title_looks_non_swe(title: str) -> bool:
    """True when the title clearly indicates a non-software role."""
    if _title_looks_swe(title):
        return False
    t = _normalize_title_for_filter(title)
    if not t:
        return False
    if any(marker in t for marker in NON_SWE_TITLE_MARKERS):
        return True
    if "solutions engineer" in t:
        return True
    if "lead engineer" in t and not _title_looks_swe(title):
        return True
    if "segment lead" in t:
        return True
    if "product engineer" in t and "software" not in t:
        return True
    return False


def _job_is_ancient(row: dict) -> bool:
    job_id = row.get("_id")
    if job_id is None:
        return False
    if job_id <= ULTRA_ANCIENT_MAX_ID:
        return True
    has_date = bool((row.get("Date added") or "").strip())
    if job_id <= PRE_PROBE_BATCH_MAX_ID and not has_date:
        return not _title_looks_swe(row.get("Job Title", ""))
    return False


def _should_expire_restored_fossil(row: dict) -> bool:
    if row.get("Applied") == "TRUE" or row.get("Job posting expired") == "TRUE":
        return False
    title = row.get("Job Title", "")
    if _title_looks_non_swe(title):
        return True
    return _job_is_ancient(row)


def expire_ancient_or_non_swe_restored_jobs(db) -> int:
    """Mark restored Lead/Staff/Principal jobs expired when ancient or non-SWE."""
    expired = 0
    for row in db.get_all_jobs():
        if not row.get("Job Title"):
            continue
        if (row.get("Fit score") or "").strip() or (row.get("Job analysis") or "").strip():
            continue
        if row.get("Bulk filtered") == "TRUE":
            continue
        if not _was_filtered_only_by_removed_level_keywords(row.get("Job Title", "")):
            continue
        if not _should_expire_restored_fossil(row):
            continue

        job_url = row.get("Job URL", "").strip()
        company_name = row.get("Company Name", "").strip()
        if not job_url or not company_name:
            continue

        db.update_job_by_key(job_url, company_name, {"Job posting expired": "TRUE"})
        expired += 1
        print(f"  Expired: {row.get('Job Title')} @ {company_name}")

    if expired:
        print(f"Ancient/non-SWE cleanup: marked {expired} job(s) expired.")
    return expired


def get_sustainability_keyword_matches(job_title, company_name, raw_location, company_overview, filters):
    """
    Check sustainability_criteria positive/negative keywords (substring, case-insensitive).
    Returns (should_skip_by_negative, reason_if_skip, matches_str).
    matches_str: "negative: X" if skipped, else "positive: A, B" or "".
    """
    criteria = (filters.get('sustainability_criteria') or {})
    neg_list = criteria.get('negative')
    pos_list = criteria.get('positive')
    negative = [str(k).strip() for k in (neg_list if isinstance(neg_list, list) else [])]
    positive = [str(k).strip() for k in (pos_list if isinstance(pos_list, list) else [])]
    if not negative and not positive:
        return False, None, ''

    use_overview = criteria.get('use_company_overview_for_sustainability_keywords', True)
    search_parts = [job_title or '', (company_name or '').lower(), (raw_location or '').lower()]
    if use_overview and (company_overview or '').strip():
        search_parts.append((company_overview or '').lower())
    search_text = ' '.join(search_parts).lower()

    for kw in negative:
        if not kw:
            continue
        if kw.lower() in search_text:
            return True, f'Sustainability negative keyword: {kw}', f'negative: {kw}'

    found_positive = [kw for kw in positive if kw and kw.lower() in search_text]
    matches_str = f'positive: {", ".join(found_positive)}' if found_positive else ''
    return False, None, matches_str


def _apply_sustainability_keyword_filters(job_title, company_name, raw_location, company_overview, filters):
    """Apply sustainability keyword lists. Returns (should_skip, reason, matches_str)."""
    should_skip, reason, matches_str = get_sustainability_keyword_matches(
        job_title, company_name, raw_location, company_overview, filters
    )
    return should_skip, reason, matches_str


def check_and_process_filters(
    job_title: str,
    company_name: str,
    raw_location: str,
    company_overview: str = "",
    job_description: str = "",
    db=None,
) -> FilterResult:
    """
    Check job details against skip keywords and sustainability. Returns a FilterResult.
    """
    filters = _get_job_filters()

    should_skip, skip_reason = _apply_keyword_filters(
        job_title, company_name, raw_location, filters, job_description
    )
    if should_skip:
        print(f"Skipping job due to filter: {job_title} @ {company_name}. Reason: {skip_reason}")
        return FilterResult(
            fit_score="Poor fit",
            fit_score_enum=fit_score_to_enum("Poor fit"),
            analysis_reason=skip_reason,
            is_sustainable=None,
            bulk_filtered="TRUE",
            sustainability_keyword_matches="",
        )

    should_skip_sust, sust_reason, sustainability_keyword_matches = _apply_sustainability_keyword_filters(
        job_title, company_name, raw_location, company_overview or "", filters
    )
    if should_skip_sust:
        print(f"Skipping job due to filter: {job_title} @ {company_name}. Reason: {sust_reason}")
        return FilterResult(
            fit_score="Very poor fit",
            fit_score_enum=fit_score_to_enum("Very poor fit"),
            analysis_reason=sust_reason,
            is_sustainable=False,
            bulk_filtered="TRUE",
            sustainability_keyword_matches=sustainability_keyword_matches,
        )

    is_sustainable = None
    if CHECK_SUSTAINABILITY and company_overview:
        is_sustainable = is_sustainable_company(company_name, company_overview, job_description, db)

    if is_sustainable is False:
        analysis_reason = "Unsustainable company (weapons/fossil fuels/harmful industries)"
        print(f"Skipping job due to filter: {job_title} @ {company_name}. Reason: {analysis_reason}")
        return FilterResult(
            fit_score="Very poor fit",
            fit_score_enum=fit_score_to_enum("Very poor fit"),
            analysis_reason=analysis_reason,
            is_sustainable=False,
            bulk_filtered="TRUE",
            sustainability_keyword_matches=sustainability_keyword_matches,
        )

    return FilterResult(
        fit_score="",
        fit_score_enum=fit_score_to_enum(""),
        analysis_reason="",
        is_sustainable=is_sustainable,
        bulk_filtered="FALSE",
        sustainability_keyword_matches=sustainability_keyword_matches,
    )


def _normalize_job_title(job_title):
    """Cleans up the job title."""
    if not job_title or not isinstance(job_title, str):
        return ''
    job_title = job_title.strip()
    if not job_title:
        return ''

    lines = job_title.split('\n')
    if len(lines) == 1:
        return job_title

    first_line = lines[0]
    is_duplicate = (len(set(lines)) == 1 or first_line in lines[1] or lines[1] in first_line)

    return first_line if is_duplicate else job_title


def _build_company_overview_cache(db):
    """Build a dictionary of company name -> company overview from existing database records."""
    all_rows = db.get_all_records()
    cache = {}
    for row in all_rows:
        company_name = row.get('Company Name', '').strip()
        company_overview = row.get('Company overview', '').strip()
        if company_name and company_overview:
            company_key = normalize_company_name(company_name)
            if company_key not in cache:
                cache[company_key] = company_overview
    return cache


def apply_keyword_filters_to_existing_jobs(db) -> int:
    """Mark existing jobs matching hard title/geo rules as Poor fit."""
    from local_storage import delete_cover_letter_local, get_local_file_path
    from .resumes import delete_resume_local

    user_name = None
    try:
        from api_methods import get_resume_json
        from utils import get_user_name

        user_name = get_user_name(get_resume_json()).replace(" ", "_")
    except Exception:
        pass

    updated = 0
    for row in db.get_all_jobs():
        if not row.get("Job Title"):
            continue
        if row.get("Applied") == "TRUE" or row.get("Job posting expired") == "TRUE":
            continue

        title = row.get("Job Title", "")
        location = row.get("Location", "")
        description = row.get("Job Description", "")
        filters = _get_job_filters()
        skip, reason = _apply_keyword_filters(
            title, row.get("Company Name", ""), location, filters, description
        )
        if not skip and _title_matches_junior_entry_nextjs(title):
            skip, reason = True, "Job title contains unwanted technology"

        if not skip:
            continue

        job_url = row.get("Job URL", "").strip()
        company_name = row.get("Company Name", "").strip()
        if not job_url or not company_name:
            continue

        analysis = (row.get("Job analysis") or "").strip()
        if reason in analysis:
            continue

        updates = {
            "Fit score": "Poor fit",
            "Fit score enum": str(fit_score_to_enum("Poor fit")),
            "Job analysis": reason,
            "Bulk filtered": "TRUE",
        }
        if row.get("Tailored resume url"):
            delete_resume_local(row.get("Tailored resume url"))
            updates["Tailored resume url"] = ""
            updates["Tailored resume json"] = ""
        if row.get("Tailored cover letter (to be humanized)"):
            if user_name:
                company_safe = company_name.replace(" ", "_")
                cl_filename = get_local_file_path(user_name, company_safe, "cover_letter")
                delete_cover_letter_local(f"local_data/cover_letters/{cl_filename}")
            updates["Tailored cover letter (to be humanized)"] = ""

        db.update_job_by_key(job_url, company_name, updates)
        updated += 1
        print(f"  Keyword-filtered: {row.get('Job Title')} @ {company_name}")

    if updated:
        print(f"Title keyword cleanup: updated {updated} job(s).")
    return updated
