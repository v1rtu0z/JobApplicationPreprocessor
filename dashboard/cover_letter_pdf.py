"""Build a simple PDF from cover letter plain text (dashboard export).

Uses DejaVu Sans (LGPL) shipped under dashboard/fonts/ for UTF-8 text.
"""

from __future__ import annotations

import re
from pathlib import Path

from fpdf import FPDF

_DEJAVU = Path(__file__).resolve().parent / "fonts" / "DejaVuSans.ttf"


def safe_cover_letter_pdf_filename(company: str, job_title: str) -> str:
    """Filesystem-safe name for download; ASCII-ish slug with unicode letters kept via \\w."""
    parts = [p for p in (company or "", job_title or "") if p.strip()]
    raw = "cover_letter_" + "_".join(parts) if parts else "cover_letter"
    safe = re.sub(r"[^\w\s-]", "", raw, flags=re.UNICODE)
    safe = re.sub(r"[-\s]+", "_", safe).strip("_")
    base = safe[:120] if safe else "cover_letter"
    return f"{base}.pdf"


def cover_letter_text_to_pdf_bytes(text: str) -> bytes:
    """Render cover letter text to a PDF (DejaVu for UTF-8). Empty input yields a minimal one-page PDF."""
    body = text if text is not None else ""
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(18, 18, 18)
    pdf.add_page()
    if not _DEJAVU.is_file():
        raise FileNotFoundError(
            f"Missing font file {_DEJAVU}; add DejaVuSans.ttf under dashboard/fonts/."
        )
    pdf.add_font("DejaVu", "", str(_DEJAVU))
    pdf.set_font("DejaVu", size=11)
    if not body.strip():
        pdf.multi_cell(0, 6, " ")
    else:
        blocks = body.split("\n\n")
        for i, block in enumerate(blocks):
            if i > 0:
                pdf.ln(4)
            pdf.multi_cell(0, 6, block)
    out = pdf.output()
    return out if isinstance(out, bytes) else bytes(out)
