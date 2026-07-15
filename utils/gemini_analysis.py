"""Batch job analysis via Gemini: one API call per N jobs, simplified JSON output."""

import json
import os
import re

import google.genai as genai

from .gemini_rate_limit import mark_gemini_rate_limit_hit
from .fit_prompt_requirements import SALARY_FIT_PROMPT_SECTION, TOP_FIT_SCORE_REQUIREMENTS_SECTION

FIT_SCORES = (
    'Very good fit',
    'Good fit',
    'Moderate fit',
    'Poor fit',
    'Very poor fit',
    'Questionable fit',
)


def _build_batch_analysis_prompt(resume_json: dict, job_details_list: list[dict]) -> str:
    """Build a single prompt: resume once, then each job. Output is a JSON array."""
    resume_str = json.dumps(resume_json, indent=2)
    jobs_text = ""
    for i, j in enumerate(job_details_list, 1):
        job_id = f"{j.get('job_title', '')} @ {j.get('company_name', '')}"
        desc = (j.get('job_description') or '')[:8000]
        location = j.get('location') or ''
        overview = (j.get('company_overview') or '')[:2000]
        jobs_text += f"""
--- Job {i} (job_id: {job_id}) ---
Company: {j.get('company_name', '')}
Title: {j.get('job_title', '')}
Location: {location}
Company overview (excerpt): {overview}
Job description (excerpt):
{desc}
"""
    return f"""You are a professional career assistant. Compare the candidate's resume to each job below and assign a fit score per job.

{TOP_FIT_SCORE_REQUIREMENTS_SECTION}

{SALARY_FIT_PROMPT_SECTION}

Resume data JSON (same candidate for all jobs):
{resume_str}

Jobs to analyze:
{jobs_text}

For each job, output exactly one object with:
- "job_id": the exact "Title @ Company" string given for that job
- "fit_score": one of {json.dumps(list(FIT_SCORES))}
- "reasoning": one or two short sentences

Respond with ONLY a JSON array of these objects, one per job, in the same order as the jobs above. No other text.
Example: [{{"job_id": "Engineer @ Acme", "fit_score": "Good fit", "reasoning": "..."}}, ...]
"""


def analyze_jobs_batch(
    resume_json: dict,
    job_details_list: list[dict],
) -> list[dict]:
    """
    Run batch job analysis: one Gemini call for all jobs in the list.
    resume_json is sent once; job_details_list contains job_title, company_name, job_description, location, company_overview per item.

    Returns list of dicts with keys: job_id, fit_score, reasoning.
    On failure (both keys 429 etc.) returns empty list and marks rate limit hit.
    """
    if not job_details_list:
        return []

    api_keys = [
        ('primary', os.getenv('GEMINI_API_KEY')),
        ('backup', os.getenv('BACKUP_GEMINI_API_KEY')),
    ]
    model_name = os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')
    prompt = _build_batch_analysis_prompt(resume_json, job_details_list)

    for key_name, api_key in api_keys:
        if not api_key:
            if key_name == 'primary':
                print('Warning: GEMINI_API_KEY not found, trying backup...')
                continue
            print('Warning: Both Gemini API keys not found.')
            return []

        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            text = (response.text or '').strip()
            cleaned = text.replace('```json', '').replace('```', '').strip()
            # Extract JSON array if wrapped in extra text
            array_match = re.search(r'\[[\s\S]*\]', cleaned)
            if array_match:
                cleaned = array_match.group(0)
            data = json.loads(cleaned)
            if not isinstance(data, list):
                print(f'Warning: Batch analysis returned non-array: {type(data)}')
                return []

            result = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                job_id = item.get('job_id') or ''
                fit = (item.get('fit_score') or '').strip()
                if fit not in FIT_SCORES:
                    fit = 'Questionable fit'
                result.append({
                    'job_id': job_id,
                    'fit_score': fit,
                    'reasoning': (item.get('reasoning') or '').strip() or 'No reasoning provided',
                })
            return result

        except Exception as e:
            err = str(e)
            if '429' in err or 'Rate limit' in err or 'ResourceExhausted' in err or 'quota' in err.lower():
                mark_gemini_rate_limit_hit()
            if key_name == 'primary':
                print(f'Batch analysis error ({key_name}): {e}')
                print('  → Trying backup key...')
                continue
            print(f'Batch analysis error ({key_name}): {e}')
            return []

    mark_gemini_rate_limit_hit()
    return []
