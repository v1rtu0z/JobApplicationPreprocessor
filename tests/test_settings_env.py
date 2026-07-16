"""Tests for Settings .env writer helpers."""

from dashboard.settings import _write_env_file


def test_write_env_strips_use_local_storage(tmp_path):
    env_path = tmp_path / ".env"
    _write_env_file(
        env_path,
        {
            "GEMINI_MODEL": "gemini-2.0-flash",
            "USE_LOCAL_STORAGE": "true",
            "CHECK_SUSTAINABILITY": "false",
        },
    )
    text = env_path.read_text(encoding="utf-8")
    assert "USE_LOCAL_STORAGE" not in text
    assert "GEMINI_MODEL=gemini-2.0-flash" in text
