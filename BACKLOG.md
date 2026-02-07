# Job Application Preprocessor – Backlog

Prioritized backlog. Done items (Settings page, Additional details field, Sustainability warning) have been removed.

---

## 🔴 High Priority

### 1. Apify: Process Each Response Fully Before Making a New Request

Implement request queuing so each Apify response is fully processed before starting the next request. Reduces risk of hitting rate limits and spreads usage across the month.

- Request queue for Apify calls
- Process responses sequentially (or controlled concurrency)
- Retry with exponential backoff; optional usage tracking and throttling
- Config for batch sizes and delays; logging for monitoring

**Notes:** Review usage in pipeline/ and utils/; consider `queue.Queue` or async; store usage in SQLite/JSON; optional dashboard metric.

---

### 2. OOP Refactor – Data-Source Agnostic Architecture

Refactor to OOP and make the app data-source agnostic (Apify, LinkedIn direct, other boards) without rewriting core logic.

- **Job** and **Company** classes with clear encapsulation
- **DataSource** interface; **ApifyDataSource**, **LinkedInDataSource** implementations
- **JobRepository** / DAO for storage
- Service layer (e.g. JobAnalysisService, ResumeGenerationService)
- Unit tests for core classes; update docs

**Notes:** Start with Job/Company and data source extraction; use DI and optionally a factory; refactor incrementally.

---

## 🟡 Medium Priority

### 3. Automatic Filter Adjustment When Good Matches Are Found

When a configurable number of “Good fit” / “Very good fit” jobs are found, adjust filters (e.g. location, keywords) to favor similar opportunities.

- Configurable threshold
- Logic to adjust filters from good-fit patterns; logging and optional revert
- Dashboard indicator when auto-adjustment ran

---

### 4. Keyword Search Improvements with Sustainability

Integrate sustainability into keyword filtering: weighted positive keywords, negative keywords for unsustainable industries, optional use of company overview.

- Sustainability keyword lists in filtering (e.g. extend pipeline/filtering or equivalent)
- Config in `job_preferences.yaml`; dashboard display of sustainability keyword matches

---

### 5. Resume from Text (Additional Details as Starting Point)

Let “Additional details” (or a dedicated text block) act as a resume starting point: parse text → LLM to structured resume JSON → generate/refine resume.

- Text parsing and LLM prompt for text-to-resume
- Validation against resume schema; UI option (e.g. in setup) to “Generate resume from text”

**Depends on:** Additional details field (done).

---

### 6. UI: Buy Me a Coffee, Feedback Link, Activity Page Improvements

- **Buy Me a Coffee** and **Feedback** links in sidebar or footer (URLs from `.env` or YAML)
- **Activity page:** filters by log level, search, export logs, clearer layout, optional auto-scroll / collapsible sections

---

### 7. “Add to Startup” Facilitation
Make it easy to add the app to system startup: script that detects OS and creates the right entry (Windows Startup folder / registry, macOS LaunchAgent, Linux `~/.config/autostart` or systemd user service). Optional UI toggle in setup/dashboard; doc for manual fallback.

---

## 🟢 Low Priority

### 8. Application Name and Branding

Choose a memorable name; update README, docs, UI; optionally rename repo and add logo/favicon.

---

### 9. Dockerization

Dockerfile (multi-stage), docker-compose, volume for `local_data/`, env handling. Document run and deploy.

---

### 10. Build Process for Windows / macOS / Linux

Build executables (e.g. PyInstaller) and installers per OS; GitHub Actions for builds; document release and, if needed, code signing.

---

## Recently Completed (removed from backlog)

- **Settings page** – Dashboard Settings with .env, Keywords, Locations, Sustainability, Search params, General, Import/Export, Reset
- **Additional details field** – Setup + Settings + use in `api_methods.py` prompts
- **Sustainability warning** – Helper text in Dashboard Settings and setup page advising caution when prioritizing financial stability

---

**Last updated:** February 2026
