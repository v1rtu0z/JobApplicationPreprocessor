"""Persisted Apify availability state with monthly hard-limit handling."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

STATE_FILE = Path("local_data/apify_state.json")
DEFAULT_RETRY_DELAY_SECONDS = 3600
MONTHLY_LIMIT_MARKER = "Monthly usage hard limit exceeded"


def seconds_until_next_month() -> float:
    """Seconds until the first moment of the next calendar month (local time)."""
    now = datetime.now()
    if now.month == 12:
        target = datetime(now.year + 1, 1, 1)
    else:
        target = datetime(now.year, now.month + 1, 1)
    return max(0.0, target.timestamp() - time.time())


def format_duration(seconds: float) -> str:
    if seconds <= 0:
        return "0s"
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes and days == 0:
        parts.append(f"{minutes}m")
    return " ".join(parts) if parts else f"{int(seconds)}s"


class ApifyStateManager:
    """Tracks Apify availability; monthly hard limits wait until next calendar month."""

    def __init__(self):
        self._available = True
        self._last_failure_time: float | None = None
        self._retry_delay = DEFAULT_RETRY_DELAY_SECONDS
        self._monthly_limited = False
        self._load_persisted()

    def _load_persisted(self) -> None:
        if not STATE_FILE.is_file():
            return
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self._monthly_limited = bool(data.get("monthly_limited"))
        self._last_failure_time = data.get("last_failure_time")
        if self._monthly_limited:
            self._available = False
            if self._monthly_retry_elapsed():
                self._clear_monthly_limit()

    def _persist(self) -> None:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "monthly_limited": self._monthly_limited,
            "last_failure_time": self._last_failure_time,
        }
        STATE_FILE.write_text(json.dumps(payload), encoding="utf-8")

    def _monthly_retry_elapsed(self) -> bool:
        return seconds_until_next_month() <= 0

    def _clear_monthly_limit(self) -> None:
        self._monthly_limited = False
        self._available = True
        self._last_failure_time = None
        self._persist()
        print("Apify monthly limit period ended — Apify is available again.")

    def is_monthly_limited(self) -> bool:
        if not self._monthly_limited:
            return False
        if self._monthly_retry_elapsed():
            self._clear_monthly_limit()
            return False
        return True

    def seconds_until_retry(self) -> float:
        if self.is_monthly_limited():
            return seconds_until_next_month()
        if not self._available and self._last_failure_time is not None:
            elapsed = time.time() - self._last_failure_time
            return max(0.0, self._retry_delay - elapsed)
        return 0.0

    def is_available(self) -> bool:
        if self.is_monthly_limited():
            return False
        if not self._available and self._last_failure_time is not None:
            elapsed = time.time() - self._last_failure_time
            if elapsed > self._retry_delay:
                print(f"Apify retry delay ({self._retry_delay}s) elapsed. Allowing retry...")
                self._available = True
                self._last_failure_time = None
                self._persist()
        return self._available

    def mark_unavailable(self) -> None:
        """Mark unavailable with a short retry (non-monthly failures)."""
        if self._monthly_limited:
            return
        self._available = False
        self._last_failure_time = time.time()
        self._persist()

    def mark_monthly_limit_exhausted(self) -> None:
        """Mark unavailable until the next calendar month."""
        self._available = False
        self._monthly_limited = True
        self._last_failure_time = time.time()
        self._persist()
        wait = seconds_until_next_month()
        print(
            f"Apify will remain disabled until next month "
            f"({format_duration(wait)} remaining)."
        )

    @staticmethod
    def is_monthly_limit_error(error_msg: str) -> bool:
        return MONTHLY_LIMIT_MARKER in (error_msg or "")

    def handle_error(self, error_msg: str) -> None:
        if self.is_monthly_limit_error(error_msg):
            print("\n" + "!" * 60)
            print("CRITICAL: APIFY MONTHLY USAGE HARD LIMIT REACHED.")
            print("No more Apify calls until next month.")
            print("!" * 60 + "\n")
            self.mark_monthly_limit_exhausted()
        else:
            self.mark_unavailable()

    def reset(self) -> None:
        """Reset state to available (testing or manual intervention)."""
        self._available = True
        self._last_failure_time = None
        self._monthly_limited = False
        if STATE_FILE.is_file():
            try:
                STATE_FILE.unlink()
            except OSError:
                pass


apify_state = ApifyStateManager()
