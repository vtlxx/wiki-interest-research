from datetime import date

from wir_core import config


def test_user_agent_uses_contact_env(monkeypatch):
    monkeypatch.setenv("WIR_CONTACT", "https://example.org/me")
    ua = config.user_agent()
    assert ua.startswith(f"wiki-interest-research/{config.VERSION} (")
    assert "https://example.org/me" in ua


def test_user_agent_default_contact(monkeypatch):
    monkeypatch.delenv("WIR_CONTACT", raising=False)
    assert config.DEFAULT_CONTACT in config.user_agent()


def test_cache_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("WIR_CACHE_DIR", str(tmp_path / "c"))
    assert config.cache_dir() == tmp_path / "c"


def test_output_root_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("WIR_OUTPUT_DIR", str(tmp_path / "o"))
    assert config.output_root() == tmp_path / "o"


def test_output_root_default_is_cwd(monkeypatch, tmp_path):
    monkeypatch.delenv("WIR_OUTPUT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert config.output_root() == tmp_path / "wiki-interest-output"


def test_today_utc_pinned(monkeypatch):
    monkeypatch.setenv("WIR_TODAY", "2026-09-27")
    assert config.today_utc() == date(2026, 9, 27)


def test_skill_root_contains_skill_md():
    assert (config.skill_root() / "SKILL.md").exists()
    assert config.assets_dir() == config.skill_root() / "assets"
