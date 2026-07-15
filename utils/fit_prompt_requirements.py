"""Shared candidate requirements injected into LLM fit-scoring prompts."""

MINIMUM_SALARY_USD_MONTHLY = 5000

TOP_FIT_SCORE_REQUIREMENTS_SECTION = """
Top fit score rules (Very good fit):
- Only assign "Very good fit" when the company appears clearly mission-driven and aligned with sustainability / ethical impact based on the company overview and job description.
- If sustainability / mission impact is unclear, cap at "Good fit" and mention uncertainty briefly.
- If the role is in an unsustainable or ethically problematic industry (e.g. fossil fuels, weapons, gambling), never assign "Very good fit".
- If the company is primarily staffing / recruiting / job marketplace / generic outsourcing, cap at "Good fit" even if the role matches well.
"""

SALARY_FIT_PROMPT_SECTION = f"""
CRITICAL compensation requirement:
- The candidate requires gross compensation of at least USD ${MINIMUM_SALARY_USD_MONTHLY:,}/month (or clearly equivalent in EUR/other currency).
- If the job description states a salary range whose maximum is below this threshold, score "Poor fit" or "Very poor fit".
- If compensation is implied to be well below this level (e.g. junior pay band, unpaid internship, stipend-only), score "Poor fit" or "Very poor fit".
- If salary is not mentioned, do not heavily penalize; note uncertainty briefly in reasoning.
"""

JD_SALARY_FIT_PROMPT_SECTION = f"""
CRITICAL compensation requirement:
- The candidate requires at least USD ${MINIMUM_SALARY_USD_MONTHLY:,}/month gross (or equivalent).
- If the JD states a max salary below this, set jd_fit_score to 3 or lower.
- If pay is clearly far below this level, set jd_fit_score to 2 or lower.
- If salary is unstated, score on skills fit only but mention pay is unknown when relevant.
"""
