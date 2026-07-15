"""Dashboard CSS and inline JS for layout (undo popup, sticky pager)."""

CUSTOM_CSS = """
<style>
    :root {
        /* JS will keep these in sync with stMain */
        --jab-main-left: 0px;
        --jab-main-width: 100vw;
    }

    /* Undo toast — fixed bottom-right (scoped to nested container only) */
    div[data-testid="stVerticalBlock"] div[data-testid="stVerticalBlock"]:has(.undo-marker-unique) {
        position: fixed !important;
        bottom: 24px !important;
        right: 24px !important;
        z-index: 10000 !important;
        width: min(360px, calc(100vw - 48px)) !important;
        background: linear-gradient(145deg, #1e2229 0%, #16191f 100%) !important;
        padding: 0 !important;
        border-radius: 14px !important;
        border: 1px solid #3d444d !important;
        box-shadow: 0 12px 32px rgba(0, 0, 0, 0.45), 0 0 0 1px rgba(255, 255, 255, 0.04) inset !important;
        overflow: hidden !important;
        gap: 8px !important;
        display: flex !important;
        flex-direction: column !important;
    }

    div[data-testid="stVerticalBlock"] div[data-testid="stVerticalBlock"]:has(.undo-marker-unique) > div {
        display: flex !important;
        flex-direction: column !important;
        gap: 10px !important;
    }

    div[data-testid="stVerticalBlock"] div[data-testid="stVerticalBlock"]:has(.undo-marker-unique) > div > * {
        margin-top: 0 !important;
        margin-bottom: 0 !important;
    }

    div[data-testid="stVerticalBlock"] div[data-testid="stVerticalBlock"]:has(.undo-marker-unique) [data-testid="stMarkdown"] {
        margin: 0 !important;
        padding: 0 !important;
        flex-shrink: 0 !important;
    }

    div[data-testid="stVerticalBlock"] div[data-testid="stVerticalBlock"]:has(.undo-marker-unique) [data-testid="stElementContainer"]:has(button) {
        padding: 0 14px 10px 14px !important;
        margin: 10px 0 0 0 !important;
        flex-shrink: 0 !important;
    }

    div[data-testid="stVerticalBlock"] div[data-testid="stVerticalBlock"]:has(.undo-marker-unique) [data-testid="stMarkdown"]:has(.jab-undo-progress-track) {
        margin: 0 !important;
        padding: 0 !important;
        order: 99 !important;
    }

    div[data-testid="stVerticalBlock"] div[data-testid="stVerticalBlock"]:has(.undo-marker-unique) [data-testid="stElementContainer"]:has(button) {
        order: 2 !important;
    }

    div[data-testid="stVerticalBlock"] div[data-testid="stVerticalBlock"]:has(.undo-marker-unique) [data-testid="stMarkdown"]:has(.jab-undo-card) {
        order: 1 !important;
    }

    .undo-marker-unique {
        display: none !important;
    }

    .jab-undo-card {
        padding: 16px 16px 0 16px;
    }

    .jab-undo-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 8px;
    }

    .jab-undo-title {
        color: #e6edf3;
        font-weight: 600;
        font-size: 0.95rem;
        letter-spacing: 0.01em;
    }

    .jab-undo-timer {
        color: #8b949e;
        font-size: 0.75rem;
        font-weight: 500;
        font-variant-numeric: tabular-nums;
        background: #21262d;
        border: 1px solid #30363d;
        border-radius: 999px;
        padding: 2px 8px;
        flex-shrink: 0;
    }

    .jab-undo-job {
        color: #c9d1d9;
        font-size: 0.88rem;
        line-height: 1.35;
        margin: 0 0 4px 0;
        word-break: break-word;
    }

    .jab-undo-sep {
        color: #6e7681;
        margin: 0 0.35em;
    }

    .jab-undo-meta {
        color: #8b949e;
        font-size: 0.8rem;
        margin: 0 0 4px 0;
    }

    .jab-undo-meta strong {
        color: #b1bac4;
        font-weight: 600;
    }

    .jab-undo-progress-track {
        height: 4px;
        background: #21262d;
        overflow: hidden;
        border-radius: 0 0 13px 13px;
    }

    .jab-undo-progress-bar {
        height: 100%;
        background: linear-gradient(90deg, #388bfd, #58a6ff);
        transition: width 0.2s ease;
    }

    div[data-testid="stVerticalBlock"] div[data-testid="stVerticalBlock"]:has(.undo-marker-unique) button[kind="secondary"] {
        width: 100% !important;
        background-color: transparent !important;
        border: 1px solid #484f58 !important;
        color: #e6edf3 !important;
        border-radius: 8px !important;
        min-height: 2rem !important;
        margin-top: 0 !important;
        font-size: 0.82rem !important;
        font-weight: 600 !important;
        padding: 0.3rem 0.75rem !important;
        box-shadow: none !important;
    }

    div[data-testid="stVerticalBlock"] div[data-testid="stVerticalBlock"]:has(.undo-marker-unique) button[kind="secondary"]:hover {
        background-color: #30363d !important;
        border-color: #8b949e !important;
    }
    /* Ensure the main application container is NEVER caught by undo toast positioning */
    div[data-testid="stMain"] > div[data-testid="stVerticalBlock"] {
        position: relative !important;
        bottom: auto !important;
        right: auto !important;
        width: 100% !important;
        z-index: 1 !important;
        box-shadow: none !important;
        background-color: transparent !important;
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

    /*
     * Unify default Streamlit button shape (radius + height) in main + sidebar.
     * Content-width buttons looked pill-like vs use_container_width rows.
     */
    [data-testid="stMain"] button[kind="secondary"],
    [data-testid="stMain"] button[kind="primary"],
    [data-testid="stMain"] button[kind="tertiary"],
    [data-testid="stSidebar"] button[kind="secondary"],
    [data-testid="stSidebar"] button[kind="primary"],
    [data-testid="stSidebar"] button[kind="tertiary"] {
        border-radius: 0.5rem !important;
        min-height: 2.5rem !important;
    }

    /* Sticky bottom pagination bar */
    div[data-testid="stVerticalBlock"] div[data-testid="stVerticalBlock"]:has(.pagination-marker-unique) {
        position: fixed !important;
        /* Keep aligned with stMain as sidebar opens/closes */
        left: var(--jab-main-left) !important;
        width: var(--jab-main-width) !important;
        transition: left 140ms ease, width 140ms ease !important;
        right: auto !important;
        bottom: 0 !important;
        z-index: 9999 !important;
        background-color: rgba(26, 28, 36, 0.98) !important;
        border-top: 1px solid #3d444d !important;
        padding: 10px 16px !important;
        box-shadow: 0 -8px 24px rgba(0,0,0,0.4) !important;
    }

    /* Add bottom space so pager doesn't cover content */
    div[data-testid="stMain"] {
        padding-bottom: 92px !important;
    }

    /* Compact pager typography */
    .pager-text {
        color: #c9d1d9 !important;
        font-size: 0.9rem !important;
        line-height: 1.2 !important;
        margin: 0 !important;
        padding: 0 !important;
    }

    /* Pager buttons: match existing dark theme */
    div[data-testid="stVerticalBlock"]:has(.pagination-marker-unique) button {
        background-color: #21262d !important;
        border: 1px solid #3d444d !important;
        color: #c9d1d9 !important;
        padding: 0.35rem 0.6rem !important;
        border-radius: 0.5rem !important;
        min-height: 2.5rem !important;
    }

    /* Sidebar support/feedback: pill-style links (target=_self so mailto opens mail client, not a blank tab) */
    .jab-sidebar-link {
        display: inline-block !important;
        font-size: 0.9rem !important;
        color: #c9d1d9 !important;
        text-decoration: none !important;
        background: #21262d !important;
        border: 1px solid #3d444d !important;
        border-radius: 999px !important;
        padding: 0.5rem 0.95rem !important;
        margin: 0.2rem 0.25rem 0.2rem 0 !important;
        transition: background 0.15s, border-color 0.15s !important;
    }
    .jab-sidebar-link:hover {
        background: #30363d !important;
        border-color: #8b949e !important;
        color: #e6edf3 !important;
    }

    /* Job card fetch date — right-aligned on collapsed expander row */
    .jab-job-date-anchor {
        height: 0;
        overflow: visible;
        position: relative;
        z-index: 2;
        pointer-events: none;
    }

    .jab-job-date-anchor span {
        position: absolute;
        right: 2.75rem;
        top: 0.72rem;
        color: #8b949e;
        font-size: 0.78rem;
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
    }

    .jab-job-date-anchor + div[data-testid="stExpander"] {
        margin-top: 0 !important;
    }

    .jab-job-date-anchor + div[data-testid="stExpander"] details summary {
        padding-right: 7.5rem !important;
    }
</style>
"""

PAGER_JS = """
<script>
(function() {
  function updateVars() {
    try {
      const doc = window.parent && window.parent.document ? window.parent.document : document;
      const root = doc.documentElement;
      const main = doc.querySelector('[data-testid="stMain"]');
      const sidebar = doc.querySelector('[data-testid="stSidebar"]');

      if (main) {
        const r = main.getBoundingClientRect();
        root.style.setProperty('--jab-main-left', r.left + 'px');
        root.style.setProperty('--jab-main-width', r.width + 'px');
        return;
      }

      let sidebarWidth = 0;
      if (sidebar) {
        const expanded = sidebar.getAttribute('aria-expanded');
        const sr = sidebar.getBoundingClientRect();
        sidebarWidth = (expanded === 'false') ? 0 : sr.width;
      }
      root.style.setProperty('--jab-main-left', sidebarWidth + 'px');
      root.style.setProperty('--jab-main-width', (window.innerWidth - sidebarWidth) + 'px');
    } catch (e) {}
  }

  updateVars();
  window.addEventListener('resize', updateVars);

  try {
    const doc = window.parent && window.parent.document ? window.parent.document : document;
    const main = doc.querySelector('[data-testid="stMain"]');
    const sidebar = doc.querySelector('[data-testid="stSidebar"]');
    if ('ResizeObserver' in window) {
      const ro = new ResizeObserver(updateVars);
      if (main) ro.observe(main);
      if (sidebar) ro.observe(sidebar);
    }
  } catch (e) {}

  setInterval(updateVars, 300);
})();
</script>
"""
