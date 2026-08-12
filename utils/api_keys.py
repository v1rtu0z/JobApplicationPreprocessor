"""Multi-key API resilience: resolve ordered key lists and fail over on quota errors.

Free-tier LLM/scraper quotas exhaust quickly. These helpers let the app rotate
across several configured API keys/tokens and fail over automatically when one
hits a quota / rate-limit / transient 5xx error, raising a single clear error
once every key is exhausted.

Backward compatible: the single-key environment variables still work — they are
simply treated as a one-element list.
"""

from __future__ import annotations

import os
from typing import Callable, Iterable, Optional, TypeVar

T = TypeVar("T")


class AllKeysExhaustedError(RuntimeError):
    """Raised when every configured API key failed with a retryable error."""


# Substrings (lower-cased) that indicate a quota / rate-limit / transient error
# worth failing over to the next key for.
_RETRYABLE_MARKERS = (
    "429",
    "quota",
    "rate limit",
    "rate-limit",
    "ratelimit",
    "too many requests",
    "resource exhausted",
    "resource_exhausted",
    "503",
    "service unavailable",
    "temporarily unavailable",
)


def is_quota_or_rate_limit_error(exc: BaseException) -> bool:
    """True when the exception looks like a quota / rate-limit / transient 5xx error."""
    for attr in ("status_code", "code", "status"):
        value = getattr(exc, attr, None)
        try:
            if int(value) in (429, 503):
                return True
        except (TypeError, ValueError):
            pass
    text = str(exc).lower()
    return any(marker in text for marker in _RETRYABLE_MARKERS)


def _split_csv(value: Optional[str]) -> list[str]:
    """Split a comma-separated env value into stripped, non-empty parts."""
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def _ordered_unique(items: Iterable[str]) -> list[str]:
    """De-duplicate while preserving first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def get_gemini_api_keys() -> list[str]:
    """Ordered, de-duplicated Gemini API keys.

    Reads ``GEMINI_API_KEYS`` (comma-separated) first, then the legacy single-key
    variables ``GEMINI_API_KEY`` and ``BACKUP_GEMINI_API_KEY`` for backward
    compatibility. Duplicates and blanks are removed; order is preserved.
    """
    keys = _split_csv(os.getenv("GEMINI_API_KEYS"))
    keys.append((os.getenv("GEMINI_API_KEY") or "").strip())
    keys.append((os.getenv("BACKUP_GEMINI_API_KEY") or "").strip())
    return _ordered_unique(keys)


def get_gemini_labeled_keys() -> list[tuple[str, str]]:
    """Ordered ``(label, key)`` pairs for every configured Gemini key.

    Labels are ``"key 1"``, ``"key 2"``, … for readable logging. A single
    configured key yields a one-element list, so existing setups are unaffected.
    """
    return [(f"key {i + 1}", key) for i, key in enumerate(get_gemini_api_keys())]


def get_apify_api_tokens() -> list[str]:
    """Ordered, de-duplicated Apify API tokens.

    Reads ``APIFY_API_TOKENS`` (comma-separated) first, then the legacy single
    ``APIFY_API_TOKEN`` for backward compatibility.
    """
    tokens = _split_csv(os.getenv("APIFY_API_TOKENS"))
    tokens.append((os.getenv("APIFY_API_TOKEN") or "").strip())
    return _ordered_unique(tokens)


def run_with_key_failover(
    keys: Iterable[str],
    fn: Callable[[str], T],
    *,
    label: str = "API",
    is_retryable: Callable[[BaseException], bool] = is_quota_or_rate_limit_error,
) -> T:
    """Call ``fn(key)`` for each key in order, failing over on retryable errors.

    Returns the first successful ``fn(key)`` result. When ``fn`` raises an error
    deemed retryable (quota / rate-limit / transient 5xx), moves on to the next
    key. A non-retryable error is re-raised immediately (no point burning the
    remaining keys). When every key raises a retryable error, raises
    :class:`AllKeysExhaustedError` after logging ``"All N <label> keys exhausted"``.
    """
    key_list = [k for k in keys if k]
    if not key_list:
        raise AllKeysExhaustedError(f"No {label} keys configured")

    total = len(key_list)
    last_error: Optional[BaseException] = None
    for index, key in enumerate(key_list):
        try:
            return fn(key)
        except Exception as exc:  # noqa: BLE001 - failover is the whole point
            if not is_retryable(exc):
                raise
            last_error = exc
            if index + 1 < total:
                print(
                    f"{label} key {index + 1}/{total} exhausted ({exc}); "
                    f"failing over to next key."
                )

    print(f"All {total} {label} keys exhausted.")
    raise AllKeysExhaustedError(f"All {total} {label} keys exhausted") from last_error
