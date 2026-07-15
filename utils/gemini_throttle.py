"""Gemini API rate throttle: RPM and RPD limits, single gate for all Gemini-backed work."""

import os
import time
from collections import deque

# Defaults for free tier (e.g. 5 RPM / 25 RPD); use slightly lower to be safe
DEFAULT_GEMINI_RPM = 4
DEFAULT_GEMINI_RPD = 20
WINDOW_MINUTE_SEC = 60
WINDOW_DAY_SEC = 24 * 3600

_request_timestamps: deque[float] = deque()


class GeminiThrottleExhausted(Exception):
    """Raised when the local RPM/RPD gate cannot admit another request yet."""


def _get_rpm_limit() -> int:
    try:
        return max(1, int(os.getenv("GEMINI_RPM", str(DEFAULT_GEMINI_RPM))))
    except (TypeError, ValueError):
        return DEFAULT_GEMINI_RPM


def _get_rpd_limit() -> int:
    try:
        return max(1, int(os.getenv("GEMINI_RPD", str(DEFAULT_GEMINI_RPD))))
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
    Block until a Gemini request is allowed under RPM and RPD limits, then record the request.
    Call this once before each Gemini API call (or before each batch / server request that uses Gemini).
    """
    rpm = _get_rpm_limit()
    rpd = _get_rpd_limit()

    while True:
        now = time.time()
        last_minute, last_day = _trim_and_count(now)

        if last_minute >= rpm:
            # Wait until oldest request in the last minute is outside the window
            oldest_in_minute = next(t for t in _request_timestamps if t >= now - WINDOW_MINUTE_SEC)
            sleep_time = WINDOW_MINUTE_SEC - (now - oldest_in_minute)
            if sleep_time > 0:
                print(
                    f"Gemini RPM throttle: {last_minute}/{rpm} requests in the last minute. "
                    f"Waiting {sleep_time:.0f}s..."
                )
                time.sleep(sleep_time)
            continue

        if last_day >= rpd:
            oldest = _request_timestamps[0]
            retry_in = max(0.0, WINDOW_DAY_SEC - (now - oldest))
            hours = retry_in / 3600
            raise GeminiThrottleExhausted(
                f"Local Gemini daily quota reached ({last_day}/{rpd} requests in 24h). "
                f"Next slot frees in ~{hours:.1f}h. Pausing resume/cover-letter work until then."
            )

        _request_timestamps.append(time.time())
        return
