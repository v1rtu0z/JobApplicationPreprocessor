"""Sustainability checks via Gemini: single/bulk company and validation pipeline."""

import json
import os

import google.genai as genai

from config import _get_job_filters

from .apify_client import rate_limit
from .gemini_rate_limit import mark_gemini_rate_limit_hit
from .gemini_throttle import acquire_gemini_slot
from .parsing import fit_score_to_enum, normalize_company_name
from .prompts import render_prompt


def _call_gemini_for_sustainability(prompt: str, key_name_context: str = "") -> dict | None:
    """Common logic for calling Gemini API with fallback for sustainability checks."""
    acquire_gemini_slot()
    api_keys = [
        ('primary', os.getenv("GEMINI_API_KEY")),
        ('backup', os.getenv("BACKUP_GEMINI_API_KEY"))
    ]

    for key_name, api_key in api_keys:
        if not api_key:
            if key_name == 'primary':
                print("Warning: GEMINI_API_KEY not found, trying backup...")
                continue
            else:
                print("Warning: Both API keys not found")
                return None

        try:
            client = genai.Client(api_key=api_key)

            model_name = os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')
            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )

            response_text = response.text.strip()
            cleaned = response_text.replace('```json', '').replace('```', '').strip()
            result = json.loads(cleaned)

            return result

        except Exception as e:
            error_msg = str(e)
            is_rate_limit = '429' in error_msg or 'Rate limit' in error_msg or 'ResourceExhausted' in error_msg or 'quota' in error_msg.lower()
            if is_rate_limit:
                mark_gemini_rate_limit_hit()

            if key_name == 'primary':
                print(f"Error with {key_name} key{' for ' + key_name_context if key_name_context else ''}: {e}")
                print("  → Trying backup key...")
                continue
            else:
                print(f"Error with {key_name} key{' for ' + key_name_context if key_name_context else ''}: {e}")
                return None

    mark_gemini_rate_limit_hit()
    return None


def _build_sustainability_cache(db):
    """Build a dictionary of company name -> sustainability status from existing database records."""
    all_rows = db.get_all_records()
    cache = {}
    for row in all_rows:
        company_name = row.get('Company Name', '').strip()
        if not company_name:
            continue

        company_key = normalize_company_name(company_name)
        if company_key not in cache:
            sustainable = row.get('Sustainable company', '').strip()
            if sustainable in ['TRUE', 'FALSE']:
                cache[company_key] = sustainable
    return cache


def get_sustainability_from_sheet(company_name: str, db, cache: dict = None) -> str | None:
    """Check if sustainability status is already known for a company."""
    if cache is None:
        cache = _build_sustainability_cache(db)

    company_key = normalize_company_name(company_name)
    return cache.get(company_key)


def _strip_company_suffix(name: str) -> str:
    """Normalize and drop common legal suffixes for bulk API name matching."""
    normalized = normalize_company_name(name)
    for suffix in (
        " incorporated", " inc.", " inc", " ltd.", " ltd", " llc", " corp.", " corp",
        " gmbh", " sa", " plc", " co.", " co",
    ):
        if normalized.endswith(suffix):
            return normalized[: -len(suffix)].strip(" ,.")
    return normalized


def _resolve_bulk_sustainability_result(company_name: str, batch_results: dict) -> dict | None:
    """Match a DB company name to a bulk Gemini response key."""
    if company_name in batch_results:
        return batch_results[company_name]

    keyed = {normalize_company_name(key): value for key, value in batch_results.items()}
    company_key = normalize_company_name(company_name)
    if company_key in keyed:
        return keyed[company_key]

    stripped = _strip_company_suffix(company_name)
    for key, value in batch_results.items():
        if _strip_company_suffix(key) == stripped:
            return value
    return None


def is_sustainable_company_bulk(companies_data: list[dict], db=None) -> dict[str, dict]:
    """Determine sustainability for multiple companies in bulk."""
    results = {}

    sustainability_cache = None
    if db:
        sustainability_cache = _build_sustainability_cache(db)

    remaining_companies = []
    for data in companies_data:
        name = data['company_name']
        if db and sustainability_cache:
            cached_result = get_sustainability_from_sheet(name, db, cache=sustainability_cache)
            if cached_result is not None:
                results[name] = {
                    'is_sustainable': cached_result == 'TRUE',
                    'reasoning': 'Cached from sheet'
                }
                continue

        if not (data.get('company_overview') or '').strip():
            results[name] = {
                'is_sustainable': None,
                'reasoning': 'Insufficient company overview'
            }
            continue

        remaining_companies.append(data)

    if not remaining_companies:
        return results

    filters = _get_job_filters()
    criteria = filters.get('sustainability_criteria', {})
    positive_list = "\n".join([f"- {c}" for c in criteria.get('positive', [])])
    negative_list = "\n".join([f"- {c}" for c in criteria.get('negative', [])])

    companies_text = ""
    for i, data in enumerate(remaining_companies):
        companies_text += f"""
--- Company {i+1} ---
Name: {data['company_name']}
Overview: {data['company_overview']}
Job Description snippet: {data['job_description'][:500] if data['job_description'] else "N/A"}
"""

    prompt = render_prompt(
        "sustainability_bulk",
        companies_text=companies_text,
        positive_list=positive_list,
        negative_list=negative_list,
    )

    batch_results = _call_gemini_for_sustainability(prompt, "bulk check")

    if batch_results:
        for data in remaining_companies:
            name = data['company_name']
            res = _resolve_bulk_sustainability_result(name, batch_results)
            if res is not None:
                is_sust = res.get('is_sustainable')
                reason = res.get('reasoning', 'No reasoning provided')
                results[name] = {
                    'is_sustainable': is_sust,
                    'reasoning': reason
                }

                if is_sust is False:
                    print(f"  ⚠️  Bulk Sustainability check: {name} -> False")
                    print(f"      Reason: {reason}")
                else:
                    print(f"  ✓  Bulk Sustainability check: {name} -> True")
            else:
                print(f"Warning: Result for {name} missing from bulk API response")
                results[name] = {'is_sustainable': None, 'reasoning': 'Missing from API response'}
    else:
        for data in remaining_companies:
            results[data['company_name']] = {'is_sustainable': None, 'reasoning': 'API Error'}

    return results


def is_sustainable_company(company_name: str, company_overview: str, job_description: str, db=None) -> bool | None:
    """Determine if a company is sustainable. Checks cache first to avoid redundant API calls."""
    if db:
        sustainability_cache = _build_sustainability_cache(db)
        cached_result = get_sustainability_from_sheet(company_name, db, cache=sustainability_cache)
        if cached_result is not None:
            return cached_result == 'TRUE'

    if not (company_overview or '').strip():
        return None

    print(f"Checking sustainability for: {company_name}")

    filters = _get_job_filters()
    criteria = filters.get('sustainability_criteria', {})
    positive_list = "\n".join([f"- {c}" for c in criteria.get('positive', [])])
    negative_list = "\n".join([f"- {c}" for c in criteria.get('negative', [])])

    prompt = render_prompt(
        "sustainability_single",
        company_name=company_name,
        company_overview=company_overview,
        job_description_excerpt=(
            job_description[:1000] if job_description else "Not available"
        ),
        positive_list=positive_list,
        negative_list=negative_list,
    )

    result = _call_gemini_for_sustainability(prompt, company_name)

    if result:
        if "is_sustainable" not in result:
            print(f"  ⚠️  Sustainability check: {company_name} -> inconclusive (missing is_sustainable)")
            return None

        is_sustainable = result.get("is_sustainable")
        if is_sustainable is None:
            print(f"  ⚠️  Sustainability check: {company_name} -> inconclusive (null is_sustainable)")
            return None

        reasoning = result.get("reasoning", "No reasoning provided")

        if not is_sustainable:
            print(f"  ⚠️  Sustainability check: {company_name} -> False")
            print(f"      Reason: {reasoning}")
        else:
            print(f"  ✓  Sustainability check: {company_name} -> True")

        return is_sustainable
    else:
        print(f"Both API keys failed for {company_name}, returning None")
        return None


def validate_sustainability_for_unprocessed_jobs(db, target_job_keys=None):
    """Process sustainability checks for jobs that have overview but no definitive Sustainable value."""
    print("\n" + "=" * 60)
    print("SUSTAINABILITY VALIDATION: Checking unprocessed companies")
    print("=" * 60 + "\n")
    if target_job_keys is not None:
        print(f"Scoped to dashboard default filter ({len(target_job_keys)} jobs).\n")

    all_rows = db.get_all_records()
    companies_to_check = []
    companies_seen = set()

    for row in all_rows:
        if row.get('Applied') == 'TRUE' or row.get('Job posting expired') == 'TRUE':
            continue

        job_url = (row.get('Job URL') or '').strip()
        company_name_row = (row.get('Company Name') or '').strip()
        if target_job_keys is not None and (job_url, company_name_row) not in target_job_keys:
            continue

        # Include companies with Bad analysis jobs so they get validated first, then analysis can run
        if row.get('Bad analysis') != 'TRUE':
            if row.get('Fit score') in ['Poor fit', 'Very poor fit', 'Moderate fit', 'Questionable fit']:
                continue

        sustainable_value = str(row.get('Sustainable company', '')).strip().upper()
        if sustainable_value in ['TRUE', 'FALSE']:
            continue

        company_overview = row.get('Company overview', '').strip()
        if not company_overview:
            continue

        company_name = row.get('Company Name', '').strip()
        if not company_name:
            continue

        company_key = normalize_company_name(company_name)
        if company_key in companies_seen:
            continue

        companies_seen.add(company_key)
        companies_to_check.append({
            'company_name': company_name,
            'company_overview': company_overview,
            'job_description': row.get('Job Description', '')
        })

    if not companies_to_check:
        print("No companies need sustainability validation.")
        return 0

    names = [c['company_name'] for c in companies_to_check]
    print(f"Found {len(companies_to_check)} companies to check for sustainability: {', '.join(names)}")

    batch_size = 10
    total_processed = 0

    for i in range(0, len(companies_to_check), batch_size):
        batch = companies_to_check[i:i + batch_size]
        print(f"\nProcessing batch {i // batch_size + 1} ({len(batch)} companies)...")

        batch_results = is_sustainable_company_bulk(batch, db=db)

        for company_name, result in batch_results.items():
            is_sustainable = result['is_sustainable']
            reasoning = result['reasoning']

            if is_sustainable is None:
                continue

            sustainability_value = 'TRUE' if is_sustainable else 'FALSE'
            company_key = normalize_company_name(company_name)
            bulk_updates = []

            for row in all_rows:
                row_company = row.get('Company Name', '').strip()
                job_url = row.get('Job URL', '').strip()

                if not job_url or not row_company:
                    continue

                if normalize_company_name(row_company) != company_key:
                    continue

                updates = {'Sustainable company': sustainability_value}

                if not is_sustainable and not row.get('Fit score'):
                    updates.update({
                        'Fit score': 'Very poor fit',
                        'Fit score enum': str(fit_score_to_enum('Very poor fit')),
                        'Job analysis': f'Unsustainable company: {reasoning}'
                    })

                bulk_updates.append((job_url, row.get('Company Name', ''), updates))

            if bulk_updates:
                db.bulk_update_by_key(bulk_updates)
                total_processed += 1

    print(f"\nSustainability validation completed. Processed {total_processed} companies.")
    return total_processed
