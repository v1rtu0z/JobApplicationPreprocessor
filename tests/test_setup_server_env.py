"""Tests for first-run setup .env writing (Telegram optional fields)."""
from pathlib import Path

from setup_server import write_env_from_form


def test_write_env_omits_telegram_when_blank(tmp_path: Path):
    write_env_from_form(
        tmp_path,
        {
            "apify_api_token": "apify_tok",
            "gemini_api_key": "gemini_key",
            "gemini_model": "gemini-2.0-flash",
            "check_sustainability": "",
            "telegram_bot_token": "",
            "telegram_chat_id": "  ",
        },
    )
    text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "APIFY_API_TOKEN=apify_tok" in text
    assert "GEMINI_API_KEY=gemini_key" in text
    assert "TELEGRAM_BOT_TOKEN" not in text
    assert "TELEGRAM_CHAT_ID" not in text


def test_write_env_includes_telegram_when_set(tmp_path: Path):
    write_env_from_form(
        tmp_path,
        {
            "apify_api_token": "apify_tok",
            "gemini_api_key": "gemini_key",
            "telegram_bot_token": "123:ABC",
            "telegram_chat_id": "2094018073",
        },
    )
    text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "TELEGRAM_BOT_TOKEN=123:ABC" in text
    assert "TELEGRAM_CHAT_ID=2094018073" in text


def test_write_env_token_only_without_chat_id(tmp_path: Path):
    write_env_from_form(
        tmp_path,
        {
            "apify_api_token": "apify_tok",
            "gemini_api_key": "gemini_key",
            "telegram_bot_token": "123:ABC",
        },
    )
    text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "TELEGRAM_BOT_TOKEN=123:ABC" in text
    assert "TELEGRAM_CHAT_ID" not in text
