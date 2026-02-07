"""
Utils package: schema, parsing, Apify client, LinkedIn crawling, sustainability, storage.
Re-exports all public names for backward compatibility with `from utils import ...` and `import utils`.
"""

from .schema import SHEET_HEADER

from .gemini_rate_limit import (
    gemini_rate_limit_hit,
    mark_gemini_rate_limit_hit,
    reset_gemini_rate_limit_flag,
)

from .parsing import (
    column_index_to_letter,
    extract_job_id,
    fit_score_to_enum,
    get_location_priority,
    get_user_name,
    html_to_markdown,
    normalize_company_name,
    parse_location,
)

from .apify_client import (
    APIFY_AVAILABLE,
    apify_state,
    fetch_job_details_bulk_via_apify,
    fetch_jobs_via_apify,
    get_company_overviews_bulk_via_apify,
    match_job_to_apify_result,
    rate_limit,
)

from .linkedin_crawl import (
    _check_job_expired,
    _extract_job_description,
    _setup_linkedin_driver,
    check_job_expiration,
    fetch_company_overview_via_crawling,
    fetch_company_overviews_via_crawling,
    fetch_job_description_via_crawling,
    fetch_job_descriptions_via_crawling,
    parse_job_url,
    random_scroll,
    retry_on_selenium_error,
    scrape_multiple_pages,
    scrape_search_results,
)

from .sustainability import (
    get_sustainability_from_sheet,
    is_sustainable_company,
    is_sustainable_company_bulk,
    validate_sustainability_for_unprocessed_jobs,
)

from .storage import (
    get_column_index,
    get_existing_jobs,
    get_existing_job_keys,
    parse_fit_score,
    setup_database,
    setup_driver,
    setup_spreadsheet,
    update_cell,
)

__all__ = [
    'SHEET_HEADER',
    'gemini_rate_limit_hit',
    'mark_gemini_rate_limit_hit',
    'reset_gemini_rate_limit_flag',
    'column_index_to_letter',
    'extract_job_id',
    'fit_score_to_enum',
    'get_location_priority',
    'get_user_name',
    'html_to_markdown',
    'normalize_company_name',
    'parse_location',
    'APIFY_AVAILABLE',
    'apify_state',
    'fetch_job_details_bulk_via_apify',
    'fetch_jobs_via_apify',
    'get_company_overviews_bulk_via_apify',
    'match_job_to_apify_result',
    'rate_limit',
    '_check_job_expired',
    '_extract_job_description',
    '_setup_linkedin_driver',
    'check_job_expiration',
    'fetch_company_overview_via_crawling',
    'fetch_company_overviews_via_crawling',
    'fetch_job_description_via_crawling',
    'fetch_job_descriptions_via_crawling',
    'parse_job_url',
    'random_scroll',
    'retry_on_selenium_error',
    'scrape_multiple_pages',
    'scrape_search_results',
    'get_sustainability_from_sheet',
    'is_sustainable_company',
    'is_sustainable_company_bulk',
    'validate_sustainability_for_unprocessed_jobs',
    'get_column_index',
    'get_existing_jobs',
    'get_existing_job_keys',
    'parse_fit_score',
    'setup_database',
    'setup_driver',
    'setup_spreadsheet',
    'update_cell',
]
