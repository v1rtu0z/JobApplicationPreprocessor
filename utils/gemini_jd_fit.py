"""JD-only job fit scoring via Gemini (1-10), for prioritization when full analysis is blocked."""

import json
import os
import re
import time

import google.genai as genai

from .gemini_rate_limit import mark_gemini_rate_limit_hit
from .prompts import render_prompt

JD_DESCRIPTION_MAX_CHARS = 3500


def _build_jd_fit_prompt(resume_json: dict, job_details_list: list[dict]) -> str:
    resume_str = json.dumps(resume_json, indent=2)
    jobs_text = ""
    for i, job in enumerate(job_details_list, 1):
        job_id = f"{job.get('job_title', '')} @ {job.get('company_name', '')}"
        desc = (job.get('job_description') or '')[:JD_DESCRIPTION_MAX_CHARS]
        location = job.get('location') or ''
        jobs_text += f"""
--- Job {i} (job_id: {job_id}) ---
Company: {job.get('company_name', '')}
Title: {job.get('job_title', '')}
Location: {location}
Job description (excerpt):
{desc}
"""
    return render_prompt(
        "jd_fit",
        salary_section=render_prompt("jd_salary_fit"),
        resume_json=resume_str,
        jobs_text=jobs_text,
    )


def _extract_response_text(response) -> str:
    """Extract text from Gemini response, including thinking-model part layouts."""
    if response is None:
        return ''
    text = getattr(response, 'text', None)
    if text and str(text).strip():
        return str(text).strip()

    candidates = getattr(response, 'candidates', None) or []
    if not candidates:
        return ''

    content = getattr(candidates[0], 'content', None)
    parts = getattr(content, 'parts', None) or []
    chunks = []
    for part in parts:
        part_text = getattr(part, 'text', None)
        if part_text:
            chunks.append(str(part_text))
    return ''.join(chunks).strip()


def _is_rate_limit_error(err: str) -> bool:
    return (
        '429' in err
        or 'Rate limit' in err
        or 'ResourceExhausted' in err
        or 'quota' in err.lower()
    )


def _is_transient_error(err: str) -> bool:
    return _is_rate_limit_error(err) or '503' in err or 'UNAVAILABLE' in err or '500' in err


def _clamp_score(value) -> int | None:
    try:
        score = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    if 1 <= score <= 10:
        return score
    return None


def _parse_jd_fit_response(text: str) -> list[dict]:
    cleaned = text.replace('```json', '').replace('```', '').strip()
    array_match = re.search(r'\[[\s\S]*\]', cleaned)
    if array_match:
        cleaned = array_match.group(0)
    data = json.loads(cleaned)
    if not isinstance(data, list):
        print(f'Warning: JD fit scoring returned non-array: {type(data)}')
        return []

    result = []
    for item in data:
        if not isinstance(item, dict):
            continue
        score = _clamp_score(item.get('jd_fit_score'))
        if score is None:
            continue
        result.append({
            'job_id': item.get('job_id') or '',
            'jd_fit_score': score,
            'reasoning': (item.get('reasoning') or '').strip() or 'No reasoning provided',
        })
    return result


def score_jobs_by_jd_batch(
    resume_json: dict,
    job_details_list: list[dict],
) -> list[dict]:
    """
    Score jobs 1-10 from resume + JD only.
    Returns list of dicts: job_id, jd_fit_score (int), reasoning.
    """
    if not job_details_list:
        return []

    api_keys = [
        ('primary', os.getenv('GEMINI_API_KEY')),
        ('backup', os.getenv('BACKUP_GEMINI_API_KEY')),
    ]
    model_name = os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')
    prompt = _build_jd_fit_prompt(resume_json, job_details_list)
    last_error = None

    for key_name, api_key in api_keys:
        if not api_key:
            if key_name == 'primary':
                print('Warning: GEMINI_API_KEY not found, trying backup...')
                continue
            print('Warning: Both Gemini API keys not found.')
            return []

        for attempt in range(3):
            try:
                client = genai.Client(api_key=api_key)
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                text = _extract_response_text(response)
                if not text:
                    raise ValueError('Empty response from Gemini')
                return _parse_jd_fit_response(text)

            except json.JSONDecodeError as e:
                last_error = e
                print(f'JD fit scoring parse error ({key_name}, attempt {attempt + 1}/3): {e}')
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                break

            except Exception as e:
                last_error = e
                err = str(e)
                if _is_rate_limit_error(err):
                    mark_gemini_rate_limit_hit()
                if _is_transient_error(err) and attempt < 2:
                    wait = min(15 * (2 ** attempt), 120)
                    print(f'JD fit scoring transient error ({key_name}, attempt {attempt + 1}/3): {e}')
                    print(f'  → Retrying in {wait}s...')
                    time.sleep(wait)
                    continue
                if key_name == 'primary':
                    print(f'JD fit scoring error ({key_name}): {e}')
                    print('  → Trying backup key...')
                    break
                print(f'JD fit scoring error ({key_name}): {e}')
                return []

    if last_error:
        print(f'JD fit scoring failed after retries: {last_error}')
        if _is_rate_limit_error(str(last_error)):
            mark_gemini_rate_limit_hit()
    return []
