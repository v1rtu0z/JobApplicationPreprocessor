"""Sidebar filters and filter mask application for the Jobs view."""
import pandas as pd
import streamlit as st


JD_FILTER_OPTIONS = ["Unset", "Has", "Missing"]


# Keys that hold filter state (must match what we read in render_sidebar_filters / apply_filter_mask).
FILTER_KEYS = (
    "filter_fit_score",
    "filter_applied_status",
    "filter_expired_status",
    "filter_bad_analysis",
    "filter_sustainable_company",
    "filter_companies",
    "filter_locations",
    "filter_has_resume",
    "filter_has_cover_letter",
    "filter_priority_only",
    "jd_data_filter",
    "co_data_filter",
)


def clear_all_filter_keys() -> None:
    """Clear all filters to show-all state (empty multiselects, Unset for radio). Call before st.rerun()."""
    st.session_state.filter_fit_score = []
    st.session_state.filter_applied_status = []
    st.session_state.filter_expired_status = []
    st.session_state.filter_bad_analysis = []
    st.session_state.filter_sustainable_company = []
    st.session_state.filter_companies = []
    st.session_state.filter_locations = []
    st.session_state.filter_has_resume = []
    st.session_state.filter_has_cover_letter = []
    st.session_state.filter_priority_only = False
    st.session_state.jd_data_filter = "Unset"
    st.session_state.co_data_filter = "Unset"


def apply_default_filter_keys(cache: dict) -> None:
    """Set all filters to default presets (exclude poor fits, show Not Applied/Active/etc). Call before st.rerun()."""
    st.session_state.filter_fit_score = list(cache.get("default_fit_scores", ["Unknown"]))
    st.session_state.filter_applied_status = ["Not Applied", "Unknown"]
    st.session_state.filter_expired_status = ["Active", "Unknown"]
    st.session_state.filter_bad_analysis = ["No", "Unknown"]
    st.session_state.filter_sustainable_company = ["Yes", "Unknown"]
    st.session_state.filter_companies = []
    st.session_state.filter_locations = []
    st.session_state.filter_has_resume = []
    st.session_state.filter_has_cover_letter = []
    st.session_state.filter_priority_only = False
    st.session_state.jd_data_filter = "Unset"
    st.session_state.co_data_filter = "Unset"


def normalize_multiselect(selection):
    """Empty selection means show all. Return selection as-is."""
    return selection if selection else []


def ensure_filter_cache(df: pd.DataFrame) -> None:
    """Ensure filter_options_cache and df_hash are in session state; invalidate if df changed."""
    if "filter_options_cache" not in st.session_state or "df_hash" not in st.session_state:
        _build_filter_cache(df)
        return
    current_df_hash = _df_hash(df)
    if current_df_hash != st.session_state.df_hash:
        if "filter_options_cache" in st.session_state:
            del st.session_state.filter_options_cache
        if "df_hash" in st.session_state:
            del st.session_state.df_hash
        st.rerun()
    else:
        cache = st.session_state.filter_options_cache
        if "filter_fit_score" not in st.session_state:
            st.session_state.filter_fit_score = cache["default_fit_scores"]


def _df_hash(df: pd.DataFrame):
    if len(df) > 0:
        sample_indices = [0]
        if len(df) > 1:
            sample_indices.append(len(df) - 1)
        if len(df) > 2:
            sample_indices.append(len(df) // 2)
        if len(df) > 10:
            step = len(df) // 5
            sample_indices.extend([step * i for i in range(1, 5) if step * i < len(df)])
        sample_urls = tuple(
            df["Job URL"].iloc[i] if i < len(df) else "" for i in sorted(set(sample_indices))
        )
        return hash((len(df), tuple(df.columns), sample_urls))
    return hash((0, tuple(df.columns), ()))


def _build_filter_cache(df: pd.DataFrame) -> None:
    df_hash = _df_hash(df)
    st.session_state.df_hash = df_hash
    fit_score_options = sorted(
        [s for s in df["Fit score"].dropna().unique().tolist() if s], reverse=True
    )
    bad_fits = ["Poor fit", "Very poor fit", "Questionable fit"]
    # Default view excludes poor fits and moderate fit (only Very good / Good fit + Unknown)
    default_exclude = bad_fits + ["Moderate fit"]
    default_fit_scores = [s for s in fit_score_options if s not in default_exclude]
    if "Unknown" not in default_fit_scores:
        default_fit_scores.append("Unknown")
    locations = sorted([l for l in df["Location"].dropna().unique().tolist() if l])
    companies = sorted([c for c in df["Company Name"].dropna().unique().tolist() if c])
    st.session_state.filter_options_cache = {
        "fit_score_options": fit_score_options,
        "default_fit_scores": default_fit_scores,
        "locations": locations,
        "companies": companies,
    }
    if "filter_fit_score" not in st.session_state:
        st.session_state.filter_fit_score = default_fit_scores


def render_sidebar_filters(df: pd.DataFrame, check_sustainability_enabled: bool = False) -> dict:
    """Render sidebar filter widgets and return a dict of selections for apply_filter_mask.
    Sustainable filter and priority checkbox only shown when check_sustainability_enabled (from .env).
    """
    cache = st.session_state.filter_options_cache
    fit_score_options = cache["fit_score_options"]
    default_fit_scores = cache["default_fit_scores"]
    locations = cache["locations"]
    companies = cache["companies"]

    st.sidebar.header("🔍 Filters")
    clear_col, default_col = st.sidebar.columns(2)
    with clear_col:
        if st.sidebar.button("Clear all", key="filter_clear_all", use_container_width=True):
            clear_all_filter_keys()
            st.rerun()
    with default_col:
        if st.sidebar.button("Apply defaults", key="filter_apply_defaults", use_container_width=True):
            apply_default_filter_keys(cache)
            st.rerun()
    st.sidebar.caption("💡 Tip: Leave multiselect filters empty to show all")

    # Use only key= for keyed widgets so Streamlit uses session_state[key] as the value.
    # Passing default= with key= can cause widgets to reset on rerun (e.g. after Refresh or filter change).
    fit_score_options_with_meta = ["Unknown"] + fit_score_options
    selected_fit_scores_raw = st.sidebar.multiselect(
        "Fit Score",
        fit_score_options_with_meta,
        key="filter_fit_score",
    )
    selected_fit_scores = normalize_multiselect(selected_fit_scores_raw)

    applied_options = ["Applied", "Not Applied", "Unknown"]
    selected_applied_raw = st.sidebar.multiselect(
        "Applied Status",
        applied_options,
        key="filter_applied_status",
    )
    selected_applied = normalize_multiselect(selected_applied_raw)

    has_resume_options = ["Yes", "No", "Unknown"]
    selected_resume_raw = st.sidebar.multiselect(
        "Has Resume",
        has_resume_options,
        key="filter_has_resume",
    )
    selected_resume = normalize_multiselect(selected_resume_raw)

    has_cl_options = ["Yes", "No", "Unknown"]
    selected_cl_raw = st.sidebar.multiselect(
        "Has Cover Letter",
        has_cl_options,
        key="filter_has_cover_letter",
    )
    selected_cl = normalize_multiselect(selected_cl_raw)

    expired_options = ["Active", "Expired", "Unknown"]
    selected_expired_raw = st.sidebar.multiselect(
        "Expired Status",
        expired_options,
        key="filter_expired_status",
    )
    selected_expired = normalize_multiselect(selected_expired_raw)

    if "Bad analysis" in df.columns:
        selected_bad_analysis_raw = st.sidebar.multiselect(
            "Bad Analysis",
            ["Yes", "No", "Unknown"],
            key="filter_bad_analysis",
        )
        selected_bad_analysis = normalize_multiselect(selected_bad_analysis_raw)
    else:
        selected_bad_analysis = []

    if check_sustainability_enabled and "Sustainable company" in df.columns:
        selected_sustainable_raw = st.sidebar.multiselect(
            "Sustainable Company",
            ["Yes", "No", "Unknown"],
            key="filter_sustainable_company",
        )
        selected_sustainable = normalize_multiselect(selected_sustainable_raw)
    else:
        selected_sustainable = []
        selected_sustainable_raw = []

    st.sidebar.divider()
    st.sidebar.header("⚠️ Data completeness")
    selected_jd_data = st.sidebar.radio(
        "Job Description",
        JD_FILTER_OPTIONS,
        key="jd_data_filter",
    )
    if "Company overview" in df.columns:
        selected_co_data = st.sidebar.radio(
            "Company Overview",
            JD_FILTER_OPTIONS,
            key="co_data_filter",
        )
    else:
        selected_co_data = "Unset"

    if check_sustainability_enabled and "Sustainable company" in df.columns:
        show_priority_only = st.sidebar.checkbox(
            "🔴 Show only sustainable jobs missing descriptions",
            key="filter_priority_only",
        )
    else:
        show_priority_only = False

    st.sidebar.divider()
    st.sidebar.caption("📍 Location & Company Filters")
    selected_locations_raw = st.sidebar.multiselect(
        "Location",
        ["Unknown"] + locations,
        key="filter_locations",
    )
    selected_locations = normalize_multiselect(selected_locations_raw)

    selected_company_raw = st.sidebar.multiselect(
        "Company",
        ["Unknown"] + companies,
        key="filter_companies",
    )
    selected_company = normalize_multiselect(selected_company_raw)

    return {
        "selected_fit_scores": selected_fit_scores,
        "selected_fit_scores_raw": selected_fit_scores_raw,
        "selected_applied": selected_applied,
        "selected_applied_raw": selected_applied_raw,
        "selected_resume": selected_resume,
        "selected_resume_raw": selected_resume_raw,
        "selected_cl": selected_cl,
        "selected_cl_raw": selected_cl_raw,
        "selected_expired": selected_expired,
        "selected_expired_raw": selected_expired_raw,
        "selected_bad_analysis": selected_bad_analysis,
        "selected_bad_analysis_raw": selected_bad_analysis_raw,
        "selected_sustainable": selected_sustainable,
        "selected_sustainable_raw": selected_sustainable_raw,
        "selected_jd_data": selected_jd_data,
        "selected_co_data": selected_co_data,
        "show_priority_only": show_priority_only,
        "selected_locations": selected_locations,
        "selected_locations_raw": selected_locations_raw,
        "selected_company": selected_company,
        "selected_company_raw": selected_company_raw,
    }


def apply_filter_mask(df: pd.DataFrame, selections: dict) -> pd.DataFrame:
    """Apply filter mask from selections; return filtered DataFrame."""
    filter_mask = pd.Series([True] * len(df), index=df.index)
    selected_fit_scores = selections["selected_fit_scores"]
    selected_applied = selections["selected_applied"]
    selected_bad_analysis = selections.get("selected_bad_analysis") or []
    selected_expired = selections["selected_expired"]
    selected_sustainable = selections.get("selected_sustainable") or []
    selected_resume = selections["selected_resume"]
    selected_cl = selections["selected_cl"]
    selected_locations = selections["selected_locations"]
    selected_company = selections["selected_company"]
    selected_jd_data = selections["selected_jd_data"]
    selected_co_data = selections["selected_co_data"]
    show_priority_only = selections["show_priority_only"]

    if selected_fit_scores:
        if "Unknown" in selected_fit_scores:
            fit_mask = (
                df["Fit score"].isna()
                | (df["Fit score"] == "")
                | df["Fit score"].isin([s for s in selected_fit_scores if s != "Unknown"])
            )
        else:
            fit_mask = df["Fit score"].isin(selected_fit_scores)
        filter_mask = filter_mask & fit_mask

    if "Applied" in df.columns and selected_applied:
        applied_mask = pd.Series([False] * len(df), index=df.index)
        if "Applied" in selected_applied:
            applied_mask = applied_mask | (df["Applied"] == "TRUE")
        if "Not Applied" in selected_applied:
            applied_mask = applied_mask | (df["Applied"] != "TRUE")
        if "Unknown" in selected_applied:
            applied_mask = applied_mask | (df["Applied"].isna() | (df["Applied"] == ""))
        filter_mask = filter_mask & applied_mask

    if "Bad analysis" in df.columns and selected_bad_analysis:
        bad_analysis_mask = pd.Series([False] * len(df), index=df.index)
        if "Yes" in selected_bad_analysis:
            bad_analysis_mask = bad_analysis_mask | (df["Bad analysis"] == "TRUE")
        if "No" in selected_bad_analysis:
            bad_analysis_mask = bad_analysis_mask | (df["Bad analysis"] != "TRUE")
        if "Unknown" in selected_bad_analysis:
            bad_analysis_mask = bad_analysis_mask | (
                df["Bad analysis"].isna() | (df["Bad analysis"] == "")
            )
        filter_mask = filter_mask & bad_analysis_mask

    if "Job posting expired" in df.columns and selected_expired:
        expired_mask = pd.Series([False] * len(df), index=df.index)
        if "Expired" in selected_expired:
            expired_mask = expired_mask | (df["Job posting expired"] == "TRUE")
        if "Active" in selected_expired:
            expired_mask = expired_mask | (df["Job posting expired"] != "TRUE")
        if "Unknown" in selected_expired:
            expired_mask = expired_mask | (
                df["Job posting expired"].isna() | (df["Job posting expired"] == "")
            )
        filter_mask = filter_mask & expired_mask

    if "Sustainable company" in df.columns and selected_sustainable:
        sustainable_mask = pd.Series([False] * len(df), index=df.index)
        if "Yes" in selected_sustainable:
            sustainable_mask = sustainable_mask | (df["Sustainable company"] == "TRUE")
        if "No" in selected_sustainable:
            sustainable_mask = sustainable_mask | (df["Sustainable company"] == "FALSE")
        if "Unknown" in selected_sustainable:
            sustainable_mask = sustainable_mask | (
                df["Sustainable company"].isna() | (df["Sustainable company"] == "")
            )
        filter_mask = filter_mask & sustainable_mask

    if selected_resume:
        resume_mask = pd.Series([False] * len(df), index=df.index)
        if "Yes" in selected_resume:
            resume_mask = resume_mask | (
                df["Tailored resume url"].notna() & (df["Tailored resume url"] != "")
            )
        if "No" in selected_resume or "Unknown" in selected_resume:
            resume_mask = resume_mask | (
                df["Tailored resume url"].isna() | (df["Tailored resume url"] == "")
            )
        filter_mask = filter_mask & resume_mask

    if selected_cl:
        cl_mask = pd.Series([False] * len(df), index=df.index)
        cl_col = "Tailored cover letter (to be humanized)"
        if "Yes" in selected_cl:
            cl_mask = cl_mask | (df[cl_col].notna() & (df[cl_col] != ""))
        if "No" in selected_cl or "Unknown" in selected_cl:
            cl_mask = cl_mask | (df[cl_col].isna() | (df[cl_col] == ""))
        filter_mask = filter_mask & cl_mask

    if selected_locations:
        if "Unknown" in selected_locations:
            location_mask = (
                df["Location"].isna()
                | (df["Location"] == "")
                | df["Location"].isin([l for l in selected_locations if l != "Unknown"])
            )
        else:
            location_mask = df["Location"].isin(selected_locations)
        filter_mask = filter_mask & location_mask

    if selected_company:
        if "Unknown" in selected_company:
            company_mask = (
                df["Company Name"].isna()
                | (df["Company Name"] == "")
                | df["Company Name"].isin([c for c in selected_company if c != "Unknown"])
            )
        else:
            company_mask = df["Company Name"].isin(selected_company)
        filter_mask = filter_mask & company_mask

    has_jd = df["Job Description"].notna() & (df["Job Description"] != "")
    has_co = (
        (df["Company overview"].notna() & (df["Company overview"] != ""))
        if "Company overview" in df.columns
        else pd.Series([False] * len(df), index=df.index)
    )

    if selected_jd_data == "Has":
        filter_mask = filter_mask & has_jd
    elif selected_jd_data == "Missing":
        filter_mask = filter_mask & ~has_jd

    if selected_co_data == "Has":
        filter_mask = filter_mask & has_co
    elif selected_co_data == "Missing":
        filter_mask = filter_mask & ~has_co

    if show_priority_only:
        is_sustainable = (
            df["Sustainable company"] == "TRUE"
            if "Sustainable company" in df.columns
            else pd.Series([False] * len(df), index=df.index)
        )
        filter_mask = filter_mask & is_sustainable & ~has_jd

    return df[filter_mask].copy()
