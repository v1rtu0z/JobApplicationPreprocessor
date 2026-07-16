"""Tests for editable LLM prompt templates (utils.prompts)."""

import yaml

from utils.prompts import (
    DEFAULT_PROMPTS,
    get_prompt_template,
    is_prompt_customized,
    list_prompt_names,
    render_prompt,
    reset_all_prompts,
    reset_prompt,
    save_prompt_overrides,
)


def _point_config(tmp_path, monkeypatch, initial: dict | None = None):
    config_path = tmp_path / "job_preferences.yaml"
    config_path.write_text(
        yaml.safe_dump(initial or {"search_parameters": []}, sort_keys=False),
        encoding="utf-8",
    )
    monkeypatch.setattr("config.CONFIG_FILE", str(config_path))
    return config_path


def test_list_prompt_names_covers_defaults():
    names = list_prompt_names()
    assert "fit_score_batch" in names
    assert "jd_fit" in names
    assert "search_parameters" in names
    assert "bulk_filter" in names
    assert "sustainability_bulk" in names
    assert set(names) == set(DEFAULT_PROMPTS)


def test_default_template_without_overrides(tmp_path, monkeypatch):
    _point_config(tmp_path, monkeypatch)
    assert get_prompt_template("salary_fit") == DEFAULT_PROMPTS["salary_fit"]
    assert not is_prompt_customized("salary_fit")


def test_save_override_and_reset(tmp_path, monkeypatch):
    config_path = _point_config(tmp_path, monkeypatch)
    custom = "CUSTOM salary floor note {minimum_salary_usd_monthly}"
    save_prompt_overrides({"salary_fit": custom})
    assert is_prompt_customized("salary_fit")
    assert get_prompt_template("salary_fit") == custom

    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert saved["prompts"]["salary_fit"] == custom

    reset_prompt("salary_fit")
    assert not is_prompt_customized("salary_fit")
    assert get_prompt_template("salary_fit") == DEFAULT_PROMPTS["salary_fit"]
    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert not (saved or {}).get("prompts")


def test_saving_default_text_clears_override(tmp_path, monkeypatch):
    _point_config(tmp_path, monkeypatch)
    save_prompt_overrides({"jd_fit": "tweaked once"})
    assert is_prompt_customized("jd_fit")
    save_prompt_overrides({"jd_fit": DEFAULT_PROMPTS["jd_fit"]})
    assert not is_prompt_customized("jd_fit")


def test_reset_all_prompts(tmp_path, monkeypatch):
    _point_config(tmp_path, monkeypatch)
    save_prompt_overrides({
        "salary_fit": "a",
        "bulk_filter": "b",
    })
    assert is_prompt_customized("salary_fit")
    reset_all_prompts()
    assert not is_prompt_customized("salary_fit")
    assert not is_prompt_customized("bulk_filter")


def test_render_prompt_substitutes_and_unescapes_braces(tmp_path, monkeypatch):
    _point_config(tmp_path, monkeypatch)
    out = render_prompt(
        "salary_fit",
        minimum_salary_usd_monthly="9,999",
    )
    assert "USD $9,999/month" in out
    assert "{minimum_salary_usd_monthly}" not in out

    batch = render_prompt(
        "fit_score_batch",
        top_fit_requirements="TOP",
        salary_section="SAL",
        resume_json='{"n":1}',
        jobs_text="JOBS",
        fit_scores_json='["Good fit"]',
    )
    assert "TOP" in batch and "SAL" in batch and "JOBS" in batch
    assert '{"job_id": "Engineer @ Acme"' in batch
    assert "{{" not in batch


def test_render_leaves_unknown_placeholders(tmp_path, monkeypatch):
    _point_config(tmp_path, monkeypatch)
    save_prompt_overrides({"bulk_filter": "Hello {user_name} and {unknown_thing}"})
    out = render_prompt("bulk_filter", user_name="Ada")
    assert "Hello Ada" in out
    assert "{unknown_thing}" in out


def test_gemini_analysis_uses_prompt_store(tmp_path, monkeypatch):
    _point_config(tmp_path, monkeypatch)
    save_prompt_overrides({
        "fit_score_batch": "BATCH_MARKER {top_fit_requirements} {salary_section} {resume_json} {jobs_text} {fit_scores_json}",
        "top_fit_score_requirements": "TOP_MARKER",
        "salary_fit": "SAL_MARKER {minimum_salary_usd_monthly}",
    })
    from utils.gemini_analysis import _build_batch_analysis_prompt

    prompt = _build_batch_analysis_prompt(
        {"personal": {"full_name": "Test"}},
        [{"job_title": "Eng", "company_name": "Acme", "job_description": "desc"}],
    )
    assert "BATCH_MARKER" in prompt
    assert "TOP_MARKER" in prompt
    assert "SAL_MARKER" in prompt
