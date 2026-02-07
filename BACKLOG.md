# Job Application Preprocessor – Backlog

Prioritized backlog. Completed items are moved to "Recently completed" below.

---

## 🟡 Medium Priority

### 1. "Add to Startup" Facilitation

Make it easy to add the app to system startup: script that detects OS and creates the right entry (Windows Startup folder / registry, macOS LaunchAgent, Linux `~/.config/autostart` or systemd user service). Optional UI toggle in setup/dashboard; doc for manual fallback.

### 2. Dashboard: Hide Filters on Activity View

When navigating Jobs → Activity, the Jobs sidebar filters (and stats) should not appear on the Activity page. Currently they persist or fade/reactivate in a loop. Settings does not show filters (correct). Fix so Activity behaves like Settings: filters hidden on Activity. Avoid breaking the Jobs UI (no container/placeholder approach that broke layout).

---

## 🟢 Low Priority

### 3. Application Name and Branding

Choose a memorable name; update README, docs, UI; optionally rename repo and add logo/favicon.

### 4. Dockerization

Dockerfile (multi-stage), docker-compose, volume for `local_data/`, env handling. Document run and deploy.

### 5. Build Process for Windows / macOS / Linux

Build executables (e.g. PyInstaller) and installers per OS; GitHub Actions for builds; document release and, if needed, code signing.

---

## Recently completed

- **Keyword search improvements with sustainability** – Sustainability keyword lists in filtering: negative keywords (substring match in title, company, location, optional company overview) mark jobs as Very poor fit and skip at collection; positive matches stored for display. Config: `sustainability_criteria.positive`, `negative`, and `use_company_overview_for_sustainability_keywords` in `job_preferences.yaml`; new column "Sustainability keyword matches"; dashboard shows matches in job details when CHECK_SUSTAINABILITY is on.
- **Settings page** – Dashboard Settings with .env, Keywords, Locations, Sustainability, Search params, General, Import/Export, Reset
- **Additional details field** – Setup + Settings + use in `api_methods.py` prompts
- **Sustainability warning** – Helper text in Dashboard Settings and setup page advising caution when prioritizing financial stability
- **Resume from text** – Generate resume_data.json from Additional details (text) via LLM; validation for personal.full_name; "Generate resume from text" in setup and Dashboard Settings
- **Automatic filter adjustment** – When a configurable number of Good fit / Very good fit jobs are found, location priorities are updated from their locations. Config: `auto_filter_adjustment.enabled` and `good_fit_threshold` in job_preferences.yaml; Dashboard Settings shows when it ran and offers "Revert last auto-adjustment"
- **OOP refactor (data-source agnostic)** – Job and Company models; DataSource interface with ApifyDataSource and LinkedInDataSource; JobRepository; JobAnalysisService and ResumeGenerationService; unit tests; collection wired to use data sources

---

*Last updated: February 2026*
