"""Editable LLM prompt templates (defaults + optional overrides in job_preferences.yaml)."""

from __future__ import annotations

import re
from typing import Any

from utils.fit_prompt_requirements import MINIMUM_SALARY_USD_MONTHLY

# Placeholders use {name} with only [a-z0-9_]+ names so JSON examples stay intact.

PROMPT_META: dict[str, dict[str, str]] = {
    "top_fit_score_requirements": {
        "label": "Top fit score rules (Very good fit)",
        "placeholders": "(injected into Fit score batch as {top_fit_requirements})",
    },
    "salary_fit": {
        "label": "Salary rules — full fit analysis",
        "placeholders": "{minimum_salary_usd_monthly}",
    },
    "jd_salary_fit": {
        "label": "Salary rules — JD-only fit scoring",
        "placeholders": "{minimum_salary_usd_monthly}",
    },
    "fit_score_batch": {
        "label": "Fit score batch analysis",
        "placeholders": "{top_fit_requirements}, {salary_section}, {resume_json}, {jobs_text}, {fit_scores_json}",
    },
    "jd_fit": {
        "label": "JD-only fit scoring (1–10)",
        "placeholders": "{salary_section}, {resume_json}, {jobs_text}",
    },
    "search_parameters": {
        "label": "LinkedIn search parameter generation",
        "placeholders": "{resume_json}, {additional_details}, {location_line}",
    },
    "bulk_filter": {
        "label": "Bulk job-title filter",
        "placeholders": "{user_name}, {resume_json}, {job_count}, {job_titles_json}",
    },
    "sustainability_bulk": {
        "label": "Sustainability check (bulk)",
        "placeholders": "{companies_text}, {positive_list}, {negative_list}",
    },
    "sustainability_single": {
        "label": "Sustainability check (single company)",
        "placeholders": "{company_name}, {company_overview}, {job_description_excerpt}, {positive_list}, {negative_list}",
    },
}

DEFAULT_PROMPTS: dict[str, str] = {
    "top_fit_score_requirements": """Top fit score rules (Very good fit):
- Only assign "Very good fit" when the company appears clearly mission-driven and aligned with sustainability / ethical impact based on the company overview and job description.
- If sustainability / mission impact is unclear, cap at "Good fit" and mention uncertainty briefly.
- If the role is in an unsustainable or ethically problematic industry (e.g. fossil fuels, weapons, gambling), never assign "Very good fit".
- If the company is primarily staffing / recruiting / job marketplace / generic outsourcing, cap at "Good fit" even if the role matches well.""",
    "salary_fit": """CRITICAL compensation requirement:
- The candidate requires gross compensation of at least USD ${minimum_salary_usd_monthly}/month (or clearly equivalent in EUR/other currency).
- If the job description states a salary range whose maximum is below this threshold, score "Poor fit" or "Very poor fit".
- If compensation is implied to be well below this level (e.g. junior pay band, unpaid internship, stipend-only), score "Poor fit" or "Very poor fit".
- If salary is not mentioned, do not heavily penalize; note uncertainty briefly in reasoning.""",
    "jd_salary_fit": """CRITICAL compensation requirement:
- The candidate requires at least USD ${minimum_salary_usd_monthly}/month gross (or equivalent).
- If the JD states a max salary below this, set jd_fit_score to 3 or lower.
- If pay is clearly far below this level, set jd_fit_score to 2 or lower.
- If salary is unstated, score on skills fit only but mention pay is unknown when relevant.""",
    "fit_score_batch": """You are a professional career assistant. Compare the candidate's resume to each job below and assign a fit score per job.

{top_fit_requirements}

{salary_section}

Resume data JSON (same candidate for all jobs):
{resume_json}

Jobs to analyze:
{jobs_text}

For each job, output exactly one object with:
- "job_id": the exact "Title @ Company" string given for that job
- "fit_score": one of {fit_scores_json}
- "reasoning": one or two short sentences

Respond with ONLY a JSON array of these objects, one per job, in the same order as the jobs above. No other text.
Example: [{{"job_id": "Engineer @ Acme", "fit_score": "Good fit", "reasoning": "..."}}]""",
    "jd_fit": """You are a professional career assistant. Score how well each job fits the candidate using ONLY the resume and job description below (ignore company sustainability or culture; no company overview is available).

{salary_section}

Resume data JSON:
{resume_json}

Jobs to score:
{jobs_text}

For each job, output exactly one object with:
- "job_id": the exact "Title @ Company" string given for that job
- "jd_fit_score": integer from 1 (very poor fit) to 10 (excellent fit)
- "reasoning": one short sentence

Respond with ONLY a JSON array of these objects, one per job, in the same order as above. No markdown, no commentary.
Example: [{{"job_id": "Engineer @ Acme", "jd_fit_score": 8, "reasoning": "Strong Python overlap."}}]""",
    "search_parameters": """Based on the following resume and additional details, generate a list of search parameters for LinkedIn job searches.
The goal is to find jobs that are a good fit for the user's background and preferences.

IMPORTANT geographic scope:
- Only search within EMEA (Europe, Middle East, Africa). Prefer concrete countries LinkedIn accepts: Italy, Spain, Germany, Netherlands, Serbia, Croatia, Montenegro, Bosnia and Herzegovina.
- Include one worldwide-remote search (location: "Worldwide", remote filter on) for global remote roles; post-filters enforce CET/EET-friendly timezones.
- Do NOT use broad ambiguous locations like plain "Remote" alone (pulls US/APAC); use "Worldwide" for global remote or a specific country.
- Avoid "European Union" / "European Economic Area" as location strings (LinkedIn often rejects them); use specific countries instead.
- Do NOT target United Kingdom as a primary search location (UK roles are only kept when globally remote).
- For Serbia, Croatia, Montenegro, and Bosnia and Herzegovina: always set remote: remote (candidate speaks local languages and prefers remote roles there).

Resume:
{resume_json}

Additional Details:
{additional_details}{location_line}

Return a JSON list of objects. Each object should have:
- keywords: string (e.g., "Software Engineer", "Project Manager", "Data Scientist")
- location: string (e.g., "Remote", "London", "United States", "New York")
- remote: string (one of: "onsite", "remote", "hybrid") - default to "remote" if not specified
- experienceLevel: string (one of: "internship", "entry", "associate", "mid_senior", "director", "executive") - infer from resume
- date_posted: string (one of: "month", "week", "day") - default to "week"
- limit: integer (number of results, default to 100)

Provide 3-5 diverse search queries OR describe a search_matrix with separate keywords and locations lists.
When using search_matrix, provide distinct keyword strings and location strings; the system expands every keyword across every location automatically.

You must respond with ONLY a JSON array, no other text. Example format:
[
  {{
    "keywords": "Software Engineer",
    "location": "Remote",
    "remote": "remote",
    "experienceLevel": "mid_senior",
    "date_posted": "week",
    "limit": 100
  }},
  {{
    "keywords": "Senior Developer",
    "location": "United States",
    "remote": "hybrid",
    "experienceLevel": "mid_senior",
    "date_posted": "week",
    "limit": 100
  }}
]""",
    "bulk_filter": """You are helping {user_name} filter job opportunities.

Resume JSON:
{resume_json}

Here are {job_count} job opportunities.

CONTEXT:
We are building an iterative keyword-based filtering system to save costs on future searches.
1. Identify specific job titles that are clearly NOT a good fit.
2. Identify generalizable "skip keywords" (substrings) for titles and company names that should ALWAYS be filtered out in the future.

CRITERIA FOR FILTERING:
1. Wrong technology stack or role requirements compared to the resume
2. Wrong role type (e.g., mismatch between desired level or functional area)
3. Wrong domain or industry that is clearly incompatible with the candidate's goals

JOB DATA (JSON):
{job_titles_json}

Respond with ONLY a JSON object in this exact format:
{{
  "filtered_titles": ["exact job title 1", "exact job title 2"],
  "new_filters": {{
    "job_title_skip_keywords": ["keyword1", "keyword2"],
    "company_skip_keywords": ["unwanted company 1"]
  }}
}}

If ALL jobs are good fits, return: {{"filtered_titles": [], "new_filters": {{"job_title_skip_keywords": [], "company_skip_keywords": []}}}}
""",
    "sustainability_bulk": """Analyze if these companies work on something sustainability-oriented.

Sustainability here includes BOTH environmental AND social impact:
- Environmental: clean energy, climate, carbon capture, circular economy, etc.
- Social: healthcare (value-based care, patient outcomes, access to care, public health), education, poverty alleviation, social equity.

{companies_text}

Criteria for Sustainability:
Return is_sustainable: true for companies in sustainable/impact-oriented industries such as:
{positive_list}
Also return true for healthcare companies whose primary focus is improving patient outcomes, value-based care, access to care, or public health (e.g. primary care enablement, care coordination, health equity).

Return is_sustainable: false for:
{negative_list}

Return is_sustainable: false for neutral industries (banking, tech, finance, insurance, investment) UNLESS they have an explicit and primary sustainability/ESG/impact focus.

You must respond with ONLY a JSON dictionary where keys are the exact company names provided above and values are objects with "is_sustainable" (boolean) and "reasoning" (string).
Example:
{{
  "Company A": {{"is_sustainable": true, "reasoning": "Solar energy manufacturer"}},
  "Company B": {{"is_sustainable": false, "reasoning": "Defense contractor"}}
}}""",
    "sustainability_single": """Analyze if this company works on something sustainability-oriented.

Sustainability here includes BOTH environmental AND social impact:
- Environmental: clean energy, climate, carbon capture, circular economy, etc.
- Social: healthcare (value-based care, patient outcomes, access to care, public health), education, poverty alleviation, social equity.

Company Name: {company_name}

Company Overview: {company_overview}

Job Description: {job_description_excerpt}

Return True for companies in sustainable/impact-oriented industries such as:
{positive_list}
Also return True for healthcare companies whose primary focus is improving patient outcomes, value-based care, access to care, or public health (e.g. primary care enablement, care coordination, health equity).

Return False for:
{negative_list}

Return False for neutral industries (banking, tech, finance, insurance, investment) UNLESS they have explicit sustainability/ESG/impact investing focus.

You must respond with ONLY a JSON object in this exact format:
{{
  "is_sustainable": True or False,
  "reasoning": "brief explanation"
}}""",
}

_PLACEHOLDER_RE = re.compile(r"\{([a-z][a-z0-9_]*)\}")
_ESCAPED_BRACE_RE = re.compile(r"\{\{|\}\}")


def _user_prompt_overrides() -> dict[str, str]:
    from config import _get_job_filters

    raw = (_get_job_filters() or {}).get("prompts") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, val in raw.items():
        if key in DEFAULT_PROMPTS and isinstance(val, str) and val.strip():
            out[key] = val
    return out


def get_prompt_template(name: str) -> str:
    """Return the effective template for ``name`` (user override or default)."""
    if name not in DEFAULT_PROMPTS:
        raise KeyError(f"Unknown prompt: {name}")
    return _user_prompt_overrides().get(name, DEFAULT_PROMPTS[name])


def is_prompt_customized(name: str) -> bool:
    return name in _user_prompt_overrides()


def list_prompt_names() -> list[str]:
    return list(DEFAULT_PROMPTS.keys())


def render_prompt(name: str, **context: Any) -> str:
    """Fill ``{placeholders}`` in the named template. Unknown placeholders are left as-is.

    Literal ``{{`` / ``}}`` in templates become single braces (for JSON examples).
    """
    template = get_prompt_template(name)
    ctx = dict(context)
    if "minimum_salary_usd_monthly" not in ctx:
        ctx["minimum_salary_usd_monthly"] = f"{MINIMUM_SALARY_USD_MONTHLY:,}"

    def repl(match: re.Match) -> str:
        key = match.group(1)
        if key in ctx:
            return str(ctx[key])
        return match.group(0)

    # Protect doubled braces, substitute placeholders, then unescape.
    sentinels: list[tuple[str, str]] = []
    protected = template

    def stash(m: re.Match) -> str:
        token = f"\0BRACE{len(sentinels)}\0"
        sentinels.append((token, "{" if m.group(0) == "{{" else "}"))
        return token

    protected = _ESCAPED_BRACE_RE.sub(stash, protected)
    filled = _PLACEHOLDER_RE.sub(repl, protected)
    for token, ch in sentinels:
        filled = filled.replace(token, ch)
    return filled


def save_prompt_overrides(overrides: dict[str, str]) -> None:
    """Persist non-empty overrides that differ from defaults; drop keys reset to default."""
    from config import _get_job_filters, _save_job_filters

    filters = _get_job_filters()
    current = dict(filters.get("prompts") or {})
    for key, text in overrides.items():
        if key not in DEFAULT_PROMPTS:
            continue
        text = (text or "").strip()
        if not text or text == DEFAULT_PROMPTS[key].strip():
            current.pop(key, None)
        else:
            current[key] = text
    if current:
        filters["prompts"] = current
    else:
        filters.pop("prompts", None)
    _save_job_filters(filters)


def reset_prompt(name: str) -> None:
    """Remove user override for one prompt (back to default)."""
    if name not in DEFAULT_PROMPTS:
        raise KeyError(f"Unknown prompt: {name}")
    from config import _get_job_filters, _save_job_filters

    filters = _get_job_filters()
    current = dict(filters.get("prompts") or {})
    if name in current:
        current.pop(name)
        if current:
            filters["prompts"] = current
        else:
            filters.pop("prompts", None)
        _save_job_filters(filters)


def reset_all_prompts() -> None:
    from config import _get_job_filters, _save_job_filters

    filters = _get_job_filters()
    if "prompts" in filters:
        filters.pop("prompts", None)
        _save_job_filters(filters)
