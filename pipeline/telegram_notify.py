"""Pipeline hooks for Telegram notifications."""

from utils.telegram_bot import (
    is_enabled,
    notify_ready_applications,
    prompt_manual_co_if_needed,
    start_update_listener,
)


def _ensure_listener(db) -> None:
    if is_enabled():
        start_update_listener(lambda: db)


def process_telegram_notifications(db) -> int:
    """Notify via Telegram and ensure the reply listener is running."""
    if not is_enabled():
        return 0
    _ensure_listener(db)
    return notify_ready_applications(db)


def process_telegram_manual_co_prompt(db) -> bool:
    """Prompt for one manual company overview via Telegram (most promising job first)."""
    if not is_enabled():
        return False
    _ensure_listener(db)
    return prompt_manual_co_if_needed(db)
