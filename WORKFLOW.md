# How the pipeline works

This document describes the runtime workflow of the job application preprocessor: how jobs move
from "found on LinkedIn via Apify" to "tailored resume + cover letter delivered on Telegram."

For setup instructions see [`setup_guide.md`](setup_guide.md). For planned/future work see
[`BACKLOG.md`](BACKLOG.md).

## System overview

```mermaid
flowchart LR
    subgraph Setup
        A[First run] --> B["setup_server.py<br/>local Flask wizard"]
        B --> C[".env, resume_data.json,<br/>job_preferences.yaml,<br/>additional_details.txt"]
    end

    C --> D["main.py → pipeline/runner.main()<br/>continuous processing loop"]
    D <--> E[("local_data/jobs.db<br/>SQLite")]
    D --> F["Apify<br/>(LinkedIn jobs, JDs, company info)"]
    D --> G["Gemini<br/>(fit scoring, filtering, sustainability)"]
    D --> H["Resume/CL server<br/>(SERVER_URL, hosted)"]
    D --> I["Telegram bot<br/>(notify + apply/expired buttons)"]
    D --> J["Streamlit dashboard<br/>(Jobs / Activity / Settings)"]
    J <--> E
    D --> K["local_data/activity.log<br/>(timestamped)"]
```

## The main loop

`pipeline/runner.main()` runs forever until shutdown is requested (`Ctrl+C` / `SIGTERM`). Each
pass through the loop is a **processing cycle**. Between cycles it sleeps (with exponential
backoff when nothing changed) unless there's known pending work.

```mermaid
flowchart TD
    Start(["Loop iteration"]) --> Idle{"Automation idle?<br/>(only JD-fit scoring or<br/>manual CO work left)"}

    Idle -- yes --> JDOnly["JD-only fit scoring batch<br/>(score_jobs_by_jd_fit)"]
    JDOnly --> IdleSleep["Short sleep, loop again"]
    IdleSleep --> Start

    Idle -- no --> Work{"Any work or Apify available?"}
    Work -- "nothing to do &<br/>Apify unavailable" --> Stop(["Stop application"])
    Work -- "yes" --> Cycle["Run one processing cycle<br/>(_run_processing_cycle)"]
    Cycle --> Progress{"Progress made?"}
    Progress -- yes --> ResetSleep["Reset sleep interval to base"]
    Progress -- no --> BackoffSleep["Exponential backoff sleep"]
    ResetSleep --> Start
    BackoffSleep --> Start
```

## One processing cycle

```mermaid
flowchart TD
    A["Bulk-fetch missing job descriptions<br/>(Apify, batched by job id)"] --> B
    B["Fetch company overviews<br/>(only if CHECK_SUSTAINABILITY)"] --> C
    C["Collection phase<br/>(see below — serial per search)"] --> D
    D["Finalize: bulk filter leftovers<br/>(force_process=True)"] --> E
    E["Final pass: analyze + resumes/CLs<br/>scoped to dashboard default filter"] --> F
    F["Process Telegram notifications<br/>(one application at a time)"] --> G
    G["Sort DB by JD fit / fit / location priority"] --> H
    H["Auto-adjust location filters<br/>if enough Good/Very good fits"] --> End(["Cycle done"])
```

## Collection phase — serial per-search draining

**This is the important part for anyone changing collection behavior.** For each search query,
the pipeline collects that search's jobs from Apify and then **immediately drains the full
downstream pipeline for just those jobs** — bulk filter, company overview, sustainability check,
fit analysis, resume/cover-letter generation — before moving on to the next search query.

This means:

- A crash or shutdown mid-cycle only loses at most one search's worth of unprocessed jobs, not
  the whole cycle's collected backlog.
- Good/Very good fit jobs (and their resumes) show up sooner instead of waiting for every search
  in the cycle to finish first.
- If `job_preferences.yaml` has no cached search parameters yet — or the cached ones found zero
  new jobs — the LLM regenerates search parameters, and the same drain-per-search loop runs
  again for the new list.

```mermaid
flowchart TD
    Start(["process_collection_phase"]) --> HasParams{"Cached search_parameters<br/>in job_preferences.yaml?"}

    HasParams -- yes --> Loop1["For each cached search param set"]
    HasParams -- no --> Regen

    Loop1 --> Shutdown1{"Shutdown requested?"}
    Shutdown1 -- yes --> Done
    Shutdown1 -- no --> Collect1["collect_jobs_via_apify(params)<br/>→ new job rows in DB"]
    Collect1 --> HasNew1{"New jobs found?"}
    HasNew1 -- no --> Loop1
    HasNew1 -- yes --> Drain1["process_new_jobs_pipeline(new_jobs)<br/>filter → CO → sustainability →<br/>analyze → resume/CL"]
    Drain1 --> Loop1

    Loop1 -.->|all params done| CheckZero{"Zero new jobs across<br/>all cached searches?"}
    CheckZero -- yes --> Regen
    CheckZero -- no --> Done

    Regen["get_search_parameters(resume)<br/>LLM generates new search matrix"] --> SaveParams["Save to job_preferences.yaml"]
    SaveParams --> Loop2["For each new search param set"]
    Loop2 --> Shutdown2{"Shutdown requested?"}
    Shutdown2 -- yes --> Done
    Shutdown2 -- no --> Collect2["collect_jobs_via_apify(params)"]
    Collect2 --> HasNew2{"New jobs found?"}
    HasNew2 -- no --> Loop2
    HasNew2 -- yes --> Drain2["process_new_jobs_pipeline(new_jobs)"]
    Drain2 --> Loop2
    Loop2 -.->|all params done| Done(["Return collected_jobs, total_new_jobs"])
```

Implementation: `pipeline/collection.py` (`process_collection_phase`, `_run_search_and_drain`,
`process_new_jobs_pipeline`). Tests: `tests/test_collection_serial.py`.

## Job lifecycle (single job's state machine)

Every job is a row in `local_data/jobs.db` (`local_storage.JobDatabase`). Columns act as a state
machine — most pipeline steps are "find rows missing X, fill it in."

```mermaid
stateDiagram-v2
    [*] --> Collected: Apify search result
    Collected --> BulkFiltered: bulk_filter_collected_jobs<br/>(cheap LLM pre-screen, batched)
    BulkFiltered --> HasJD: JD present (Apify item or bulk_fetch_missing_job_descriptions)
    HasJD --> HasCO: Company overview fetched<br/>(only if sustainability check on)
    HasCO --> Analyzed: analyze_all_jobs<br/>(Gemini fit score + reasoning)

    Analyzed --> VeryGoodFit: Fit score = Very good fit
    Analyzed --> GoodFit: Fit score = Good fit
    Analyzed --> OtherFit: Moderate / Poor / Very poor fit

    VeryGoodFit --> ResumeReady: process_resume + process_cover_letter<br/>(triggered immediately)
    GoodFit --> ResumeReady: process_resumes_and_cover_letters<br/>(later pass)

    ResumeReady --> TelegramNotified: notify_ready_applications<br/>(one at a time, Telegram)
    TelegramNotified --> Applied: user taps "Yes, I applied"
    TelegramNotified --> BadAnalysis: user taps "Bad analysis"<br/>→ re-analyzed next cycle
    TelegramNotified --> Expired: user taps "Not yet" → "Yes, expired"

    OtherFit --> [*]
    Applied --> [*]
    Expired --> [*]
    BadAnalysis --> Analyzed
```

Key columns: `Bulk filtered`, `Job Description`, `Company overview`, `Fit score`,
`Fit score enum`, `Tailored resume url`, `Tailored cover letter (to be humanized)`,
`Telegram notified`, `Telegram app completed`, `Applied`, `Job posting expired`, `Bad analysis`.

## Telegram notifications (one application at a time)

To avoid overwhelming the user, only one "ready to apply" job is pushed to Telegram at a time.
The next one is sent only after the current one is resolved (applied / bad analysis / expired).

```mermaid
sequenceDiagram
    participant P as Pipeline
    participant DB as jobs.db
    participant TG as Telegram

    P->>DB: find best "application ready" job<br/>(Good/Very good fit + resume + CL, not yet notified)
    P->>TG: send summary + cover letter + resume PDF<br/>+ "Yes, I applied / Not yet / Bad analysis" buttons
    P->>DB: mark Telegram notified = TRUE

    TG->>P: user taps a button (callback_query)
    P->>DB: resolve job by id, verify via URL/company/title fingerprint<br/>(protects against stale button after DB changes)
    alt Yes, I applied
        P->>DB: Applied = TRUE, Telegram app completed = TRUE
    else Not yet
        P->>TG: ask "Is the posting expired?"
        TG->>P: Yes, expired / Still active
        P->>DB: Job posting expired = TRUE (if expired)
    else Bad analysis
        P->>DB: Bad analysis = TRUE → re-scored next cycle
    end
    P->>TG: send next ready application (if any)
```

## Where to look in the code

| Concern | File |
|---|---|
| Main loop, sleep/backoff, shutdown | `pipeline/runner.py` |
| Collection + serial per-search draining | `pipeline/collection.py` |
| Bulk LLM filter, JD/CO Apify fetch | `pipeline/bulk_ops.py` |
| Fit analysis (Gemini) | `pipeline/analysis.py` |
| JD-only fit scoring (idle-time fallback) | `pipeline/jd_fit_scoring.py` |
| Resume / cover letter generation | `pipeline/resumes.py`, `api_methods.py` |
| Telegram bot + notifications | `utils/telegram_bot.py`, `pipeline/telegram_notify.py` |
| Job storage (SQLite) | `local_storage.py` |
| Dashboard (Jobs / Activity / Settings) | `dashboard/` |
| Rate limiting (Gemini) | `utils/gemini_throttle.py` (unlimited by default) |
