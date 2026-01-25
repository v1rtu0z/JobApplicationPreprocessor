import streamlit as st
import pandas as pd
from pathlib import Path
import subprocess
import sys
import os
import time
from datetime import datetime
from local_storage import JobDatabase
from utils import SHEET_HEADER, get_user_name
from api_methods import get_resume_json
from config import _get_job_filters

# Page config
st.set_page_config(
    page_title="Job Application Dashboard",
    page_icon="💼",
    layout="wide"
)

# Custom CSS for fixed undo popup
st.markdown("""
<style>
    /* 1. Target the specific vertical block for the undo popup */
    div[data-testid="stVerticalBlock"] div[data-testid="stVerticalBlock"]:has(.undo-marker-unique) {
        position: fixed !important;
        bottom: 30px !important;
        right: 30px !important;
        z-index: 10000 !important;
        width: 320px !important;
        background-color: #1a1c24 !important;
        padding: 20px !important;
        border-radius: 12px !important;
        border: 1px solid #3d444d !important;
        box-shadow: 0 8px 24px rgba(0,0,0,0.6) !important;
        display: flex !important;
        flex-direction: column !important;
        gap: 10px !important;
    }
    
    /* 2. Ensure the main application container is NEVER caught by this */
    div[data-testid="stMain"] > div[data-testid="stVerticalBlock"] {
        position: relative !important;
        bottom: auto !important;
        right: auto !important;
        width: 100% !important;
        z-index: 1 !important;
        box-shadow: none !important;
        background-color: transparent !important;
    }

    .undo-text {
        color: #e6edf3 !important;
        font-weight: 600 !important;
        font-size: 1.0rem !important;
        margin-bottom: 4px !important;
    }
    
    .undo-subtext {
        color: #8b949e !important;
        font-size: 0.85rem !important;
        line-height: 1.4 !important;
        margin-bottom: 8px !important;
    }

    /* Target the button within the fixed popup specifically */
    div[data-testid="stVerticalBlock"]:has(.undo-marker-unique) button {
        width: 100% !important;
        background-color: #21262d !important;
        border: 1px solid #3d444d !important;
        color: #c9d1d9 !important;
    }
    
    /* Highlight missing data alerts */
    .stAlert[data-baseweb="notification"] {
        border-left: 4px solid !important;
    }
    
    /* Critical alert for sustainable jobs missing descriptions */
    div[data-testid="stAlert"]:has-text("CRITICAL") {
        border-left-color: #ff4444 !important;
        background-color: #2d1f1f !important;
    }
</style>
""", unsafe_allow_html=True)

# Auto-refresh configuration
if 'last_refresh' not in st.session_state:
    st.session_state.last_refresh = time.time()

AUTO_REFRESH_INTERVAL = 60  # seconds (increased from 30)

@st.cache_data(ttl=3600)  # Cache for 1 hour - user_name rarely changes
def get_cached_user_name():
    """Get user name from resume JSON, cached separately."""
    try:
        resume_json = get_resume_json()
        return get_user_name(resume_json)
    except Exception:
        return None

def open_file_manager(file_path: Path):
    """
    Open file manager at the location of the file (OS-agnostic).
    """
    file_path = Path(file_path).resolve()
    
    if sys.platform == "win32":
        # Windows
        subprocess.run(["explorer", "/select,", str(file_path)])
    elif sys.platform == "darwin":
        # macOS
        subprocess.run(["open", "-R", str(file_path)])
    else:
        # Linux and other Unix-like systems
        # Try different file managers
        file_dir = file_path.parent
        managers = [
            ["xdg-open", str(file_dir)],
            ["nautilus", str(file_dir)],
            ["dolphin", str(file_dir)],
            ["thunar", str(file_dir)],
            ["pcmanfm", str(file_dir)],
        ]
        
        for manager in managers:
            try:
                subprocess.run(manager, check=True)
                break
            except (subprocess.CalledProcessError, FileNotFoundError):
                continue
        else:
            st.error(f"Could not open file manager. File location: {file_dir}")

def get_resume_path(resume_url: str) -> Path:
    """
    Convert resume URL/path to absolute Path object.
    Handles relative paths from local_data/resumes/.
    """
    if not resume_url or not resume_url.strip():
        return None
    
    resume_url = resume_url.strip()
    path = Path(resume_url)
    
    # If relative path, make it relative to current working directory
    if not path.is_absolute():
        # Handle paths like "local_data/resumes/file.pdf"
        if resume_url.startswith('local_data/'):
            path = Path('.') / path
        else:
            # Assume it's relative to current directory
            path = Path('.') / path
    
    try:
        resolved = path.resolve()
        return resolved if resolved.exists() else None
    except (OSError, ValueError):
        return None

@st.cache_data(ttl=300)  # Cache for 5 minutes to avoid excessive DB reads
def load_job_data():
    """Load job data from SQLite database."""
    try:
        db_path = Path("local_data") / "jobs.db"
        if not db_path.exists():
            return None, "No job data found. Please run the main application first."
        
        db = JobDatabase(str(db_path), SHEET_HEADER)
        records = db.get_all_records()
        
        if not records:
            return None, "No jobs found in the database."
        
        # Convert to DataFrame
        df = pd.DataFrame(records)
        return df, None
    except Exception as e:
        return None, f"Error loading data: {str(e)}"

def update_job_field(job_url_key: str, company_key: str, field_name: str, value: str):
    """Update a single field for a job in the database."""
    db_path = Path("local_data") / "jobs.db"
    if not db_path.exists():
        return 0
    
    db = JobDatabase(str(db_path), SHEET_HEADER)
    return db.update_job_by_key(job_url_key, company_key, {field_name: value})

def handle_field_update(job_url_key: str, company_key: str, field_name: str, new_value: str, current_value: str, success_msg: str):
    """Helper to handle field updates with robust refresh logic."""
    if new_value != current_value:
        rows_affected = update_job_field(job_url_key, company_key, field_name, new_value)
        if rows_affected > 0:
            st.success(success_msg)
            # Only clear cache if data actually changed, and update session state DF directly
            if 'df' in st.session_state:
                df = st.session_state.df
                mask = (df.get('Job URL', '') == job_url_key) & (df.get('Company Name', '') == company_key)
                df.loc[mask, field_name] = new_value
                st.session_state.df = df
                # Invalidate filter cache since data changed
                if 'filter_options_cache' in st.session_state:
                    del st.session_state.filter_options_cache
                if 'df_hash' in st.session_state:
                    del st.session_state.df_hash
            # Only clear cache, don't force full reload
            st.cache_data.clear()
            st.rerun()
        else:
            st.error(f"Failed to update {field_name}. Record not found in database.")
            st.info(f"Debug: Company='{company_key}', URL='{job_url_key[:50]}...'")
    else:
        st.info("No changes detected.")

def main():
    st.title("💼 Job Application Dashboard")
    
    # Initialize session state for data and UI
    if 'df' not in st.session_state:
        df, error = load_job_data()
        if error:
            st.error(error)
            return
        st.session_state.df = df
    
    if 'hidden_jobs' not in st.session_state:
        st.session_state.hidden_jobs = set()
    if 'undo_stack' not in st.session_state:
        st.session_state.undo_stack = []  # Format: (job_key, field_name, old_value, job_url_key, company_key, company, job_title)
    if 'last_refresh' not in st.session_state:
        st.session_state.last_refresh = time.time()

    def on_checkbox_change(job_key, field_name, job_url_key, company_key, company, job_title, current_val, filter_selection):
        # The new value is in session state
        key = f"{field_name.lower().replace(' ', '_')}_{job_key}"
        if key not in st.session_state:
            return
        new_val = st.session_state[key]
        
        # 1. Update DB
        update_job_field(job_url_key, company_key, field_name, 'TRUE' if new_val else 'FALSE')
        
        # 2. Update session state DF
        df = st.session_state.df
        mask = (df.get('Job URL', '') == job_url_key) & (df.get('Company Name', '') == company_key)
        df.loc[mask, field_name] = 'TRUE' if new_val else 'FALSE'
        st.session_state.df = df
        
        # 3. Determine if it should be hidden
        should_hide = False
        if field_name == 'Applied':
            if not new_val and filter_selection and 'Not Applied' not in filter_selection and 'Unknown' not in filter_selection:
                should_hide = True
            elif new_val and filter_selection and 'Applied' not in filter_selection:
                should_hide = True
        elif field_name == 'Job posting expired':
            if new_val and filter_selection and 'Expired' not in filter_selection:
                should_hide = True
            elif not new_val and filter_selection and 'Active' not in filter_selection and 'Unknown' not in filter_selection:
                should_hide = True
        elif field_name == 'Bad analysis':
            if new_val and filter_selection and 'Yes' not in filter_selection:
                should_hide = True
            elif not new_val and filter_selection and 'No' not in filter_selection and 'Unknown' not in filter_selection:
                should_hide = True
        
        if should_hide:
            st.session_state.hidden_jobs.add(job_key)
            st.session_state.undo_stack.append((job_key, field_name, current_val, job_url_key, company_key, company, job_title))
        
        # Don't clear cache on checkbox change - session state DF is already updated

    def handle_undo():
        if st.session_state.undo_stack:
            job_key, field_name, old_value, job_url_key, company_key, company, job_title = st.session_state.undo_stack.pop()
            
            # Update DB
            update_job_field(job_url_key, company_key, field_name, old_value)
            
            # Update session state DF
            df = st.session_state.df
            mask = (df.get('Job URL', '') == job_url_key) & (df.get('Company Name', '') == company_key)
            df.loc[mask, field_name] = old_value
            st.session_state.df = df
            
            # Unhide
            st.session_state.hidden_jobs.discard(job_key)
            # Don't clear cache - session state DF is already updated
            # No rerun needed here, Streamlit will rerun anyway after callback

    # Auto-refresh button and status
    col_header1, col_header2, col_header3 = st.columns([3, 1, 1])
    with col_header1:
        st.markdown("View and manage your job applications")
    with col_header2:
        if st.button("🔄 Refresh", use_container_width=True):
            st.cache_data.clear()
            st.session_state.df, error = load_job_data()
            if error:
                st.error(error)
            st.rerun()
    with col_header3:
        auto_refresh = st.checkbox("Auto-refresh", value=True)
    
    # Auto-refresh logic
    if auto_refresh:
        current_time = time.time()
        if current_time - st.session_state.last_refresh > AUTO_REFRESH_INTERVAL:
            st.session_state.last_refresh = current_time
            st.cache_data.clear()
            st.session_state.df, error = load_job_data()
            if error:
                st.error(f"Auto-refresh error: {error}")
            else:
                st.rerun()
    
    # Use data from session state
    df = st.session_state.df
    
    if df is None or df.empty:
        st.info("No jobs found.")
        return
    
    # Initialize PDF cache with LRU eviction
    MAX_PDF_CACHE_SIZE = 10
    if 'pdf_cache_keys' not in st.session_state:
        st.session_state.pdf_cache_keys = []
    
    # Check if location priorities are defined
    filters = _get_job_filters()
    has_location_priorities = bool(filters.get('location_priorities', {}))
    
    # Sidebar filters
    st.sidebar.header("🔍 Filters")
    st.sidebar.caption("💡 Tip: Leave multiselect filters empty to show all")
    
    # Helper function to normalize multiselect - empty selection means "All"
    def normalize_multiselect(selection):
        """Empty selection means show all. Return selection as-is (no 'All' option in multiselect)."""
        return selection if selection else []
    
    # Cache filter options in session state for performance
    if 'filter_options_cache' not in st.session_state or 'df_hash' not in st.session_state:
        # Generate cache key from DataFrame shape and content hash
        # Use a more robust hash that samples multiple rows to detect changes
        # Hash includes: length, columns, and a sample of Job URLs (first, middle, last, and a few random ones)
        if len(df) > 0:
            sample_indices = [0]
            if len(df) > 1:
                sample_indices.append(len(df) - 1)
            if len(df) > 2:
                sample_indices.append(len(df) // 2)
            # Add a few more samples for larger datasets
            if len(df) > 10:
                step = len(df) // 5
                sample_indices.extend([step * i for i in range(1, 5) if step * i < len(df)])
            
            sample_urls = tuple(df['Job URL'].iloc[i] if i < len(df) else '' for i in sorted(set(sample_indices)))
            df_hash = hash((len(df), tuple(df.columns), sample_urls))
        else:
            df_hash = hash((0, tuple(df.columns), ()))
        st.session_state.df_hash = df_hash
        
        # Cache fit score options
        fit_score_options = sorted([s for s in df['Fit score'].dropna().unique().tolist() if s], reverse=True)
        bad_fits = ['Poor fit', 'Very poor fit', 'Questionable fit']
        default_fit_scores = [s for s in fit_score_options if s not in bad_fits]
        if 'Unknown' not in default_fit_scores:
            default_fit_scores.append('Unknown')
        
        # Cache location and company options
        locations = sorted([l for l in df['Location'].dropna().unique().tolist() if l])
        companies = sorted([c for c in df['Company Name'].dropna().unique().tolist() if c])
        
        st.session_state.filter_options_cache = {
            'fit_score_options': fit_score_options,
            'default_fit_scores': default_fit_scores,
            'locations': locations,
            'companies': companies
        }
    else:
        # Check if DataFrame has changed (efficient hash comparison)
        # Use same hash calculation as above
        if len(df) > 0:
            sample_indices = [0]
            if len(df) > 1:
                sample_indices.append(len(df) - 1)
            if len(df) > 2:
                sample_indices.append(len(df) // 2)
            if len(df) > 10:
                step = len(df) // 5
                sample_indices.extend([step * i for i in range(1, 5) if step * i < len(df)])
            
            sample_urls = tuple(df['Job URL'].iloc[i] if i < len(df) else '' for i in sorted(set(sample_indices)))
            current_df_hash = hash((len(df), tuple(df.columns), sample_urls))
        else:
            current_df_hash = hash((0, tuple(df.columns), ()))
        
        if current_df_hash != st.session_state.df_hash:
            # Invalidate cache
            del st.session_state.filter_options_cache
            del st.session_state.df_hash
            st.rerun()
    
    # Use cached filter options
    cache = st.session_state.filter_options_cache
    fit_score_options = cache['fit_score_options']
    default_fit_scores = cache['default_fit_scores']
    locations = cache['locations']
    companies = cache['companies']
    
    fit_score_options_with_meta = ['Unknown'] + fit_score_options
    selected_fit_scores_raw = st.sidebar.multiselect("Fit Score", fit_score_options_with_meta, default=default_fit_scores)
    selected_fit_scores = normalize_multiselect(selected_fit_scores_raw)
    
    # Applied filter
    applied_options = ['Applied', 'Not Applied', 'Unknown']
    selected_applied_raw = st.sidebar.multiselect("Applied Status", applied_options, default=['Not Applied', 'Unknown'])
    selected_applied = normalize_multiselect(selected_applied_raw)
    
    # Has Resume filter
    has_resume_options = ['Yes', 'No', 'Unknown']
    selected_resume_raw = st.sidebar.multiselect("Has Resume", has_resume_options, default=[])
    selected_resume = normalize_multiselect(selected_resume_raw)
    
    # Has Cover Letter filter
    has_cl_options = ['Yes', 'No', 'Unknown']
    selected_cl_raw = st.sidebar.multiselect("Has Cover Letter", has_cl_options, default=[])
    selected_cl = normalize_multiselect(selected_cl_raw)
    
    # Expired filter
    expired_options = ['Active', 'Expired', 'Unknown']
    selected_expired_raw = st.sidebar.multiselect("Expired Status", expired_options, default=['Active', 'Unknown'])
    selected_expired = normalize_multiselect(selected_expired_raw)
    
    # Bad analysis filter
    if 'Bad analysis' in df.columns:
        bad_analysis_options = ['Yes', 'No', 'Unknown']
        selected_bad_analysis_raw = st.sidebar.multiselect("Bad Analysis", bad_analysis_options, default=['No', 'Unknown'])
        selected_bad_analysis = normalize_multiselect(selected_bad_analysis_raw)
    else:
        selected_bad_analysis = []
    
    # Sustainable company filter
    if 'Sustainable company' in df.columns:
        sustainable_options = ['Yes', 'No', 'Unknown']
        selected_sustainable_raw = st.sidebar.multiselect("Sustainable Company", sustainable_options, default=['Yes', 'Unknown'])
        selected_sustainable = normalize_multiselect(selected_sustainable_raw)
    else:
        selected_sustainable = []
    
    # Company overview filter
    if 'Company overview' in df.columns:
        company_overview_options = ['Yes', 'No', 'Unknown']
        selected_company_overview_raw = st.sidebar.multiselect("Has Company Overview", company_overview_options, default=[])
        selected_company_overview = normalize_multiselect(selected_company_overview_raw)
    else:
        selected_company_overview = []
    
    # Missing data filter (high priority)
    st.sidebar.divider()
    st.sidebar.header("⚠️ Missing Data")
    missing_data_options = ['Missing Job Description', 'Missing Company Overview', 'Missing Both', 'All Complete']
    selected_missing_data_raw = st.sidebar.multiselect("Filter by Missing Data", missing_data_options, default=[])
    selected_missing_data = normalize_multiselect(selected_missing_data_raw)
    
    # Priority filter for sustainable jobs missing descriptions
    show_priority_only = st.sidebar.checkbox("🔴 Show only sustainable jobs missing descriptions", value=False)
    
    st.sidebar.divider()
    st.sidebar.caption("📍 Location & Company Filters")
    
    # Location filter (using cached options)
    selected_locations_raw = st.sidebar.multiselect("Location", ['Unknown'] + locations, default=[])
    selected_locations = normalize_multiselect(selected_locations_raw)
    
    # Company filter (using cached options)
    selected_company_raw = st.sidebar.multiselect("Company", ['Unknown'] + companies, default=[])
    selected_company = normalize_multiselect(selected_company_raw)
    
    # Filter data - use vectorized operations with boolean mask for better performance
    # Build combined mask instead of multiple DataFrame copies
    filter_mask = pd.Series([True] * len(df), index=df.index)
    
    # Fit score filtering
    if selected_fit_scores:
        if 'Unknown' in selected_fit_scores:
            fit_mask = df['Fit score'].isna() | (df['Fit score'] == '') | df['Fit score'].isin([s for s in selected_fit_scores if s != 'Unknown'])
        else:
            fit_mask = df['Fit score'].isin(selected_fit_scores)
        filter_mask = filter_mask & fit_mask
    
    # Applied filtering - multiselect
    if 'Applied' in df.columns and selected_applied:
        applied_mask = pd.Series([False] * len(df), index=df.index)
        if 'Applied' in selected_applied:
            applied_mask = applied_mask | (df['Applied'] == 'TRUE')
        if 'Not Applied' in selected_applied:
            applied_mask = applied_mask | (df['Applied'] != 'TRUE')
        if 'Unknown' in selected_applied:
            applied_mask = applied_mask | (df['Applied'].isna() | (df['Applied'] == ''))
        filter_mask = filter_mask & applied_mask
    
    # Bad analysis filtering - multiselect (only if column exists)
    if 'Bad analysis' in df.columns and selected_bad_analysis:
        bad_analysis_mask = pd.Series([False] * len(df), index=df.index)
        if 'Yes' in selected_bad_analysis:
            bad_analysis_mask = bad_analysis_mask | (df['Bad analysis'] == 'TRUE')
        if 'No' in selected_bad_analysis:
            bad_analysis_mask = bad_analysis_mask | (df['Bad analysis'] != 'TRUE')
        if 'Unknown' in selected_bad_analysis:
            bad_analysis_mask = bad_analysis_mask | (df['Bad analysis'].isna() | (df['Bad analysis'] == ''))
        filter_mask = filter_mask & bad_analysis_mask
    
    # Expired filtering - multiselect
    if 'Job posting expired' in df.columns and selected_expired:
        expired_mask = pd.Series([False] * len(df), index=df.index)
        if 'Expired' in selected_expired:
            expired_mask = expired_mask | (df['Job posting expired'] == 'TRUE')
        if 'Active' in selected_expired:
            expired_mask = expired_mask | (df['Job posting expired'] != 'TRUE')
        if 'Unknown' in selected_expired:
            expired_mask = expired_mask | (df['Job posting expired'].isna() | (df['Job posting expired'] == ''))
        filter_mask = filter_mask & expired_mask
    
    # Sustainable filtering - multiselect (only if column exists)
    if 'Sustainable company' in df.columns and selected_sustainable:
        sustainable_mask = pd.Series([False] * len(df), index=df.index)
        if 'Yes' in selected_sustainable:
            sustainable_mask = sustainable_mask | (df['Sustainable company'] == 'TRUE')
        if 'No' in selected_sustainable:
            sustainable_mask = sustainable_mask | (df['Sustainable company'] == 'FALSE')
        if 'Unknown' in selected_sustainable:
            sustainable_mask = sustainable_mask | (df['Sustainable company'].isna() | (df['Sustainable company'] == ''))
        filter_mask = filter_mask & sustainable_mask
    
    # Resume filtering - multiselect
    if selected_resume:
        resume_mask = pd.Series([False] * len(df), index=df.index)
        if 'Yes' in selected_resume:
            resume_mask = resume_mask | (df['Tailored resume url'].notna() & (df['Tailored resume url'] != ''))
        if 'No' in selected_resume or 'Unknown' in selected_resume:
            resume_mask = resume_mask | (df['Tailored resume url'].isna() | (df['Tailored resume url'] == ''))
        filter_mask = filter_mask & resume_mask
    
    # Cover letter filtering - multiselect
    if selected_cl:
        cl_mask = pd.Series([False] * len(df), index=df.index)
        if 'Yes' in selected_cl:
            cl_mask = cl_mask | (df['Tailored cover letter (to be humanized)'].notna() & (df['Tailored cover letter (to be humanized)'] != ''))
        if 'No' in selected_cl or 'Unknown' in selected_cl:
            cl_mask = cl_mask | (df['Tailored cover letter (to be humanized)'].isna() | (df['Tailored cover letter (to be humanized)'] == ''))
        filter_mask = filter_mask & cl_mask
    
    # Location filtering
    if selected_locations:
        if 'Unknown' in selected_locations:
            location_mask = df['Location'].isna() | (df['Location'] == '') | df['Location'].isin([l for l in selected_locations if l != 'Unknown'])
        else:
            location_mask = df['Location'].isin(selected_locations)
        filter_mask = filter_mask & location_mask
    
    # Company filtering
    if selected_company:
        if 'Unknown' in selected_company:
            company_mask = df['Company Name'].isna() | (df['Company Name'] == '') | df['Company Name'].isin([c for c in selected_company if c != 'Unknown'])
        else:
            company_mask = df['Company Name'].isin(selected_company)
        filter_mask = filter_mask & company_mask
    
    # Company overview filtering
    if 'Company overview' in df.columns and selected_company_overview:
        co_mask = pd.Series([False] * len(df), index=df.index)
        if 'Yes' in selected_company_overview:
            co_mask = co_mask | (df['Company overview'].notna() & (df['Company overview'] != ''))
        if 'No' in selected_company_overview or 'Unknown' in selected_company_overview:
            co_mask = co_mask | (df['Company overview'].isna() | (df['Company overview'] == ''))
        filter_mask = filter_mask & co_mask
    
    # Missing data filtering
    if selected_missing_data:
        has_jd = df['Job Description'].notna() & (df['Job Description'] != '')
        has_co = df['Company overview'].notna() & (df['Company overview'] != '') if 'Company overview' in df.columns else pd.Series([False] * len(df), index=df.index)
        
        missing_mask = pd.Series([False] * len(df), index=df.index)
        if 'Missing Job Description' in selected_missing_data:
            missing_mask = missing_mask | ~has_jd
        if 'Missing Company Overview' in selected_missing_data:
            missing_mask = missing_mask | ~has_co
        if 'Missing Both' in selected_missing_data:
            missing_mask = missing_mask | (~has_jd & ~has_co)
        if 'All Complete' in selected_missing_data:
            missing_mask = missing_mask | (has_jd & has_co)
        filter_mask = filter_mask & missing_mask
    
    # Priority filter: sustainable jobs missing descriptions
    if show_priority_only:
        has_jd = df['Job Description'].notna() & (df['Job Description'] != '')
        is_sustainable = df['Sustainable company'] == 'TRUE' if 'Sustainable company' in df.columns else pd.Series([False] * len(df), index=df.index)
        filter_mask = filter_mask & is_sustainable & ~has_jd
    
    # Apply all filters at once
    filtered_df = df[filter_mask].copy()
    
    
    # Metrics
    st.sidebar.divider()
    st.sidebar.header("📊 Statistics")
    st.sidebar.metric("Total Jobs", len(filtered_df))
    # Defensive check for 'Tailored resume url' column
    if 'Tailored resume url' in filtered_df.columns:
        with_resumes = len(filtered_df[filtered_df['Tailored resume url'].notna() & (filtered_df['Tailored resume url'] != '')])
        st.sidebar.metric("With Resumes", with_resumes)
    else:
        st.sidebar.metric("With Resumes", 0)
    # Defensive check for 'Applied' column
    if 'Applied' in filtered_df.columns:
        applied_count = len(filtered_df[filtered_df['Applied'] == 'TRUE'])
        st.sidebar.metric("Applied", applied_count)
    else:
        st.sidebar.metric("Applied", 0)
    
    # Sustainability stats
    if 'Sustainable company' in df.columns:
        st.sidebar.divider()
        st.sidebar.header("🌱 Sustainability")
        sustainable_yes = len(filtered_df[filtered_df['Sustainable company'] == 'TRUE'])
        sustainable_no = len(filtered_df[filtered_df['Sustainable company'] == 'FALSE'])
        sustainable_unknown = len(filtered_df[filtered_df['Sustainable company'].isna() | (filtered_df['Sustainable company'] == '')])
        st.sidebar.metric("✅ Sustainable", sustainable_yes)
        st.sidebar.metric("❌ Not Sustainable", sustainable_no)
        st.sidebar.metric("❓ Unknown", sustainable_unknown)
    
    # Fit score breakdown
    if len(filtered_df) > 0:
        st.sidebar.divider()
        st.sidebar.header("⭐ Fit Score Breakdown")
        fit_breakdown = filtered_df['Fit score'].value_counts()
        for score, count in fit_breakdown.items():
            if score:
                st.sidebar.text(f"{score}: {count}")
        # Show unknown count
        unknown_fit = len(filtered_df[filtered_df['Fit score'].isna() | (filtered_df['Fit score'] == '')])
        if unknown_fit > 0:
            st.sidebar.text(f"Unknown: {unknown_fit}")
    
    # Count visible jobs (excluding hidden ones) - using itertuples for performance
    # Create column index map for efficient access
    column_index_map = {col: idx for idx, col in enumerate(filtered_df.columns)}
    
    # Helper function to get column value from itertuples row (using column index)
    def get_row_value(row, col_name, default=''):
        """Get value from itertuples row using column index.
        
        itertuples(index=False) returns tuples where columns are in order.
        We access by position using the column_index_map.
        """
        if col_name not in column_index_map:
            return default
        col_idx = column_index_map[col_name]
        # itertuples with index=False: columns start at index 0
        try:
            value = row[col_idx]
            return str(value) if value is not None else default
        except (IndexError, AttributeError, TypeError):
            return default
    
    visible_count = 0
    for row_idx, row in enumerate(filtered_df.itertuples(index=False)):
        job_url_key = get_row_value(row, 'Job URL', '')
        company_key = get_row_value(row, 'Company Name', '')
        job_key = f"{job_url_key}|{company_key}|{row_idx}"
        if job_key not in st.session_state.hidden_jobs:
            visible_count += 1
    st.header(f"Job Listings ({visible_count} jobs)")
    
    # Multi-column sorting
    st.subheader("Sorting")
    col_sort1, col_sort2, col_sort3 = st.columns(3)
    with col_sort1:
        sort_by_1 = st.selectbox("Primary Sort", ['Location Priority', 'Fit Score', 'Company', 'Location'], key='sort_by_1', index=0)
        sort_order_1 = st.selectbox("Order", ['Descending', 'Ascending'], key='sort_order_1', index=0)
    with col_sort2:
        sort_by_2 = st.selectbox("Secondary Sort", ['Fit Score', 'Location Priority', 'Company', 'Location'], key='sort_by_2', index=0)
        sort_order_2 = st.selectbox("Order", ['Descending', 'Ascending'], key='sort_order_2', index=0)
    with col_sort3:
        sort_by_3 = st.selectbox("Tertiary Sort", ['None', 'Company', 'Location', 'Fit Score', 'Location Priority'], key='sort_by_3', index=0)
        sort_order_3 = st.selectbox("Order", ['Descending', 'Ascending'], key='sort_order_3', index=0)
    
    # Apply multi-column sorting
    sort_columns = []
    sort_ascending = []
    
    # Primary sort
    if sort_by_1 == 'Location Priority':
        if 'Location Priority' in filtered_df.columns:
            sort_columns.append('Location Priority')
            sort_ascending.append(sort_order_1 == 'Ascending')
    elif sort_by_1 == 'Fit Score':
        if 'Fit score enum' in filtered_df.columns:
            sort_columns.append('Fit score enum')
            sort_ascending.append(sort_order_1 == 'Ascending')
        elif 'Fit score' in filtered_df.columns:
            sort_columns.append('Fit score')
            sort_ascending.append(sort_order_1 == 'Ascending')
    elif sort_by_1 == 'Company':
        sort_columns.append('Company Name')
        sort_ascending.append(sort_order_1 == 'Ascending')
    elif sort_by_1 == 'Location':
        sort_columns.append('Location')
        sort_ascending.append(sort_order_1 == 'Ascending')
    
    # Secondary sort
    if sort_by_2 != sort_by_1 and sort_by_2 != 'None':
        if sort_by_2 == 'Location Priority':
            if 'Location Priority' in filtered_df.columns:
                sort_columns.append('Location Priority')
                sort_ascending.append(sort_order_2 == 'Ascending')
        elif sort_by_2 == 'Fit Score':
            if 'Fit score enum' in filtered_df.columns:
                sort_columns.append('Fit score enum')
                sort_ascending.append(sort_order_2 == 'Ascending')
            elif 'Fit score' in filtered_df.columns:
                sort_columns.append('Fit score')
                sort_ascending.append(sort_order_2 == 'Ascending')
        elif sort_by_2 == 'Company':
            sort_columns.append('Company Name')
            sort_ascending.append(sort_order_2 == 'Ascending')
        elif sort_by_2 == 'Location':
            sort_columns.append('Location')
            sort_ascending.append(sort_order_2 == 'Ascending')
    
    # Tertiary sort
    if sort_by_3 != 'None' and sort_by_3 != sort_by_1 and sort_by_3 != sort_by_2:
        if sort_by_3 == 'Location Priority':
            if 'Location Priority' in filtered_df.columns:
                sort_columns.append('Location Priority')
                sort_ascending.append(sort_order_3 == 'Ascending')
        elif sort_by_3 == 'Fit Score':
            if 'Fit score enum' in filtered_df.columns:
                sort_columns.append('Fit score enum')
                sort_ascending.append(sort_order_3 == 'Ascending')
            elif 'Fit score' in filtered_df.columns:
                sort_columns.append('Fit score')
                sort_ascending.append(sort_order_3 == 'Ascending')
        elif sort_by_3 == 'Company':
            sort_columns.append('Company Name')
            sort_ascending.append(sort_order_3 == 'Ascending')
        elif sort_by_3 == 'Location':
            sort_columns.append('Location')
            sort_ascending.append(sort_order_3 == 'Ascending')
    
    # Apply sorting if we have columns to sort by
    if sort_columns:
        filtered_df = filtered_df.sort_values(sort_columns, ascending=sort_ascending)
    
    # Build job URL key map first (needed for undo) - using itertuples for performance
    job_url_key_map = {}  # Map to track job identifiers
    for row_idx, row in enumerate(filtered_df.itertuples(index=False)):
        job_url_key = get_row_value(row, 'Job URL', '')
        company_key = get_row_value(row, 'Company Name', '')
        # Use row index to ensure uniqueness even if URL/company are empty
        job_key = f"{job_url_key}|{company_key}|{row_idx}"
        job_url_key_map[job_key] = (job_url_key, company_key)
    
    # Undo notification will be shown at the end of the page
    
    # Build list of visible jobs (excluding hidden ones)
    visible_jobs_list = []
    for row_idx, row in enumerate(filtered_df.itertuples(index=False)):
        job_url_key = get_row_value(row, 'Job URL', '')
        company_key = get_row_value(row, 'Company Name', '')
        job_key = f"{job_url_key}|{company_key}|{row_idx}"
        if job_key not in st.session_state.hidden_jobs:
            visible_jobs_list.append((row_idx, row))
    
    # Display jobs in expandable sections - using itertuples for performance
    for display_idx, (original_row_idx, row) in enumerate(visible_jobs_list):
        # Get unique identifier for this job
        job_url_key = get_row_value(row, 'Job URL', '')
        company_key = get_row_value(row, 'Company Name', '')
        # Use original row index to ensure uniqueness even if URL/company are empty
        job_key = f"{job_url_key}|{company_key}|{original_row_idx}"
        
        fit_score = get_row_value(row, 'Fit score', '') or 'Unknown'
        company = get_row_value(row, 'Company Name', 'N/A')
        job_title = get_row_value(row, 'Job Title', 'N/A')
        location = get_row_value(row, 'Location', 'N/A')
        location_priority = get_row_value(row, 'Location Priority', '')
        resume_url = get_row_value(row, 'Tailored resume url', '')
        job_url = get_row_value(row, 'Job URL', '')
        company_overview = get_row_value(row, 'Company overview', '')
        sustainable = get_row_value(row, 'Sustainable company', '')
        job_analysis = get_row_value(row, 'Job analysis', '')
        has_bad_analysis = get_row_value(row, 'Bad analysis', '') == 'TRUE'
        
        # Color code by fit score
        if fit_score == 'Very good fit':
            color = "🟢"
        elif fit_score == 'Good fit':
            color = "🟡"
        elif fit_score in ['Poor fit', 'Very poor fit']:
            color = "🔴"
        else:
            color = "⚪"
        
        # Check for missing critical data
        job_description = get_row_value(row, 'Job Description', '')
        has_job_description = bool(job_description.strip() if job_description else False)
        has_company_overview = bool(company_overview.strip() if company_overview else False)
        missing_jd = not has_job_description
        
        # Only show missing CO if fetching was attempted and failed
        co_attempted = get_row_value(row, 'CO fetch attempted', '') == 'TRUE'
        missing_co = not has_company_overview and co_attempted
        
        # Build expander title with more info
        title_parts = [f"{color} {company} - {job_title}"]
        if location:
            title_parts.append(f"📍 {location}")
        if fit_score and fit_score != 'Unknown':
            title_parts.append(f"⭐ {fit_score}")
        # Add sustainability indicator
        if sustainable == 'TRUE':
            title_parts.append("🌱 Sustainable")
        elif sustainable == 'FALSE':
            title_parts.append("⚠️ Not Sustainable")
        applied = get_row_value(row, 'Applied', '')
        if applied == 'TRUE':
            title_parts.append("✅ Applied")
        expired = get_row_value(row, 'Job posting expired', '')
        if expired == 'TRUE':
            title_parts.append("❌ Expired")
        # Add missing data indicators (high priority)
        if missing_jd:
            if sustainable == 'TRUE':
                title_parts.insert(0, "🔴⚠️")  # Highest priority - sustainable but missing JD
            else:
                title_parts.append("⚠️ Missing JD")
        if missing_co:
            title_parts.append("⚠️ Missing CO")
        
        with st.expander(" | ".join(title_parts), expanded=False):
            # Basic info
            st.write(f"**Company:** {company}")
            st.write(f"**Job Title:** {job_title}")
            st.write(f"**Location:** {location}")
            if has_location_priorities and location_priority:
                st.write(f"**Location Priority:** {location_priority}")
            if fit_score != 'Unknown':
                st.write(f"**Fit Score:** {fit_score}")
            
            if sustainable:
                sustainable_icon = "✅" if sustainable == 'TRUE' else "❌"
                st.write(f"**Sustainable Company:** {sustainable_icon} {sustainable}")
            
            # Applied checkbox - only show if resume or CL exists
            cover_letter = get_row_value(row, 'Tailored cover letter (to be humanized)', '')
            has_resume_or_cl = bool(resume_url) or bool(cover_letter)
            if has_resume_or_cl:
                current_applied = applied == 'TRUE'
                st.checkbox("✅ Applied", value=current_applied, key=f"applied_{job_key}",
                           on_change=on_checkbox_change,
                           args=(job_key, 'Applied', job_url_key, company_key, company, job_title, 'TRUE' if current_applied else 'FALSE', selected_applied))
            
            # Job URL with inline expired checkbox
            if job_url:
                url_col1, url_col2 = st.columns([3, 1])
                with url_col1:
                    st.write(f"**Job URL:** [{job_url}]({job_url})")
                with url_col2:
                    current_expired = expired == 'TRUE'
                    st.checkbox("Expired", value=current_expired, key=f"job_posting_expired_{job_key}",
                               on_change=on_checkbox_change,
                               args=(job_key, 'Job posting expired', job_url_key, company_key, company, job_title, 'TRUE' if current_expired else 'FALSE', selected_expired))
            
            # Job Analysis with inline bad analysis checkbox
            if job_analysis:
                analysis_col1, analysis_col2 = st.columns([3, 1])
                with analysis_col1:
                    with st.expander("Job Analysis"):
                        st.markdown(job_analysis)
                with analysis_col2:
                    st.checkbox("Bad Analysis", value=has_bad_analysis, key=f"bad_analysis_{job_key}",
                               on_change=on_checkbox_change,
                               args=(job_key, 'Bad analysis', job_url_key, company_key, company, job_title, 'TRUE' if has_bad_analysis else 'FALSE', selected_bad_analysis))
            
            # Job Description section
            st.divider()
            st.subheader("📋 Job Description")
            if has_job_description:
                with st.expander("View/Edit Job Description"):
                    # Allow editing existing job description
                    with st.form(key=f"edit_job_description_form_{job_key}"):
                        current_jd = job_description if job_description else ''
                        job_description_text = st.text_area(
                            "Update Job Description",
                            value=current_jd,
                            key=f"edit_job_description_{job_key}",
                            height=300
                        )
                        if st.form_submit_button("💾 Update Job Description"):
                            handle_field_update(
                                job_url_key, company_key, 'Job Description', job_description_text, current_jd,
                                "✅ Job description updated!"
                            )
            else:
                if sustainable == 'TRUE':
                    st.error("🚨 **CRITICAL: Missing Job Description** - This sustainable company job cannot be analyzed without a job description!")
                else:
                    st.warning("⚠️ **Missing Job Description** - This job cannot be analyzed without a job description.")
                
                # Manual job description input
                with st.form(key=f"job_description_form_{job_key}"):
                    st.subheader("✏️ Add Job Description")
                    current_jd = job_description if job_description else ''
                    job_description_text = st.text_area(
                        "Job Description",
                        value=current_jd,
                        key=f"job_description_{job_key}",
                        height=300,
                        help="Paste the job description from the LinkedIn job posting here"
                    )
                    if st.form_submit_button("💾 Save Job Description"):
                        handle_field_update(
                            job_url_key, company_key, 'Job Description', job_description_text, current_jd,
                            "✅ Job description saved! The job will be analyzed in the next cycle."
                        )
            
            # Company Overview section
            st.divider()
            st.subheader("🏢 Company Overview")
            if company_overview:
                with st.expander("View/Edit Company Overview"):
                    # Manual company overview update (inside expander)
                    with st.form(key=f"company_overview_form_{job_key}"):
                        current_co = company_overview
                        company_overview_text = st.text_area(
                            "Update Company Overview",
                            value=current_co,
                            key=f"company_overview_{job_key}",
                            height=200
                        )
                        if st.form_submit_button("💾 Update Company Overview"):
                            handle_field_update(
                                job_url_key, company_key, 'Company overview', company_overview_text, current_co,
                                "✅ Company overview updated!"
                            )
            else:
                st.warning("⚠️ **Missing Company Overview** - Company overview is needed for sustainability checks and better analysis.")
                # Manual company overview input
                with st.form(key=f"company_overview_missing_form_{job_key}"):
                    st.subheader("✏️ Add Company Overview")
                    current_co = company_overview
                    company_overview_text = st.text_area(
                        "Company Overview",
                        value=current_co,
                        key=f"company_overview_missing_{job_key}",
                        height=200,
                        help="Paste the company overview/description here"
                    )
                    if st.form_submit_button("💾 Save Company Overview"):
                        handle_field_update(
                            job_url_key, company_key, 'Company overview', company_overview_text, current_co,
                            "✅ Company overview saved!"
                        )
            
            # Resume section with inline feedback - lazy load PDF preview
            if resume_url:
                st.divider()
                st.subheader("📄 Tailored Resume")
                
                resume_path = get_resume_path(resume_url)
                
                if resume_path and resume_path.exists():
                    # Display path
                    st.write(f"**Path:** `{resume_path}`")
                    
                    # File info
                    file_size = resume_path.stat().st_size
                    file_mtime = datetime.fromtimestamp(resume_path.stat().st_mtime)
                    st.caption(f"File size: {file_size:,} bytes | Modified: {file_mtime.strftime('%Y-%m-%d %H:%M:%S')}")
                    
                    # PDF Preview - lazy loaded only when expander is opened
                    pdf_cache_key = f"pdf_base64_{resume_path}"
                    with st.expander("📄 Preview Resume PDF", expanded=False):
                        if pdf_cache_key not in st.session_state:
                            with st.spinner("Loading PDF preview..."):
                                try:
                                    import base64
                                    with open(resume_path, 'rb') as f:
                                        pdf_bytes = f.read()
                                        base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
                                        
                                        # LRU eviction: remove oldest cached PDF if at capacity
                                        if len(st.session_state.pdf_cache_keys) >= MAX_PDF_CACHE_SIZE:
                                            oldest_key = st.session_state.pdf_cache_keys.pop(0)
                                            if oldest_key in st.session_state:
                                                del st.session_state[oldest_key]
                                        
                                        # Cache new PDF
                                        st.session_state[pdf_cache_key] = base64_pdf
                                        st.session_state.pdf_cache_keys.append(pdf_cache_key)
                                except Exception as e:
                                    st.session_state[pdf_cache_key] = None
                                    st.warning(f"Could not encode PDF: {e}")
                        
                        if st.session_state.get(pdf_cache_key):
                            pdf_display = f'''
                            <iframe src="data:application/pdf;base64,{st.session_state[pdf_cache_key]}" 
                                    width="700" 
                                    height="900" 
                                    type="application/pdf"
                                    style="border: 1px solid #ccc;">
                            </iframe>
                            '''
                            st.components.v1.html(pdf_display, height=920)
                        else:
                            # Fallback: download button
                            try:
                                with open(resume_path, 'rb') as f:
                                    pdf_bytes = f.read()
                                    st.download_button(
                                        label="Download Resume PDF",
                                        data=pdf_bytes,
                                        file_name=resume_path.name,
                                        mime_type="application/pdf"
                                    )
                            except Exception as download_error:
                                st.error(f"Could not read PDF file: {download_error}")
                    
                    # Open in file manager button
                    if st.button(f"📂 Open in File Manager", key=f"open_{job_key}"):
                        open_file_manager(resume_path)
                        st.success(f"Opened file manager at: {resume_path.parent}")
                    
                    # Resume feedback inline
                    current_resume_feedback = get_row_value(row, 'Resume feedback', '')
                    with st.form(key=f"resume_feedback_form_{job_key}"):
                        resume_feedback_text = st.text_area(
                            "Resume Feedback",
                            value=current_resume_feedback,
                            key=f"resume_feedback_{job_key}",
                            height=100
                        )
                        if st.form_submit_button("💾 Save Resume Feedback"):
                            handle_field_update(
                                job_url_key, company_key, 'Resume feedback', resume_feedback_text, current_resume_feedback,
                                "✅ Resume feedback saved"
                            )
                else:
                    st.warning(f"Resume file not found at: {resume_url}")
                    if resume_path:
                        st.write(f"Expected location: {resume_path}")
            
            # Cover letter section with inline feedback
            if cover_letter:
                st.divider()
                st.subheader("📝 Cover Letter")
                with st.expander("View/Edit Cover Letter"):
                    # CL feedback inline
                    current_cl_feedback = get_row_value(row, 'CL feedback', '')
                    with st.form(key=f"cl_feedback_form_{job_key}"):
                        st.text_area("Current Cover Letter", value=cover_letter, height=400, key=f"cl_view_{job_key}", disabled=True)
                        
                        cl_feedback_text = st.text_area(
                            "Cover Letter Feedback",
                            value=current_cl_feedback,
                            key=f"cl_feedback_{job_key}",
                            height=100
                        )
                        if st.form_submit_button("💾 Save CL Feedback"):
                            handle_field_update(
                                job_url_key, company_key, 'CL feedback', cl_feedback_text, current_cl_feedback,
                                "✅ Cover letter feedback saved"
                            )
    
    # Fixed Undo popup in bottom right
    if st.session_state.undo_stack:
        job_key, field_name, old_value, job_url_key, company_key, company, job_title = st.session_state.undo_stack[-1]
        
        field_display = {
            'Applied': 'Applied',
            'Job posting expired': 'Expired',
            'Bad analysis': 'Bad Analysis'
        }.get(field_name, field_name)
        
        with st.container():
            # Unique marker for CSS to find ONLY this container
            st.markdown('<div class="undo-marker-unique"></div>', unsafe_allow_html=True)
            st.markdown(f'<div class="undo-text">ℹ️ Job hidden</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="undo-subtext"><b>{company}</b> - {job_title}<br/>Marked as {field_display}</div>', unsafe_allow_html=True)
            st.button("↩️ Undo", key="undo_button_fixed", on_click=handle_undo, use_container_width=True)

if __name__ == "__main__":
    main()
