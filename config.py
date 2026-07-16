import os
import yaml
from pathlib import Path

# Configuration file name
CONFIG_FILE = 'job_preferences.yaml'
LEGACY_CONFIG_FILE = 'filters.yaml'  # For migration

def _deduplicate_list(items):
    """Remove duplicates from a list while preserving order."""
    seen = set()
    result = []
    for item in items:
        item_lower = str(item).lower().strip()
        if item_lower and item_lower not in seen:
            seen.add(item_lower)
            result.append(item)
    return result

def _deduplicate_filters(filters):
    """Remove duplicates from all filter lists in the filters dict."""
    # Top-level list fields to deduplicate
    top_level_fields = [
        'job_title_skip_keywords',
        'job_title_skip_keywords_2',
        'company_skip_keywords',
        'location_skip_keywords'
    ]
    
    for field in top_level_fields:
        if field in filters and isinstance(filters[field], list):
            filters[field] = _deduplicate_list(filters[field])
    
    # Deduplicate nested sustainability_criteria lists
    if 'sustainability_criteria' in filters and isinstance(filters['sustainability_criteria'], dict):
        for key in ['positive', 'negative']:
            if key in filters['sustainability_criteria'] and isinstance(filters['sustainability_criteria'][key], list):
                filters['sustainability_criteria'][key] = _deduplicate_list(filters['sustainability_criteria'][key])
    
    return filters

def _migrate_legacy_config():
    """Migrate from filters.yaml to job_preferences.yaml if needed."""
    if os.path.exists(LEGACY_CONFIG_FILE) and not os.path.exists(CONFIG_FILE):
        print(f"Migrating {LEGACY_CONFIG_FILE} to {CONFIG_FILE}...")
        import shutil
        shutil.copy(LEGACY_CONFIG_FILE, CONFIG_FILE)
        # Optionally backup the old file
        backup_path = f"{LEGACY_CONFIG_FILE}.backup"
        if not os.path.exists(backup_path):
            shutil.copy(LEGACY_CONFIG_FILE, backup_path)
        print(f"Migration complete. Old file backed up to {backup_path}")


def expand_search_matrix(matrix: dict) -> list[dict]:
    """Build Apify search_parameters as the cartesian product of keywords × locations."""
    keywords = matrix.get("keywords") or []
    locations = matrix.get("locations") or []
    if not keywords or not locations:
        return []

    defaults = {
        "remote": "remote",
        "experienceLevel": "mid_senior",
        "date_posted": "week",
        "sort": "recent",
        "limit": 100,
    }
    defaults.update(matrix.get("defaults") or {})

    month_locations = {str(x).lower() for x in (matrix.get("month_date_posted_locations") or [])}
    month_keywords = {str(x).lower() for x in (matrix.get("month_date_posted_keywords") or [])}

    params: list[dict] = []
    for keyword in keywords:
        for location in locations:
            entry = dict(defaults)
            entry["keywords"] = keyword
            entry["location"] = location
            if keyword.lower() in month_keywords or str(location).lower() in month_locations:
                entry["date_posted"] = "month"
            params.append(entry)
    return params


def _resolve_search_parameters(filters: dict) -> list[dict]:
    """Prefer search_matrix expansion; fall back to explicit search_parameters list."""
    matrix = filters.get("search_matrix")
    if isinstance(matrix, dict):
        expanded = expand_search_matrix(matrix)
        if expanded:
            return expanded
    return filters.get("search_parameters") or []


def _get_job_filters():
    """Returns the job filtering keywords and settings from YAML."""
    # Migrate legacy config if needed
    _migrate_legacy_config()
    
    filter_path = CONFIG_FILE
    
    # Default filters and settings
    default_filters = {
        'default_search_location': '',  # Default location for job search (used when generating search parameters)
        'job_title_skip_keywords': [],
        'job_title_skip_keywords_2': [],
        'company_skip_keywords': [],
        'location_skip_keywords': [],
        'location_priorities': {},
        'sustainability_criteria': {
            'positive': [],
            'negative': [],
            'use_company_overview_for_sustainability_keywords': True,
        },
        'general_settings': {
            'resume_theme': 'engineeringclassic'
        },
        'search_parameters': [],  # Cached search parameters from LLM
        'search_matrix': {},  # Optional keywords × locations → expanded into search_parameters
        'apify_search_cache': {},  # fingerprint -> last successful Apify job-search fetch (ISO UTC)
        'auto_filter_adjustment': {
            'enabled': False,
            'good_fit_threshold': 5,
        },
        'prompts': {},  # Optional LLM prompt overrides (see utils.prompts.DEFAULT_PROMPTS)
    }

    if os.path.exists(filter_path):
        try:
            with open(filter_path, 'r') as f:
                content = f.read()
            filters = yaml.safe_load(content)
            if filters and isinstance(filters, dict):
                # Merge with defaults to ensure all keys exist
                for key, value in default_filters.items():
                    if key not in filters:
                        filters[key] = value
                # Deduplicate before returning
                filters = _deduplicate_filters(filters)
                filters["search_parameters"] = _resolve_search_parameters(filters)
                if not isinstance(filters.get("prompts"), dict):
                    filters["prompts"] = {}
                return filters
        except yaml.YAMLError as e:
            print(f"Error parsing {CONFIG_FILE} (invalid YAML): {e}")
            return default_filters
        except OSError as e:
            print(f"Error reading {CONFIG_FILE}: {e}")
            return default_filters
        except Exception as e:
            print(f"Error loading {CONFIG_FILE}: {e}")
            return default_filters

    return default_filters


def _save_job_filters(filters):
    """Saves the job filtering keywords and settings to YAML."""
    # Deduplicate before saving
    filters = _deduplicate_filters(filters)
    
    filter_path = CONFIG_FILE
    with open(filter_path, 'w') as f:
        yaml.safe_dump(filters, f, sort_keys=False, default_flow_style=False)


def add_company_skip_keyword(company_name: str) -> bool:
    """Add a company to company_skip_keywords (future collection/filtering). Returns True if newly added."""
    from utils.parsing import normalize_company_name

    keyword = normalize_company_name(company_name)
    if not keyword:
        return False

    filters = _get_job_filters()
    keywords = list(filters.get("company_skip_keywords") or [])
    existing = {normalize_company_name(k) for k in keywords}
    if keyword in existing:
        return False

    keywords.append(keyword)
    filters["company_skip_keywords"] = keywords
    _save_job_filters(filters)
    print(f"Added company skip keyword: {keyword}")
    return True
