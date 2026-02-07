"""Dashboard app: page config, view routing, and Jobs view entry."""
import os
import time

import streamlit as st

from setup_server import get_app_root

from .activity import render_activity_view
from .data import load_job_data
from .jobs_view import render_jobs_view
from .settings import render_settings_view
from .styles import CUSTOM_CSS, PAGER_JS


def main() -> None:
    """Run the dashboard: route to Jobs, Activity, or Settings."""
    st.set_page_config(
        page_title="Job Application Dashboard",
        page_icon="💼",
        layout="wide",
    )
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    if "last_refresh" not in st.session_state:
        st.session_state.last_refresh = time.time()

    try:
        os.chdir(get_app_root())
    except OSError:
        pass

    view = st.sidebar.radio(
        "View",
        ["Jobs", "Activity", "Settings"],
        index=0,
        key="dashboard_view",
    )
    st.sidebar.markdown("---")
    st.sidebar.markdown(
        '<p style="margin:0.5rem 0 0 0;">'
        '<a class="jab-sidebar-link" target="_blank" rel="noopener noreferrer" href="https://buymeacoffee.com/v1rtu0z96">☕ Buy Me a Coffee</a> '
        '<a class="jab-sidebar-link" target="_self" href="mailto:nikolamandic1996@gmail.com">✉ Feedback</a>'
        '</p>',
        unsafe_allow_html=True,
    )

    if view == "Activity":
        render_activity_view()
        return
    if view == "Settings":
        render_settings_view()
        return

    st.title("💼 Job Application Dashboard")
    st.components.v1.html(PAGER_JS, height=0)

    if "df" not in st.session_state:
        df, error = load_job_data()
        if error:
            st.error(error)
            return
        st.session_state.df = df

    render_jobs_view()
