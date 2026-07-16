# Job Application Preprocessor – Backlog

Prioritized backlog. Completed items are moved to "Recently completed" below.

---

## 🟡 Medium Priority

### 1. "Add to Startup" Facilitation

Make it easy to add the app to system startup: script that detects OS and creates the right entry (Windows Startup folder / registry, macOS LaunchAgent, Linux `~/.config/autostart` or systemd user service). Optional UI toggle in setup/dashboard; doc for manual fallback.

---

## 🟢 Low Priority

### 2. Application Name and Branding

Choose a memorable name; update README, docs, UI; optionally rename repo and add logo/favicon.

### 3. Dockerization

Dockerfile (multi-stage), docker-compose, volume for `local_data/`, env handling. Document run and deploy.

### 4. Build Process for Windows / macOS / Linux

Build executables (e.g. PyInstaller) and installers per OS; GitHub Actions for builds; document release and, if needed, code signing.

---

## Recently completed

- **Remove legacy spreadsheet interface** – Pipeline/`local_storage` spreadsheet aliases were already gone; this pass finished `SHEET_HEADER`→`JOB_COLUMNS`, `get_sustainability_from_sheet`→`get_sustainability_from_db`, removed dead `column_index_to_letter` / unused `update_cell` / `append_rows` / `update_record_by_fields`, and cleaned core service `sheet` locals. Kept intentional DB APIs: `get_all_records()` (no-`_id` view), `add_jobs_from_rows()`, `sort_by()`.
- **Hide Jobs filters on Activity/Settings** – View radio no longer forces `index=0` on every rerun (was resetting to Jobs during Activity auto-refresh and flashing sidebar filters). Jobs sidebar filters/stats now render into an `st.sidebar.empty()` placeholder created early in `app.py`, so switching to Activity/Settings clears them instantly instead of lingering for a second or two until the (slower) other view's script run finishes.
- **Telegram test message** – Settings → App config: “Send Telegram test message” ping (no dummy job).
- **USE_LOCAL_STORAGE cleanup** – Toggle already gone from setup/settings/example; Settings `.env` writer strips leftover key.
- **Editable local LLM prompts** – Settings → Prompts; overrides in `job_preferences.yaml`.
- **Keyword search improvements with sustainability** – Sustainability keyword lists in filtering: negative keywords (substring match in title, company, location, optional company overview) mark jobs as Very poor fit and skip at collection; positive matches stored for display. Config: `sustainability_criteria.positive`, `negative`, and `use_company_overview_for_sustainability_keywords` in `job_preferences.yaml`; new column "Sustainability keyword matches"; dashboard shows matches in job details when CHECK_SUSTAINABILITY is on.
- **Settings page** – Dashboard Settings with .env, Keywords, Locations, Sustainability, Search params, General, Import/Export, Reset
- **Additional details field** – Setup + Settings + use in `api_methods.py` prompts
- **Sustainability warning** – Helper text in Dashboard Settings and setup page advising caution when prioritizing financial stability
- **Resume from text** – Generate resume_data.json from Additional details (text) via LLM; validation for personal.full_name; "Generate resume from text" in setup and Dashboard Settings
- **Automatic filter adjustment** – When a configurable number of Good fit / Very good fit jobs are found, location priorities are updated from their locations. Config: `auto_filter_adjustment.enabled` and `good_fit_threshold` in job_preferences.yaml; Dashboard Settings shows when it ran and offers "Revert last auto-adjustment"
- **OOP refactor (data-source agnostic)** – Job and Company models; DataSource interface with ApifyDataSource and LinkedInDataSource; JobRepository; JobAnalysisService and ResumeGenerationService; unit tests; collection wired to use data sources

---

*Last updated: July 2026*
