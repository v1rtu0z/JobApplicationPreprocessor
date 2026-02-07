"""Dashboard CSS and inline JS for layout (undo popup, sticky pager)."""

CUSTOM_CSS = """
<style>
    :root {
        /* JS will keep these in sync with stMain */
        --jab-main-left: 0px;
        --jab-main-width: 100vw;
    }

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
