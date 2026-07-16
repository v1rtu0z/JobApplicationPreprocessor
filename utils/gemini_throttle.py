"""Gemini API rate throttle: optional RPM/RPD gate for all Gemini-backed work.

By default there is no local cap (RPM/RPD = 0). Set GEMINI_RPM / GEMINI_RPD to
positive integers only if you need to stay under a specific quota.
"""

import os
import time
from collections import deque

# 0 = unlimited (no local throttle). Positive values enforce a soft gate.
DEFAULT_GEMINI_RPM = 0
DEFAULT_GEMINI_RPD = 0
WINDOW_MINUTE_SEC = 60
WINDOW_DAY_SEC = 24 * 3600

_request_timestamps: deque[float] = deque()


class GeminiThrottleExhausted(Exception):
    """Raised when a configured RPD gate cannot admit another request yet."""


def _get_rpm_limit() -> int:
    try:
        return max(0, int(os.getenv("GEMINI_RPM", str(DEFAULT_GEMINI_RPM))))
    except (TypeError, ValueError):
        return DEFAULT_GEMINI_RPM


def _get_rpd_limit() -> int:
    try:
        return max(0, int(os.getenv("GEMINI_RPD", str(DEFAULT_GEMINI_RPD))))
    except (TypeError, ValueError):
        return DEFAULT_GEMINI_RPD


def _trim_and_count(now: float):
    """Drop timestamps outside the last 24h; return (count_last_minute, count_last_day)."""
    global _request_timestamps
    while _request_timestamps and _request_timestamps[0] < now - WINDOW_DAY_SEC:
        _request_timestamps.popleft()
    last_minute = sum(1 for t in _request_timestamps if t >= now - WINDOW_MINUTE_SEC)
    return last_minute, len(_request_timestamps)


def acquire_gemini_slot() -> None:
    """
    Optionally block until a Gemini request is allowed under RPM/RPD, then record it.

    When GEMINI_RPM and GEMINI_RPD are 0 (default), returns immediately with no wait.
    Call once before each Gemini API call (or batch / server request that uses Gemini).
    """
    rpm = _get_rpm_limit()
    rpd = _get_rpd_limit()
    if rpm <= 0 and rpd <= 0:
        return

    while True:
        now = time.time()
        last_minute, last_day = _trim_and_count(now)

        if rpm > 0 and last_minute >= rpm:
            oldest_in_minute = next(t for t in _request_timestamps if t >= now - WINDOW_MINUTE_SEC)
            sleep_time = WINDOW_MINUTE_SEC - (now - oldest_in_minute)
            if sleep_time > 0:
                print(
                    f"Gemini RPM throttle: {last_minute}/{rpm} requests in the last minute. "
                    f"Waiting {sleep_time:.0f}s..."
                )
                time.sleep(sleep_time)
            continue

        if rpd > 0 and last_day >= rpd:
            oldest = _request_timestamps[0]
            retry_in = max(0.0, WINDOW_DAY_SEC - (now - oldest))
            hours = retry_in / 3600
            raise GeminiThrottleExhausted(
                f"Local Gemini daily quota reached ({last_day}/{rpd} requests in 24h). "
                f"Next slot frees in ~{hours:.1f}h. Pausing resume/cover-letter work until then."
            )

        _request_timestamps.append(time.time())
        return
