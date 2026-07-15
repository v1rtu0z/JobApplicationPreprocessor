# RenderCV playbook (append-only)

Agents **append** new entries at the bottom. Do not delete rows; if a note is wrong, add a superseding entry that references the old one.

## Entry template

```markdown
### YYYY-MM-DD — [short title]

- **Context:** (job / theme / base vs tailored)
- **Symptom:** (user or PDF observation)
- **Hypothesis:** (content | theme | design | structure)
- **Change:** (exact edit)
- **Result:** (better / worse / partial; page count if noted)
- **Keep:** (recommendation for future)
```

---

### 2026-07-15 — Default theme for this project

- **Context:** Job Application Preprocessor defaults
- **Symptom:** N/A (baseline)
- **Hypothesis:** theme
- **Change:** `general_settings.resume_theme: engineeringclassic` in `job_preferences.yaml`
- **Result:** Default pipeline output; engineering-oriented one-line entry style
- **Keep:** Try `moderncv` or `sb2nov` when user wants denser layout or more classic academic look

---

### 2026-07-15 — Long responsibility bullets wrap heavily

- **Context:** Tailored resumes with LLM-expanded bullets (e.g. Recombo 4-line bullets)
- **Symptom:** Page count increases; dense paragraphs in experience section
- **Hypothesis:** content
- **Change:** Cap bullets at ~2 lines (~220 chars); move extra facts to `additionalDetails` or drop lowest-priority bullet
- **Result:** Expected to reduce vertical space without theme change
- **Keep:** Prefer content trim before switching theme when complaint is "too long" or "wall of text"

---

### 2026-07-15 — additionalDetails is content, not a RenderCV section

- **Context:** `resume_data.json` root field `additionalDetails`
- **Symptom:** User adds narrative facts; may or may not appear in PDF depending on server mapping
- **Hypothesis:** structure
- **Change:** Use for facts that should influence tailoring but not always as visible bullets; verify PDF after edit
- **Result:** Feeds LLM tailoring; confirm render server includes it in output JSON sections
- **Keep:** After editing `additionalDetails`, regenerate one PDF to confirm visibility

---

### 2026-07-15 — Theme switch is fast A/B test

- **Context:** Dashboard Settings → General → Resume theme
- **Symptom:** User unsure which layout fits
- **Hypothesis:** theme
- **Change:** Same JSON, regenerate PDF with `engineeringclassic` vs `moderncv` vs `engineeringresumes`
- **Result:** Side-by-side comparison usually resolves preference faster than bullet edits
- **Keep:** Run theme A/B before deep JSON surgery when complaint is aesthetic (fonts, spacing, header)
