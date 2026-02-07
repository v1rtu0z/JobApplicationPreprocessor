"""Activity log view and helpers."""
import time
import streamlit as st
from pathlib import Path

from .constants import ACTIVITY_LOG_PATH, ACTIVITY_LOG_TAIL_LINES, ACTIVITY_AUTO_REFRESH_SEC


def _activity_log_level(line: str) -> str:
    """Classify a log line as error, warning, section, or info for styling."""
    t = line.strip()
    if any(x in line for x in ("Error", "error:", "CRITICAL", "Traceback", "failed", "Failed", "Exception")):
        return "error"
    if any(x in line for x in ("Warning", "WARNING", "⚠️", "Skipping", "Skipped")):
        return "warning"
    if not t:
        return "section"
    if len(t) > 2 and (
        set(t.replace(" ", "")) <= {">", "=", "-", "!", "*"}
        or "Phase" in line
        or "COLLECTION" in line
        or "ANALYSIS" in line
        or "PROCESSING" in line
        or "SUSTAINABILITY" in line
        or "BULK" in line
    ):
        return "section"
    return "info"


@st.cache_data(ttl=2)  # Short TTL so Activity view sees new lines quickly
def _read_activity_log_tail(max_lines: int = ACTIVITY_LOG_TAIL_LINES) -> list[str]:
    """Read last max_lines from activity log."""
    if not ACTIVITY_LOG_PATH.exists():
        return []
    try:
        with open(ACTIVITY_LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return lines[-max_lines:] if len(lines) > max_lines else lines
    except (OSError, IOError):
        return []


def render_activity_view() -> None:
    """Render the Activity log view."""
    st.title("Activity log")
    st.caption("Logs from the main application (`local_data/activity.log`).")

    lines = _read_activity_log_tail()
    if not lines:
        st.info("No activity yet. Run the main application to see logs here.")
        return

    st.markdown(
        """
        <style>
        .log-card { border-radius: 10px; padding: 10px 14px; margin: 6px 0; font-family: monospace; font-size: 0.9rem; }
        .log-card.log-error   { border-left: 4px solid #dc3545; background-color: rgba(220, 53, 69, 0.12); }
        .log-card.log-warning { border-left: 4px solid #fd7e14; background-color: rgba(253, 126, 20, 0.12); }
        .log-card.log-section { border-left: 4px solid #6c757d; background-color: rgba(108, 117, 125, 0.12); }
        .log-card.log-info    { border-left: 4px solid #0d6efd; background-color: rgba(13, 110, 253, 0.08); }
        .log-preview { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        if st.button("Refresh", key="activity_refresh", use_container_width=True):
            _read_activity_log_tail.clear()
            st.rerun()
    with col2:
        auto = st.checkbox("Auto-refresh", value=True, key="activity_auto_refresh")
    with col3:
        level_filter = st.multiselect(
            "Show levels",
            ["error", "warning", "section", "info"],
            default=["error", "warning", "section", "info"],
            key="activity_level_filter",
        )

    shown = 0
    for line in reversed(lines):
        text = line.rstrip("\n\r")
        if not text:
            continue
        level = _activity_log_level(text)
        if level_filter and level not in level_filter:
            continue
        preview = text[:120] + ("..." if len(text) > 120 else "")
        preview_esc = (
            preview.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        )
        full_esc = (
            text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        )
        st.markdown(
            f'<div class="log-card log-{level}"><span class="log-preview" title="{full_esc[:200]}">{preview_esc}</span></div>',
            unsafe_allow_html=True,
        )
        shown += 1

    st.caption(f"Showing {shown} of last {len(lines)} lines (tail size: {ACTIVITY_LOG_TAIL_LINES}).")
    if auto:
        time.sleep(ACTIVITY_AUTO_REFRESH_SEC)
        st.rerun()
