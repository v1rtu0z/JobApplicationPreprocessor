"""
Utils package: schema, parsing, Apify client, sustainability, storage.
Re-exports all public names for backward compatibility with `from utils import ...` and `import utils`.
"""

from .schema import JOB_COLUMNS

from .gemini_rate_limit import (
    gemini_rate_limit_hit,
    mark_gemini_rate_limit_hit,
    reset_gemini_rate_limit_flag,
)

from .parsing import (
    extract_job_id,
    fit_score_to_enum,
    get_location_priority,
    get_user_name,
    html_to_markdown,
    normalize_company_name,
    normalize_easy_apply,
    normalize_posted_at,
    parse_location,
)

from .apify_client import (
    APIFY_AVAILABLE,
    apify_jobs_search_is_cached,
    apify_state,
    fetch_job_details_bulk_via_apify,
    fetch_jobs_via_apify,
    get_company_overviews_bulk_via_apify,
    match_job_to_apify_result,
    rate_limit,
)

from .sustainability import (
    get_sustainability_from_db,
    is_sustainable_company,
    is_sustainable_company_bulk,
    validate_sustainability_for_unprocessed_jobs,
)

from .storage import (
    get_existing_job_keys,
    parse_fit_score,
    setup_database,
)

__all__ = [
    'JOB_COLUMNS',
    'gemini_rate_limit_hit',
    'mark_gemini_rate_limit_hit',
    'reset_gemini_rate_limit_flag',
    'extract_job_id',
    'fit_score_to_enum',
    'get_location_priority',
    'get_user_name',
    'html_to_markdown',
    'normalize_company_name',
    'normalize_easy_apply',
    'normalize_posted_at',
    'parse_location',
    'APIFY_AVAILABLE',
    'apify_jobs_search_is_cached',
    'apify_state',
    'fetch_job_details_bulk_via_apify',
    'fetch_jobs_via_apify',
    'get_company_overviews_bulk_via_apify',
    'match_job_to_apify_result',
    'rate_limit',
    'get_sustainability_from_db',
    'is_sustainable_company',
    'is_sustainable_company_bulk',
    'validate_sustainability_for_unprocessed_jobs',
    'get_existing_job_keys',
    'parse_fit_score',
    'setup_database',
]
