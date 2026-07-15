# Feedback → first lever to try

Quick routing before deep exploration. Update when playbook entries prove a better first step.

| User says (symptoms) | Try first | Then | Avoid initially |
|----------------------|-----------|------|-----------------|
| Too long / 3 pages / wall of text | Shorten bullets; drop 1 role bullet or skills items | Theme with tighter margins (`engineeringresumes`) | Custom Typst templates |
| Cramped / hard to read | Switch theme (`moderncv`, `classic`) | Increase spacing via design YAML (if server supports) | Deleting entire sections |
| Ugly header / contact line breaks | Fewer `social_networks`; shorter location string | Theme with `header.alignment: left` (design) | Rewriting all experience |
| Skills section overflow | Fewer items per category; merge categories | Move rare skills to one "Other" category | Font size hacks |
| Wrong emphasis for job | Tailored JSON + `Resume feedback` with role ordering | Edit base `resume_data.json` experience order | Theme change only |
| Missing fact | Add to right `experience` bullet or `additionalDetails` | Regenerate tailored resume | Only editing PDF manually |
| Inconsistent with cover letter | Align titles in JSON; same `personal.full_name` | Regenerate both CL and resume | New theme per document |
| Page break mid-job | Theme with `allow_page_break_in_entries: false` (design) | Shorten that job's bullets | Random bullet deletion |
| Too plain / boring | Theme (`moderncv`, colored design overrides) | Bold section titles in design | Adding decorative content |
| Too flashy | `engineeringclassic` or `classic`; minimal colors | Reduce skills count | — |

## Resume feedback phrasing (for dashboard / API)

Copy-adapt these into **Resume feedback** when regenerating:

```
Theme: engineeringclassic. Max 3 bullets for current employer, 2 for others.
Each bullet ≤ 2 lines. Lead with Python/AWS for this JD. Drop duplicated ML buzzwords.
```

```
Try theme moderncv. Keep all companies; shorten Antara bullets by 30%.
Preserve Recombo LLM/verification wording verbatim.
```

## RenderCV CLI spot checks (optional, local)

When `rendercv` is installed and you have YAML:

```bash
rendercv render My_CV.yaml --design.theme engineeringclassic -pdf-path /tmp/a.pdf
rendercv render My_CV.yaml --design.theme moderncv -pdf-path /tmp/b.pdf
```

Compare `/tmp/a.pdf` and `/tmp/b.pdf` before editing project JSON.
