import os
import yaml

def _get_job_filters():
    """Returns the job filtering keywords and settings from YAML."""
    filter_path = 'filters.yaml'
    
    # Default filters and settings
    default_filters = {
        'job_title_skip_keywords': [],
        'job_title_skip_keywords_2': [],
        'company_skip_keywords': [],
        'location_skip_keywords': [],
        'location_priorities': {},
        'sustainability_criteria': {
            'positive': [],
            'negative': []
        },
        'general_settings': {
            'resume_theme': 'engineeringclassic'
        }
    }

    if os.path.exists(filter_path):
        with open(filter_path, 'r') as f:
            try:
                filters = yaml.safe_load(f)
                if filters:
                    # Merge with defaults to ensure all keys exist
                    for key, value in default_filters.items():
                        if key not in filters:
                            filters[key] = value
                    return filters
            except Exception as e:
                print(f"Error loading filters.yaml: {e}")
    
    return default_filters


def _save_job_filters(filters):
    """Saves the job filtering keywords and settings to YAML."""
    filter_path = 'filters.yaml'
    with open(filter_path, 'w') as f:
        yaml.safe_dump(filters, f, sort_keys=False)
