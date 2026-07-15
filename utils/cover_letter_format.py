"""Normalize generated cover letter text before storage."""

import re


def normalize_cover_letter_body(text: str) -> str:
    """Strip email-style headers and normalize the opening salutation."""
    text = (text or "").strip()
    if not text:
        return text

    while text.lower().startswith("subject:"):
        text = text.split("\n", 1)[1].strip() if "\n" in text else ""

    dear_match = re.search(r"(?i)\bdear\b", text)
    if dear_match:
        text = text[dear_match.start() :]

    text = re.sub(
        r"(?i)^Dear[^,\n]*,",
        "Dear Hiring Team,",
        text,
        count=1,
    )
    return text.strip()
