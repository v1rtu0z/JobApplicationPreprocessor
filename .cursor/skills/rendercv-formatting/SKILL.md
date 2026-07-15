---
name: rendercv-formatting
description: >-
  Iterates on RenderCV resume layout and content to fix PDF feedback (spacing,
  overflow, themes, sections). Use when tailoring resumes, resume PDF looks wrong,
  RenderCV themes, resume feedback, resume_data.json, or job_preferences resume_theme.
---

# RenderCV formatting (living skill)

This skill **grows over time**. Before acting, read [playbook.md](playbook.md) and [feedback-map.md](feedback-map.md). After you learn something new from exploration or user feedback, **append** to those files (never delete history; mark superseded entries instead).

## When to use

- User dislikes resume PDF layout, density, fonts, page breaks, or section order
- Tuning `resume_theme` or resume JSON for Job Application Preprocessor
- Comparing themes or bullet strategies for a specific job
- Interpreting dashboard **Resume feedback** for regeneration

## This project (Job Application Preprocessor)

| What | Where |
|------|--------|
| Base resume JSON | `resume_data.json` (gitignored) |
| Theme | `job_preferences.yaml` → `general_settings.resume_theme` (dashboard: Settings → General) |
| Theme list | `rendercv_themes.txt` or defaults: `engineeringclassic`, `moderncv`, `classic`, `sb2nov`, `engineeringresumes` |
| Generate tailored PDF | Pipeline / dashboard; server `POST {SERVER_URL}/tailor-resume` with `theme` + `resume_json_data` |
| Per-job tailored JSON | DB column `Tailored resume json`; PDF at `Tailored resume url` |
| Regenerate with notes | Dashboard **Resume feedback** → pipeline sets `Resume feedback addressed` after regen |

**Lever order (try in this sequence):**

1. **Content** — shorten bullets, split long lines, drop low-value items, move facts to `summary` vs `experience`
2. **Theme** — switch `resume_theme` (layout presets share Typst templates; defaults differ)
3. **Structure** — reorder experience, merge skill categories, trim `additionalDetails` if it bloats tailoring
4. **Retry feedback** — pass concrete, visual instructions via `Resume feedback` / `retry_feedback` (see feedback-map)
5. **RenderCV design / templates** — only if you control the render server or run CLI locally (see Exploration below)

## Exploration loop (use for unfamiliar feedback)

Work in **small deltas** — change one lever per render, keep a note of what changed.

```
1. Capture baseline
   - Save current PDF path + theme + (if tailored) job company/title
   - Skim page count, header block, longest bullets, skills density

2. Hypothesize
   - Map user words to lever: content | theme | spacing | section order (see feedback-map)

3. Apply one change
   - Theme only, OR edit 1–2 bullets, OR one skills category — not all at once

4. Render & compare
   - This repo: regenerate one job resume OR call tailor-resume for a fixture job
   - Local CLI (optional): rendercv render CV.yaml --design.theme moderncv -o /tmp/out.pdf

5. Record outcome
   - Append playbook entry: symptom → change → result → theme → date
   - Add feedback-map row if reusable

6. Stop or iterate
   - If fixed: update base JSON / theme / document recommendation for user
   - If not: next lever; do not stack 5 changes without intermediate PDFs
```

Spend **2–4 deliberate iterations** on novel complaints before asking the user to choose between options. Show what you tried (theme A vs B, bullet length before/after).

## RenderCV concepts (quick reference)

RenderCV YAML has `cv`, `design`, `locale`, `settings`. This app uses **JSON** shaped like `resume_data.json`; the render server maps it to RenderCV.

**Themes** set default `design` values (margins, fonts, entry templates, page breaks). Same template engine; theme changes defaults.

**Common design knobs** (when editing YAML/CLI/server theme config):

- `design.page` — margins, page size, footer
- `design.typography` — font size, line spacing, alignment
- `design.entries` / `design.highlights` — bullet spacing, margins between entries
- `design.templates.*` — one-line vs two-line entry layouts
- `settings.rendercv.allow_page_break_in_entries` — keep role blocks intact vs split

Docs: https://docs.rendercv.com/user_guide/yaml_input_structure/design/

**Content rules that affect layout (JSON):**

- Each `experience[].responsibilities[]` string → usually one bullet; long strings wrap and push pages
- `summary` — often one dense paragraph; splitting can help scanning
- `skills[].items` — many items → multi-column overflow depending on theme
- `personal.social_networks` — header width affects line breaks

## Writing effective resume feedback (for regeneration)

Be **visual and specific**, not vague:

- Bad: "make it cleaner"
- Good: "Limit Recombo to 3 bullets max 2 lines each; move Langfuse migration to additionalDetails; keep theme engineeringclassic"

Include: target company/job if tailored, theme to keep or try, max bullets per role, phrases to preserve verbatim.

## After each task (required)

1. Append to [playbook.md](playbook.md) using the entry template there
2. If the fix generalizes, add a row to [feedback-map.md](feedback-map.md)
3. Mention in the user reply which playbook entry you added (one line)

## Additional resources

- [playbook.md](playbook.md) — dated experiments and outcomes (project-specific)
- [feedback-map.md](feedback-map.md) — symptom → first lever to try
- RenderCV CLI: `rendercv render`, `rendercv create-theme`, `--design.theme`
