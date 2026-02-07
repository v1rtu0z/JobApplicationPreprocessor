"""Jobs view: list, filters, sorting, pagination, job cards, undo popup."""
import base64
import time
from datetime import datetime

import pandas as pd
import streamlit as st

from config import _get_job_filters
from .constants import (
    AUTO_REFRESH_INTERVAL,
    MAX_PDF_CACHE_SIZE,
    PAGE_SIZE,
    UNDO_POPUP_TIMEOUT,
)
from .data import (
    get_check_sustainability,
    handle_field_update,
    load_job_data,
    open_file_manager,
    get_resume_path,
    update_job_field,
)
from .filters import (
    FILTER_KEYS,
    JD_FILTER_OPTIONS,
    apply_filter_mask,
    ensure_filter_cache,
    render_sidebar_filters,
)
from .job_cards import get_row_value


def _init_jobs_session_state() -> None:
    """Initialize session state keys for the Jobs view (including filter migration)."""
    if "hidden_jobs" not in st.session_state:
        st.session_state.hidden_jobs = set()
    if "undo_stack" not in st.session_state:
        st.session_state.undo_stack = []
    if "undo_stack_timestamp" not in st.session_state:
        st.session_state.undo_stack_timestamp = None
    if "page_index" not in st.session_state:
        st.session_state.page_index = 0
    if "page_jump" not in st.session_state:
        st.session_state.page_jump = 1
    if "pagination_context_hash" not in st.session_state:
        st.session_state.pagination_context_hash = None

    # Restore all filters after refresh so cleared/default state is never overwritten
    if "_preserve_filters" in st.session_state:
        for k, v in st.session_state._preserve_filters.items():
            st.session_state[k] = v
        del st.session_state._preserve_filters

    if "jd_data_filter" not in st.session_state:
        st.session_state.jd_data_filter = "Unset"
    else:
        current_value = st.session_state.jd_data_filter
        is_old_format = isinstance(current_value, list) and len(current_value) == 0
        is_invalid = not isinstance(current_value, str) or current_value not in JD_FILTER_OPTIONS
        if is_old_format or is_invalid:
            st.session_state.jd_data_filter = "Unset"

    if "co_data_filter" not in st.session_state:
        st.session_state.co_data_filter = "Unset"
    else:
        current_value = st.session_state.co_data_filter
        is_old_format = isinstance(current_value, list) and len(current_value) == 0
        is_invalid = not isinstance(current_value, str) or current_value not in JD_FILTER_OPTIONS
        if is_old_format or is_invalid:
            st.session_state.co_data_filter = "Unset"

    if "filter_applied_status" not in st.session_state:
        st.session_state.filter_applied_status = ["Not Applied", "Unknown"]
    if "filter_expired_status" not in st.session_state:
        st.session_state.filter_expired_status = ["Active", "Unknown"]
    if "filter_bad_analysis" not in st.session_state:
        st.session_state.filter_bad_analysis = ["No", "Unknown"]
    if "filter_sustainable_company" not in st.session_state:
        st.session_state.filter_sustainable_company = ["Yes", "Unknown"]

    # Initialize filter keys so keyed widgets use only session_state (no default=).
    # Passing default= to keyed widgets can cause Streamlit to reset selections on rerun/refresh.
    if "filter_companies" not in st.session_state:
        st.session_state.filter_companies = []
    if "filter_locations" not in st.session_state:
        st.session_state.filter_locations = []
    if "filter_has_resume" not in st.session_state:
        st.session_state.filter_has_resume = []
    if "filter_has_cover_letter" not in st.session_state:
        st.session_state.filter_has_cover_letter = []
    if "filter_priority_only" not in st.session_state:
        st.session_state.filter_priority_only = False


def render_jobs_view() -> None:
    """Render the Jobs view: data, filters, sorting, pagination, job cards, undo, pager."""
    _init_jobs_session_state()

    def on_checkbox_change(
        job_key, field_name, job_url_key, company_key, company, job_title, current_val, filter_selection
    ):
        key = f"{field_name.lower().replace(' ', '_')}_{job_key}"
        if key not in st.session_state:
            return
        new_val = st.session_state[key]
        update_job_field(job_url_key, company_key, field_name, "TRUE" if new_val else "FALSE")
        df = st.session_state.df
        mask = (df.get("Job URL", "") == job_url_key) & (df.get("Company Name", "") == company_key)
        df.loc[mask, field_name] = "TRUE" if new_val else "FALSE"
        st.session_state.df = df

        should_hide = False
        if field_name == "Applied":
            if not new_val and filter_selection and "Not Applied" not in filter_selection and "Unknown" not in filter_selection:
                should_hide = True
            elif new_val and filter_selection and "Applied" not in filter_selection:
                should_hide = True
        elif field_name == "Job posting expired":
            if new_val and filter_selection and "Expired" not in filter_selection:
                should_hide = True
            elif not new_val and filter_selection and "Active" not in filter_selection and "Unknown" not in filter_selection:
                should_hide = True
        elif field_name == "Bad analysis":
            if new_val and filter_selection and "Yes" not in filter_selection:
                should_hide = True
            elif not new_val and filter_selection and "No" not in filter_selection and "Unknown" not in filter_selection:
                should_hide = True
        elif field_name == "Sustainable company":
            if new_val and filter_selection and "Yes" not in filter_selection:
                should_hide = True
            elif not new_val and filter_selection and "No" not in filter_selection and "Unknown" not in filter_selection:
                should_hide = True

        if should_hide:
            st.session_state.hidden_jobs.add(job_key)
            st.session_state.undo_stack.append(
                (job_key, field_name, current_val, job_url_key, company_key, company, job_title)
            )
            st.session_state.undo_stack_timestamp = time.time()

    def handle_undo():
        if st.session_state.undo_stack:
            job_key, field_name, old_value, job_url_key, company_key, company, job_title = (
                st.session_state.undo_stack.pop()
            )
            update_job_field(job_url_key, company_key, field_name, old_value)
            df = st.session_state.df
            mask = (df.get("Job URL", "") == job_url_key) & (df.get("Company Name", "") == company_key)
            df.loc[mask, field_name] = old_value
            st.session_state.df = df
            st.session_state.hidden_jobs.discard(job_key)
            if not st.session_state.undo_stack:
                st.session_state.undo_stack_timestamp = None

    # Header with refresh
    col_header1, col_header2, col_header3 = st.columns([3, 1, 1])
    with col_header1:
        st.markdown("View and manage your job applications")
    with col_header2:
        if st.button("🔄 Refresh", use_container_width=True):
            st.cache_data.clear()
            st.session_state.df, error = load_job_data()
            if error:
                st.error(error)
            # Preserve all filter state across rerun so current filters (including cleared) are kept
            st.session_state._preserve_filters = {
                k: st.session_state.get(k)
                for k in FILTER_KEYS
                if k in st.session_state
            }
            # Fill in any missing keys with show-all defaults so restore is complete
            for k in FILTER_KEYS:
                if k not in st.session_state._preserve_filters:
                    if k in ("jd_data_filter", "co_data_filter"):
                        st.session_state._preserve_filters[k] = "Unset"
                    elif k == "filter_priority_only":
                        st.session_state._preserve_filters[k] = False
                    else:
                        st.session_state._preserve_filters[k] = []
            if "filter_options_cache" in st.session_state:
                del st.session_state.filter_options_cache
            if "df_hash" in st.session_state:
                del st.session_state.df_hash
            st.rerun()
    with col_header3:
        auto_refresh = st.checkbox("Auto-refresh", value=True, key="jobs_auto_refresh")

    if st.session_state.undo_stack and st.session_state.undo_stack_timestamp is not None:
        elapsed_time = time.time() - st.session_state.undo_stack_timestamp
        if elapsed_time >= UNDO_POPUP_TIMEOUT:
            st.session_state.undo_stack.clear()
            st.session_state.undo_stack_timestamp = None

    if auto_refresh:
        current_time = time.time()
        refresh_interval = (
            5
            if (st.session_state.undo_stack and st.session_state.undo_stack_timestamp)
            else AUTO_REFRESH_INTERVAL
        )
        if current_time - st.session_state.last_refresh > refresh_interval:
            st.session_state.last_refresh = current_time
            st.cache_data.clear()
            st.session_state.df, error = load_job_data()
            if error:
                st.error(f"Auto-refresh error: {error}")
            else:
                st.rerun()

    df = st.session_state.df
    if df is None or df.empty:
        st.info("No jobs found.")
        return

    if "pdf_cache_keys" not in st.session_state:
        st.session_state.pdf_cache_keys = []

    filters_config = _get_job_filters()
    has_location_priorities = bool(filters_config.get("location_priorities", {}))
    check_sustainability_enabled = get_check_sustainability()

    ensure_filter_cache(df)
    selections = render_sidebar_filters(df, check_sustainability_enabled)
    filtered_df = apply_filter_mask(df, selections)

    # Sidebar stats
    st.sidebar.divider()
    st.sidebar.header("📊 Statistics")
    st.sidebar.metric("Total Jobs", len(filtered_df))
    if "Tailored resume url" in filtered_df.columns:
        with_resumes = len(
            filtered_df[
                filtered_df["Tailored resume url"].notna()
                & (filtered_df["Tailored resume url"] != "")
            ]
        )
        st.sidebar.metric("With Resumes", with_resumes)
    else:
        st.sidebar.metric("With Resumes", 0)
    if "Applied" in filtered_df.columns:
        applied_count = len(filtered_df[filtered_df["Applied"] == "TRUE"])
        st.sidebar.metric("Applied", applied_count)
    else:
        st.sidebar.metric("Applied", 0)
    if check_sustainability_enabled and "Sustainable company" in df.columns:
        st.sidebar.divider()
        st.sidebar.header("🌱 Sustainability")
        st.sidebar.metric(
            "✅ Sustainable",
            len(filtered_df[filtered_df["Sustainable company"] == "TRUE"]),
        )
        st.sidebar.metric(
            "❌ Not Sustainable",
            len(filtered_df[filtered_df["Sustainable company"] == "FALSE"]),
        )
        st.sidebar.metric(
            "❓ Unknown",
            len(
                filtered_df[
                    filtered_df["Sustainable company"].isna()
                    | (filtered_df["Sustainable company"] == "")
                ]
            ),
        )
    if len(filtered_df) > 0:
        st.sidebar.divider()
        st.sidebar.header("⭐ Fit Score Breakdown")
        fit_breakdown = filtered_df["Fit score"].value_counts()
        for score, count in fit_breakdown.items():
            if score:
                st.sidebar.text(f"{score}: {count}")
        unknown_fit = len(
            filtered_df[filtered_df["Fit score"].isna() | (filtered_df["Fit score"] == "")]
        )
        if unknown_fit > 0:
            st.sidebar.text(f"Unknown: {unknown_fit}")

    column_index_map = {col: idx for idx, col in enumerate(filtered_df.columns)}

    def _get(row, col: str, default: str = ""):
        return get_row_value(row, col, column_index_map, default)

    visible_count = 0
    for row_idx, row in enumerate(filtered_df.itertuples(index=False)):
        job_key = f"{_get(row, 'Job URL', '')}|{_get(row, 'Company Name', '')}|{row_idx}"
        if job_key not in st.session_state.hidden_jobs:
            visible_count += 1
    st.header(f"Job Listings ({visible_count} jobs)")

    # Sorting
    st.subheader("Sorting")
    col_sort1, col_sort2, col_sort3 = st.columns(3)
    with col_sort1:
        sort_by_1 = st.selectbox(
            "Primary Sort",
            ["Location Priority", "Fit Score", "Company", "Location"],
            key="sort_by_1",
            index=0,
        )
        sort_order_1 = st.selectbox("Order", ["Descending", "Ascending"], key="sort_order_1", index=0)
    with col_sort2:
        sort_by_2 = st.selectbox(
            "Secondary Sort",
            ["Fit Score", "Location Priority", "Company", "Location"],
            key="sort_by_2",
            index=0,
        )
        sort_order_2 = st.selectbox("Order", ["Descending", "Ascending"], key="sort_order_2", index=0)
    with col_sort3:
        sort_by_3 = st.selectbox(
            "Tertiary Sort",
            ["None", "Company", "Location", "Fit Score", "Location Priority"],
            key="sort_by_3",
            index=0,
        )
        sort_order_3 = st.selectbox("Order", ["Descending", "Ascending"], key="sort_order_3", index=0)

    sort_columns = []
    sort_ascending = []

    if sort_by_1 == "Location Priority" and "Location Priority" in filtered_df.columns:
        sort_columns.append("Location Priority")
        sort_ascending.append(sort_order_1 == "Ascending")
    elif sort_by_1 == "Fit Score":
        if "Fit score enum" in filtered_df.columns:
            sort_columns.append("Fit score enum")
            sort_ascending.append(sort_order_1 == "Ascending")
        elif "Fit score" in filtered_df.columns:
            sort_columns.append("Fit score")
            sort_ascending.append(sort_order_1 == "Ascending")
    elif sort_by_1 == "Company":
        sort_columns.append("Company Name")
        sort_ascending.append(sort_order_1 == "Ascending")
    elif sort_by_1 == "Location":
        sort_columns.append("Location")
        sort_ascending.append(sort_order_1 == "Ascending")

    if sort_by_2 != sort_by_1 and sort_by_2 != "None":
        if sort_by_2 == "Location Priority" and "Location Priority" in filtered_df.columns:
            sort_columns.append("Location Priority")
            sort_ascending.append(sort_order_2 == "Ascending")
        elif sort_by_2 == "Fit Score":
            if "Fit score enum" in filtered_df.columns:
                sort_columns.append("Fit score enum")
                sort_ascending.append(sort_order_2 == "Ascending")
            elif "Fit score" in filtered_df.columns:
                sort_columns.append("Fit score")
                sort_ascending.append(sort_order_2 == "Ascending")
        elif sort_by_2 == "Company":
            sort_columns.append("Company Name")
            sort_ascending.append(sort_order_2 == "Ascending")
        elif sort_by_2 == "Location":
            sort_columns.append("Location")
            sort_ascending.append(sort_order_2 == "Ascending")

    if sort_by_3 != "None" and sort_by_3 != sort_by_1 and sort_by_3 != sort_by_2:
        if sort_by_3 == "Location Priority" and "Location Priority" in filtered_df.columns:
            sort_columns.append("Location Priority")
            sort_ascending.append(sort_order_3 == "Ascending")
        elif sort_by_3 == "Fit Score":
            if "Fit score enum" in filtered_df.columns:
                sort_columns.append("Fit score enum")
                sort_ascending.append(sort_order_3 == "Ascending")
            elif "Fit score" in filtered_df.columns:
                sort_columns.append("Fit score")
                sort_ascending.append(sort_order_3 == "Ascending")
        elif sort_by_3 == "Company":
            sort_columns.append("Company Name")
            sort_ascending.append(sort_order_3 == "Ascending")
        elif sort_by_3 == "Location":
            sort_columns.append("Location")
            sort_ascending.append(sort_order_3 == "Ascending")

    if sort_columns:
        filtered_df = filtered_df.sort_values(sort_columns, ascending=sort_ascending)

    visible_jobs_list = []
    for row_idx, row in enumerate(filtered_df.itertuples(index=False)):
        job_key = f"{_get(row, 'Job URL', '')}|{_get(row, 'Company Name', '')}|{row_idx}"
        if job_key not in st.session_state.hidden_jobs:
            visible_jobs_list.append((row_idx, row))

    pagination_context = (
        st.session_state.get("df_hash"),
        tuple(selections["selected_fit_scores_raw"]),
        tuple(selections["selected_applied_raw"]),
        tuple(selections["selected_resume_raw"]),
        tuple(selections["selected_cl_raw"]),
        tuple(selections["selected_expired_raw"]),
        tuple(selections.get("selected_bad_analysis_raw") or []),
        tuple(selections.get("selected_sustainable_raw") or []),
        selections["selected_jd_data"],
        selections["selected_co_data"],
        selections["show_priority_only"],
        tuple(selections["selected_locations_raw"]),
        tuple(selections["selected_company_raw"]),
        sort_by_1,
        sort_order_1,
        sort_by_2,
        sort_order_2,
        sort_by_3,
        sort_order_3,
        len(st.session_state.hidden_jobs),
    )
    current_context_hash = hash(pagination_context)
    if st.session_state.pagination_context_hash != current_context_hash:
        st.session_state.pagination_context_hash = current_context_hash
        st.session_state.page_index = 0
        st.session_state.page_jump = 1

    total_items = len(visible_jobs_list)
    total_pages = max(1, (total_items + PAGE_SIZE - 1) // PAGE_SIZE)
    st.session_state.page_index = max(
        0, min(int(st.session_state.page_index), total_pages - 1)
    )
    st.session_state.page_jump = st.session_state.page_index + 1

    start_idx = st.session_state.page_index * PAGE_SIZE
    end_idx = min(start_idx + PAGE_SIZE, total_items)
    paginated_jobs_list = visible_jobs_list[start_idx:end_idx]

    selected_applied = selections["selected_applied"]
    selected_expired = selections["selected_expired"]
    selected_bad_analysis = selections.get("selected_bad_analysis") or []
    selected_sustainable = selections.get("selected_sustainable") or []

    for _display_idx, (original_row_idx, row) in enumerate(paginated_jobs_list):
        job_url_key = _get(row, "Job URL", "")
        company_key = _get(row, "Company Name", "")
        job_key = f"{job_url_key}|{company_key}|{original_row_idx}"

        fit_score = _get(row, "Fit score", "") or "Unknown"
        company = _get(row, "Company Name", "N/A")
        job_title = _get(row, "Job Title", "N/A")
        location = _get(row, "Location", "N/A")
        location_priority = _get(row, "Location Priority", "")
        resume_url = _get(row, "Tailored resume url", "")
        job_url = _get(row, "Job URL", "")
        company_overview = _get(row, "Company overview", "")
        sustainable = _get(row, "Sustainable company", "")
        job_analysis = _get(row, "Job analysis", "")
        has_bad_analysis = _get(row, "Bad analysis", "") == "TRUE"
        job_description = _get(row, "Job Description", "")
        has_job_description = bool(job_description.strip() if job_description else False)
        has_company_overview = bool(company_overview.strip() if company_overview else False)
        missing_jd = not has_job_description
        missing_co = not has_company_overview
        applied = _get(row, "Applied", "")
        expired = _get(row, "Job posting expired", "")
        cover_letter = _get(row, "Tailored cover letter (to be humanized)", "")

        if fit_score == "Very good fit":
            color = "🟢"
        elif fit_score == "Good fit":
            color = "🟡"
        elif fit_score in ["Poor fit", "Very poor fit"]:
            color = "🔴"
        else:
            color = "⚪"

        title_parts = [f"{color} {company} - {job_title}"]
        if location:
            title_parts.append(f"📍 {location}")
        if fit_score and fit_score != "Unknown":
            title_parts.append(f"⭐ {fit_score}")
        # FALSE due only to missing CO is shown as Missing CO, not "Not Sustainable"
        unsustainable_no_co = (
            sustainable == "FALSE"
            and (missing_co or "Insufficient company overview" in (job_analysis or ""))
        )
        if check_sustainability_enabled and "Sustainable company" in df.columns:
            if sustainable == "TRUE":
                title_parts.append("🌱 Sustainable")
            elif sustainable == "FALSE" and not unsustainable_no_co:
                title_parts.append("⚠️ Not Sustainable")
        if applied == "TRUE":
            title_parts.append("✅ Applied")
        if expired == "TRUE":
            title_parts.append("❌ Expired")
        if missing_jd:
            if check_sustainability_enabled and sustainable == "TRUE":
                title_parts.insert(0, "🔴⚠️")
            else:
                title_parts.append("⚠️ Missing JD")
        if missing_co:
            title_parts.append("⚠️ Missing CO")

        # Show "Apply" at top only when fit is at least moderate; otherwise same fields live in Job details
        show_apply_at_top = fit_score in ("Moderate fit", "Good fit", "Very good fit")
        expanded = job_key == st.session_state.get("expanded_job_row")
        with st.expander(" | ".join(title_parts), expanded=expanded):
            if show_apply_at_top:
                st.subheader("🔗 Apply")
                if job_url:
                    url_col1, url_col2 = st.columns([3, 1])
                    with url_col1:
                        st.write(f"**Job URL:** [{job_url}]({job_url})")
                    with url_col2:
                        current_expired = expired == "TRUE"
                        st.checkbox(
                            "Expired",
                            value=current_expired,
                            key=f"job_posting_expired_{job_key}",
                            on_change=on_checkbox_change,
                            args=(
                                job_key,
                                "Job posting expired",
                                job_url_key,
                                company_key,
                                company,
                                job_title,
                                "TRUE" if current_expired else "FALSE",
                                selected_expired,
                            ),
                        )
                current_applied = applied == "TRUE"
                st.checkbox(
                    "✅ Applied",
                    value=current_applied,
                    key=f"applied_{job_key}",
                    on_change=on_checkbox_change,
                    args=(
                        job_key,
                        "Applied",
                        job_url_key,
                        company_key,
                        company,
                        job_title,
                        "TRUE" if current_applied else "FALSE",
                        selected_applied,
                    ),
                )
                st.divider()

            if resume_url:
                st.subheader("📄 Tailored Resume")
                resume_path = get_resume_path(resume_url)
                if resume_path and resume_path.exists():
                    st.write(f"**Path:** `{resume_path}`")
                    file_size = resume_path.stat().st_size
                    file_mtime = datetime.fromtimestamp(resume_path.stat().st_mtime)
                    st.caption(
                        f"File size: {file_size:,} bytes | Modified: {file_mtime.strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    pdf_cache_key = f"pdf_base64_{resume_path}"
                    with st.expander("📄 Preview Resume PDF", expanded=False):
                        if pdf_cache_key not in st.session_state:
                            with st.spinner("Loading PDF preview..."):
                                try:
                                    with open(resume_path, "rb") as f:
                                        pdf_bytes = f.read()
                                        base64_pdf = base64.b64encode(pdf_bytes).decode("utf-8")
                                        if len(st.session_state.pdf_cache_keys) >= MAX_PDF_CACHE_SIZE:
                                            oldest_key = st.session_state.pdf_cache_keys.pop(0)
                                            if oldest_key in st.session_state:
                                                del st.session_state[oldest_key]
                                        st.session_state[pdf_cache_key] = base64_pdf
                                        st.session_state.pdf_cache_keys.append(pdf_cache_key)
                                except Exception as e:
                                    st.session_state[pdf_cache_key] = None
                                    st.warning(f"Could not encode PDF: {e}")
                        if st.session_state.get(pdf_cache_key):
                            pdf_display = f'''
                            <iframe src="data:application/pdf;base64,{st.session_state[pdf_cache_key]}"
                                    width="700" height="900" type="application/pdf"
                                    style="border: 1px solid #ccc;">
                            </iframe>
                            '''
                            st.components.v1.html(pdf_display, height=920)
                        else:
                            try:
                                with open(resume_path, "rb") as f:
                                    st.download_button(
                                        label="Download Resume PDF",
                                        data=f.read(),
                                        file_name=resume_path.name,
                                        mime_type="application/pdf",
                                    )
                            except Exception as download_error:
                                st.error(f"Could not read PDF file: {download_error}")
                    if st.button(f"📂 Open in File Manager", key=f"open_{job_key}"):
                        open_file_manager(resume_path)
                        st.success(f"Opened file manager at: {resume_path.parent}")

                    current_resume_feedback = _get(row, "Resume feedback", "")
                    rf_key = f"resume_feedback_{job_key}"
                    rf_loaded_key = f"{rf_key}__loaded"
                    if rf_key not in st.session_state:
                        st.session_state[rf_key] = current_resume_feedback
                        st.session_state[rf_loaded_key] = current_resume_feedback
                    else:
                        last_loaded = st.session_state.get(rf_loaded_key, current_resume_feedback)
                        if st.session_state.get(rf_key, "") == last_loaded and current_resume_feedback != last_loaded:
                            st.session_state[rf_key] = current_resume_feedback
                        st.session_state[rf_loaded_key] = current_resume_feedback
                    st.text_area("Resume Feedback", key=rf_key, height=100)
                    if st.button("💾 Save Resume Feedback", key=f"save_resume_feedback_{job_key}"):
                        st.session_state.expanded_job_row = job_key
                        st.session_state.last_refresh = time.time()
                        handle_field_update(
                            job_url_key,
                            company_key,
                            "Resume feedback",
                            st.session_state.get(rf_key, ""),
                            current_resume_feedback,
                            "✅ Resume feedback saved",
                        )
                else:
                    st.warning(f"Resume file not found at: {resume_url}")
                    if resume_path:
                        st.write(f"Expected location: {resume_path}")

            if cover_letter:
                st.divider()
                st.subheader("📝 Cover Letter")
                with st.expander("View/Edit Cover Letter"):
                    current_cl_feedback = _get(row, "CL feedback", "")
                    st.text_area(
                        "Current Cover Letter",
                        value=cover_letter,
                        height=400,
                        key=f"cl_view_{job_key}",
                        disabled=True,
                    )
                    cf_key = f"cl_feedback_{job_key}"
                    cf_loaded_key = f"{cf_key}__loaded"
                    if cf_key not in st.session_state:
                        st.session_state[cf_key] = current_cl_feedback
                        st.session_state[cf_loaded_key] = current_cl_feedback
                    else:
                        last_loaded = st.session_state.get(cf_loaded_key, current_cl_feedback)
                        if st.session_state.get(cf_key, "") == last_loaded and current_cl_feedback != last_loaded:
                            st.session_state[cf_key] = current_cl_feedback
                        st.session_state[cf_loaded_key] = current_cl_feedback
                    st.text_area("Cover Letter Feedback", key=cf_key, height=100)
                    if st.button("💾 Save CL Feedback", key=f"save_cl_feedback_{job_key}"):
                        st.session_state.expanded_job_row = job_key
                        st.session_state.last_refresh = time.time()
                        handle_field_update(
                            job_url_key,
                            company_key,
                            "CL feedback",
                            st.session_state.get(cf_key, ""),
                            current_cl_feedback,
                            "✅ Cover letter feedback saved",
                        )

            st.divider()
            st.subheader("📌 Job details")
            if not show_apply_at_top:
                if job_url:
                    url_col1, url_col2 = st.columns([3, 1])
                    with url_col1:
                        st.write(f"**Job URL:** [{job_url}]({job_url})")
                    with url_col2:
                        _current_expired = expired == "TRUE"
                        st.checkbox(
                            "Expired",
                            value=_current_expired,
                            key=f"job_posting_expired_{job_key}",
                            on_change=on_checkbox_change,
                            args=(
                                job_key,
                                "Job posting expired",
                                job_url_key,
                                company_key,
                                company,
                                job_title,
                                "TRUE" if _current_expired else "FALSE",
                                selected_expired,
                            ),
                        )
                _current_applied = applied == "TRUE"
                st.checkbox(
                    "✅ Applied",
                    value=_current_applied,
                    key=f"applied_{job_key}",
                    on_change=on_checkbox_change,
                    args=(
                        job_key,
                        "Applied",
                        job_url_key,
                        company_key,
                        company,
                        job_title,
                        "TRUE" if _current_applied else "FALSE",
                        selected_applied,
                    ),
                )
            st.write(f"**Company:** {company}")
            st.write(f"**Job Title:** {job_title}")
            st.write(f"**Location:** {location}")
            if has_location_priorities and location_priority:
                st.write(f"**Location Priority:** {location_priority}")
            if fit_score != "Unknown":
                st.write(f"**Fit Score:** {fit_score}")
            if check_sustainability_enabled and "Sustainable company" in df.columns:
                if sustainable == "TRUE":
                    sustainable_icon = "✅"
                    sustainable_label = sustainable
                elif unsustainable_no_co:
                    sustainable_icon = "⚠️"
                    sustainable_label = "Missing overview (not evaluated)"
                elif (sustainable or "").strip() not in ("TRUE", "FALSE"):
                    sustainable_icon = "⚠️"
                    sustainable_label = "Missing overview (not evaluated)" if missing_co else "Unknown"
                else:
                    sustainable_icon = "❌"
                    sustainable_label = sustainable
                st.write(f"**Sustainable Company:** {sustainable_icon} {sustainable_label}")
                current_sustainable = sustainable == "TRUE"
                st.checkbox(
                    "🌱 Mark as sustainable company",
                    value=current_sustainable,
                    key=f"sustainable_company_{job_key}",
                    on_change=on_checkbox_change,
                    args=(
                        job_key,
                        "Sustainable company",
                        job_url_key,
                        company_key,
                        company,
                        job_title,
                        "TRUE" if current_sustainable else "FALSE",
                        selected_sustainable,
                    ),
                )
            st.divider()
            if job_analysis:
                analysis_col1, analysis_col2 = st.columns([3, 1])
                with analysis_col1:
                    with st.expander("Job Analysis"):
                        st.markdown(job_analysis)
                with analysis_col2:
                    st.checkbox(
                        "Bad Analysis",
                        value=has_bad_analysis,
                        key=f"bad_analysis_{job_key}",
                        on_change=on_checkbox_change,
                        args=(
                            job_key,
                            "Bad analysis",
                            job_url_key,
                            company_key,
                            company,
                            job_title,
                            "TRUE" if has_bad_analysis else "FALSE",
                            selected_bad_analysis,
                        ),
                    )

            st.divider()
            st.subheader("📋 Job Description")
            if has_job_description:
                with st.expander("View/Edit Job Description"):
                    current_jd = job_description or ""
                    jd_key = f"job_description_{job_key}"
                    jd_loaded_key = f"{jd_key}__loaded"
                    if jd_key not in st.session_state:
                        st.session_state[jd_key] = current_jd
                        st.session_state[jd_loaded_key] = current_jd
                    else:
                        last_loaded = st.session_state.get(jd_loaded_key, current_jd)
                        if st.session_state.get(jd_key, "") == last_loaded and current_jd != last_loaded:
                            st.session_state[jd_key] = current_jd
                        st.session_state[jd_loaded_key] = current_jd
                    st.text_area("Job Description", key=jd_key, height=300)
                    if st.button("💾 Save Job Description", key=f"save_job_description_{job_key}"):
                        st.session_state.expanded_job_row = job_key
                        st.session_state.last_refresh = time.time()
                        handle_field_update(
                            job_url_key,
                            company_key,
                            "Job Description",
                            st.session_state.get(jd_key, ""),
                            current_jd,
                            "✅ Job description saved!",
                        )
            else:
                if check_sustainability_enabled and sustainable == "TRUE":
                    st.error(
                        "🚨 **CRITICAL: Missing Job Description** - This sustainable company job cannot be analyzed without a job description!"
                    )
                else:
                    st.warning(
                        "⚠️ **Missing Job Description** - This job cannot be analyzed without a job description."
                    )
                st.subheader("✏️ Add Job Description")
                current_jd = job_description or ""
                jd_key = f"job_description_{job_key}"
                jd_loaded_key = f"{jd_key}__loaded"
                if jd_key not in st.session_state:
                    st.session_state[jd_key] = current_jd
                    st.session_state[jd_loaded_key] = current_jd
                else:
                    last_loaded = st.session_state.get(jd_loaded_key, current_jd)
                    if st.session_state.get(jd_key, "") == last_loaded and current_jd != last_loaded:
                        st.session_state[jd_key] = current_jd
                    st.session_state[jd_loaded_key] = current_jd
                st.text_area(
                    "Job Description",
                    key=jd_key,
                    height=300,
                    help="Paste the job description from the LinkedIn job posting here",
                )
                if st.button("💾 Save Job Description", key=f"save_job_description_missing_{job_key}"):
                    st.session_state.expanded_job_row = job_key
                    st.session_state.last_refresh = time.time()
                    handle_field_update(
                        job_url_key,
                        company_key,
                        "Job Description",
                        st.session_state.get(jd_key, ""),
                        current_jd,
                        "✅ Job description saved! The job will be analyzed in the next cycle.",
                    )

            st.divider()
            st.subheader("🏢 Company Overview")
            if company_overview:
                with st.expander("View/Edit Company Overview"):
                    current_co = company_overview
                    co_key = f"company_overview_{job_key}"
                    co_loaded_key = f"{co_key}__loaded"
                    if co_key not in st.session_state:
                        st.session_state[co_key] = current_co
                        st.session_state[co_loaded_key] = current_co
                    else:
                        last_loaded = st.session_state.get(co_loaded_key, current_co)
                        if st.session_state.get(co_key, "") == last_loaded and current_co != last_loaded:
                            st.session_state[co_key] = current_co
                        st.session_state[co_loaded_key] = current_co
                    st.text_area("Company Overview", key=co_key, height=200)
                    if st.button("💾 Save Company Overview", key=f"save_company_overview_{job_key}"):
                        st.session_state.expanded_job_row = job_key
                        st.session_state.last_refresh = time.time()
                        handle_field_update(
                            job_url_key,
                            company_key,
                            "Company overview",
                            st.session_state.get(co_key, ""),
                            current_co,
                            "✅ Company overview saved!",
                        )
            else:
                st.warning(
                    "⚠️ **Missing Company Overview** - Company overview is needed for sustainability checks and better analysis."
                )
                st.subheader("✏️ Add Company Overview")
                current_co = company_overview
                co_key = f"company_overview_{job_key}"
                co_loaded_key = f"{co_key}__loaded"
                if co_key not in st.session_state:
                    st.session_state[co_key] = current_co
                    st.session_state[co_loaded_key] = current_co
                else:
                    last_loaded = st.session_state.get(co_loaded_key, current_co)
                    if st.session_state.get(co_key, "") == last_loaded and current_co != last_loaded:
                        st.session_state[co_key] = current_co
                    st.session_state[co_loaded_key] = current_co
                st.text_area(
                    "Company Overview",
                    key=co_key,
                    height=200,
                    help="Paste the company overview/description here",
                )
                if st.button("💾 Save Company Overview", key=f"save_company_overview_missing_{job_key}"):
                    st.session_state.expanded_job_row = job_key
                    st.session_state.last_refresh = time.time()
                    handle_field_update(
                        job_url_key,
                        company_key,
                        "Company overview",
                        st.session_state.get(co_key, ""),
                        current_co,
                        "✅ Company overview saved!",
                    )

    # Sticky pagination
    if total_items > 0:
        def _go_prev():
            st.session_state.page_index = max(0, st.session_state.page_index - 1)
            st.session_state.page_jump = st.session_state.page_index + 1

        def _go_next():
            st.session_state.page_index = min(total_pages - 1, st.session_state.page_index + 1)
            st.session_state.page_jump = st.session_state.page_index + 1

        def _on_page_jump_change():
            try:
                desired = int(st.session_state.page_jump)
            except Exception:
                desired = 1
            desired = max(1, min(desired, total_pages))
            st.session_state.page_index = desired - 1
            st.session_state.page_jump = desired

        with st.container():
            st.markdown('<div class="pagination-marker-unique"></div>', unsafe_allow_html=True)
            pager_cols = st.columns([1.1, 3.8, 1.1])
            with pager_cols[0]:
                st.button(
                    "◀ Prev",
                    key="pager_prev",
                    on_click=_go_prev,
                    disabled=(st.session_state.page_index <= 0),
                    use_container_width=True,
                )
            with pager_cols[1]:
                mid_cols = st.columns([3.4, 0.6])
                with mid_cols[0]:
                    st.markdown(
                        f'<p class="pager-text">Page <b>{st.session_state.page_index + 1}</b> / <b>{total_pages}</b>'
                        f' · Showing <b>{start_idx + 1}</b>-<b>{end_idx}</b> of <b>{total_items}</b></p>',
                        unsafe_allow_html=True,
                    )
                with mid_cols[1]:
                    st.number_input(
                        "Page",
                        min_value=1,
                        max_value=total_pages,
                        step=1,
                        key="page_jump",
                        on_change=_on_page_jump_change,
                        label_visibility="collapsed",
                        format="%d",
                    )
            with pager_cols[2]:
                st.button(
                    "Next ▶",
                    key="pager_next",
                    on_click=_go_next,
                    disabled=(st.session_state.page_index >= total_pages - 1),
                    use_container_width=True,
                )

    # Undo popup
    if st.session_state.undo_stack and st.session_state.undo_stack_timestamp is not None:
        elapsed_time = time.time() - st.session_state.undo_stack_timestamp
        if elapsed_time >= UNDO_POPUP_TIMEOUT:
            st.session_state.undo_stack.clear()
            st.session_state.undo_stack_timestamp = None
            st.rerun()

    if st.session_state.undo_stack:
        job_key, field_name, old_value, job_url_key, company_key, company, job_title = (
            st.session_state.undo_stack[-1]
        )
        field_display = {
            "Applied": "Applied",
            "Job posting expired": "Expired",
            "Bad analysis": "Bad Analysis",
            "Sustainable company": "Sustainable",
        }.get(field_name, field_name)
        remaining_time = UNDO_POPUP_TIMEOUT
        if st.session_state.undo_stack_timestamp is not None:
            elapsed = time.time() - st.session_state.undo_stack_timestamp
            remaining_time = max(0, UNDO_POPUP_TIMEOUT - elapsed)

        with st.container():
            st.markdown('<div class="undo-marker-unique"></div>', unsafe_allow_html=True)
            st.markdown(f'<div class="undo-text">ℹ️ Job hidden</div>', unsafe_allow_html=True)
            st.markdown(
                f'<div class="undo-subtext"><b>{company}</b> - {job_title}<br/>Marked as {field_display}</div>',
                unsafe_allow_html=True,
            )
            st.button("↩️ Undo", key="undo_button_fixed", on_click=handle_undo, use_container_width=True)

            auto_hide_button_key = f"undo_auto_hide_{int(st.session_state.undo_stack_timestamp or 0)}"

            def clear_undo_on_timeout():
                if st.session_state.undo_stack:
                    st.session_state.undo_stack.clear()
                    st.session_state.undo_stack_timestamp = None

            with st.container():
                st.button(
                    "",
                    key=auto_hide_button_key,
                    on_click=clear_undo_on_timeout,
                    help="",
                    use_container_width=False,
                )
                st.markdown(
                    f"""
                    <style>
                    div[data-testid="stVerticalBlock"]:has(button[data-testid*="{auto_hide_button_key}"]) {{
                        display: none !important;
                    }}
                    button[data-testid*="{auto_hide_button_key}"] {{
                        display: none !important;
                        visibility: hidden !important;
                        position: absolute !important;
                        left: -9999px !important;
                        width: 0 !important;
                        height: 0 !important;
                        padding: 0 !important;
                        margin: 0 !important;
                    }}
                    </style>
                    """,
                    unsafe_allow_html=True,
                )
                st.components.v1.html(
                    f"""
                <script>
                (function() {{
                    const timeoutMs = {int(remaining_time * 1000)};
                    const buttonKey = '{auto_hide_button_key}';
                    setTimeout(function() {{
                        let triggered = false;
                        const allButtons = document.querySelectorAll('button');
                        for (let btn of allButtons) {{
                            const testId = btn.getAttribute('data-testid') || '';
                            if (testId.includes(buttonKey)) {{
                                btn.click();
                                triggered = true;
                                break;
                            }}
                        }}
                        if (!triggered && window.parent) {{
                            try {{
                                window.parent.postMessage({{ type: 'streamlit:rerun' }}, '*');
                                triggered = true;
                            }} catch(e) {{}}
                        }}
                        if (!triggered) {{ window.location.reload(); }}
                    }}, timeoutMs);
                }})();
                </script>
                """,
                    height=0,
                )
