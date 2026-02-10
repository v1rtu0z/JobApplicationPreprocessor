# Job Application Preprocessor – Backlog

Prioritized backlog. Completed items are moved to "Recently completed" below.

---

## 🟡 Medium Priority

### 1. Remove legacy spreadsheet interface; use database-only naming and APIs

**Goal:** Drop spreadsheet terminology and compatibility shims. The app already uses only the SQLite `JobDatabase` (no Google Sheets path). Standardize on database naming, remove dead `USE_LOCAL_STORAGE` config, and rely on `JobDatabase`’s native APIs where possible.

**Findings from codebase:**

- **Storage:** `utils/storage.py` – `setup_spreadsheet()` is a legacy alias for `setup_database()`; `get_existing_jobs()` is an alias for `get_existing_job_keys()`; `get_column_index(job_store, column_name)` exists only to support the old `sheet.sort((col_index, 'des'), …)` style (1-based index). Pipeline and all callers already use a single SQLite store; no branching on spreadsheet vs DB.
- **Runner:** `pipeline/runner.py` – Imports `setup_spreadsheet` and `get_column_index`; variable named `sheet` (actually the DB); ends cycle with `sheet.sort((get_column_index(sheet, 'Fit score enum'), 'des'), (get_column_index(sheet, 'Location Priority'), 'asc'))`. Should use `setup_database`, rename `sheet` → `db` (or `job_store`), and call `db.sort_by([('Fit score enum', False), ('Location Priority', True)])` instead.
- **Pipeline modules** (all use `sheet` and/or `sheet.get_all_records()`, `sheet.update_job_by_key()`, `sheet.append_rows()`): `pipeline/collection.py`, `pipeline/analysis.py`, `pipeline/resumes.py`, `pipeline/bulk_ops.py`, `pipeline/validation.py`, `pipeline/filtering.py`, `pipeline/auto_filter_adjustment.py`, `pipeline/logging_dashboard.py`; also `utils/sustainability.py`. Rename parameter/variable `sheet` → `db` (or `job_store`) throughout.
- **local_storage.py (`JobDatabase`):**
  - **Keep (native or widely used):** `get_all_jobs()`, `get_all_records()` (thin wrapper dropping `_id`), `add_jobs()`, `add_jobs_from_rows()`, `append_rows()` (alias for `add_jobs_from_rows`), `update_job_by_key()`, `bulk_update_by_key()`, `sort_by()`.
  - **Remove or deprecate (legacy/spreadsheet compatibility):** `get_column_index()` (0-based column index), `row_values(row)` (1-based row), `update_cell(row, col, value)` (1-based), `batch_update(updates)` (A1 notation, gspread compat), `sort(*sort_specs)` with `(col_index, 'asc'/'des')` (replace all call sites with `sort_by([(col_name, ascending), …])`), `header` property (if unused), `LocalSheet = JobDatabase` alias.
- **utils/storage.py:** Remove `setup_spreadsheet` and `get_existing_jobs`; remove `get_column_index` once runner (and any other caller) uses `sort_by`; update docstrings that refer to “sheet”.
- **utils/__init__.py:** Remove exports for `setup_spreadsheet`, `get_existing_jobs`, and `get_column_index` when those are removed.
- **Config and UI:** `USE_LOCAL_STORAGE` is still in `.env.example`, `setup_server.py` (setup page checkbox “Use local storage”), and `dashboard/settings.py` (Settings .env form and `preferred_order`). The app never branches on it—storage is always local SQLite. Remove the option: drop the checkbox and the env key (or keep key defaulted to `true` for backward compat and stop showing the toggle); update `.env.example` so “Storage” section states that storage is always local SQLite and remove “CSV files” / “Google Sheets/Drive” wording; remove or shorten the “Google Cloud Configuration (Required only if USE_LOCAL_STORAGE=false)” section.
- **Dashboard:** `dashboard/data.py` already uses `JobDatabase` and `get_all_records()`; no spreadsheet path. Only naming/docs may need a quick pass.
- **Scripts and tests:** `test_co_crawl.py` uses variable `sheet` and `get_all_records`; align with `db` and same APIs. `bulk_populate_descriptions.py`, `populate_company_overviews.py`, `test_jd_crawl.py`, `test_linkedin_direct.py` already use `JobDatabase`/`db`; confirm they use only the APIs we keep.

**Checklist of changes:**

1. **utils/storage.py** – Remove `setup_spreadsheet`, `get_existing_jobs`, `get_column_index`; update docstrings.
2. **utils/__init__.py** – Remove those three from imports and `__all__`.
3. **pipeline/runner.py** – Use `setup_database`; rename `sheet` → `db`; replace sort call with `db.sort_by([('Fit score enum', False), ('Location Priority', True)])`; pass `db` through.
4. **pipeline/** (collection, analysis, resumes, bulk_ops, validation, filtering, auto_filter_adjustment, logging_dashboard) – Rename `sheet` → `db` (or `job_store`) in parameters and locals.
5. **utils/sustainability.py** – Rename `sheet` → `db`.
6. **local_storage.py** – Remove legacy methods: `get_column_index`, `row_values`, `update_cell`, `batch_update`, `sort(*sort_specs)`, `header` (if unused), `LocalSheet` alias; keep `sort_by`, `get_all_records`, `append_rows` as above.
7. **.env.example** – Storage section: “always local SQLite”; remove USE_LOCAL_STORAGE and Google Sheets/CSV wording; trim Google Cloud section.
8. **setup_server.py** – Remove “Use local storage” checkbox and USE_LOCAL_STORAGE from form/output.
9. **dashboard/settings.py** – Remove “Use local storage” from .env tab and from `preferred_order`; stop writing USE_LOCAL_STORAGE.
10. **Tests/scripts** – test_co_crawl.py: `sheet` → `db`; ensure all use only retained APIs.

### 2. "Add to Startup" Facilitation

Make it easy to add the app to system startup: script that detects OS and creates the right entry (Windows Startup folder / registry, macOS LaunchAgent, Linux `~/.config/autostart` or systemd user service). Optional UI toggle in setup/dashboard; doc for manual fallback.

### 3. Dashboard: Hide Filters on Activity View

When navigating Jobs → Activity, the Jobs sidebar filters (and stats) should not appear on the Activity page. Currently they persist or fade/reactivate in a loop. Settings does not show filters (correct). Fix so Activity behaves like Settings: filters hidden on Activity. Avoid breaking the Jobs UI (no container/placeholder approach that broke layout).

---

## 🟢 Low Priority

### 4. Application Name and Branding

Choose a memorable name; update README, docs, UI; optionally rename repo and add logo/favicon.

### 5. Dockerization

Dockerfile (multi-stage), docker-compose, volume for `local_data/`, env handling. Document run and deploy.

### 6. Build Process for Windows / macOS / Linux

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
