from datetime import date

import pytest

from wir_core import project as pj
from wir_core.errors import WirError


@pytest.mark.parametrize("text,months", [("24m", 24), ("2y", 24), ("5y", 60), (" 36 m ", 36)])
def test_parse_period_ok(text, months):
    assert pj.parse_period(text) == months


@pytest.mark.parametrize("text", ["3m", "20y", "abc", ""])
def test_parse_period_bad(text):
    with pytest.raises(WirError):
        pj.parse_period(text)


def test_parse_month():
    assert pj.parse_month("2024-09") == date(2024, 9, 1)
    with pytest.raises(WirError):
        pj.parse_month("2024-13")


def test_slugify():
    assert pj.slugify("Intermittent fasting!") == "intermittent-fasting"
    assert pj.slugify("Астрономія") == ""


def make(wir_env):
    p = pj.new_project(topic="intermittent fasting", qid="Q1666254", label="intermittent fasting",
                       description="diet", source="wikipedia", langs=["pl", "cs"], ui="uk",
                       period_months=24, date_from=None, date_to=None)
    p.entries["cs"] = pj.LangEntry("cs", "found", [pj.Article("Přerušovaný půst", created="2020-10-28")])
    p.entries["pl"] = pj.LangEntry("pl", "missing")
    pj.save(p)
    return p


def test_save_load_latest_roundtrip(wir_env):
    p = make(wir_env)
    assert p.id == "2026-09-27-intermittent-fasting"
    loaded = pj.load(None)
    assert loaded.to_json() == p.to_json()
    assert loaded.entries["cs"].main().title == "Přerušovaný půst" and loaded.entries["pl"].main() is None
    assert pj.load(str(p.dir)).id == p.id and pj.load(p.id).id == p.id


def test_find_by_key_and_unique_ids(wir_env):
    p = make(wir_env)
    assert pj.find_by_key(p.key).id == p.id
    q = pj.new_project(topic="x", qid="Q1", label="intermittent fasting", description="", source="wikipedia",
                       langs=["en"], ui="en", period_months=24, date_from=None, date_to=None)
    assert q.id == "2026-09-27-intermittent-fasting-2"


def test_fork_copies_directory(wir_env):
    p = make(wir_env)
    (p.dir / "analysis.json").write_text("{}")
    f = pj.fork(p)
    assert f.id != p.id and (f.dir / "analysis.json").exists() and pj.load(None).id == f.id


def test_load_without_projects_is_actionable(wir_env):
    with pytest.raises(WirError) as e:
        pj.load(None)
    assert e.value.code == "NO_PROJECT" and "wir scope" in e.value.fix


def test_status_is_offline_and_points_to_analyze(wir_env, monkeypatch):
    from argparse import Namespace

    from wir_core import net
    p = make(wir_env)
    monkeypatch.setattr(net, "open_client", lambda *a, **k: pytest.fail("status must not use the network"))
    env = pj.run_status(Namespace(project=None))
    assert env["state"] == "ready" and env["project"] == pj.rel(p.dir)
    assert env["facts"] == {"pl": {"status": "missing", "article": "—"},
                            "cs": {"status": "found", "article": "Přerušovaný půst"}}
    assert env["next"] == [{"why": pj.t("uk", "next.analyze"), "cmd": "wir analyze"}]
    assert "останні 24 повних місяців" in env["say"][0]


def test_status_shows_explicit_range_and_stale_analysis(wir_env):
    from argparse import Namespace
    p = make(wir_env)
    p.date_from, p.date_to = "2024-09", "2026-08"
    pj.save(p)
    (p.dir / "analysis.json").write_text("{}")
    assert "next" not in pj.run_status(Namespace(project=p.id))
    (p.dir / ".stale").write_text("1")
    env = pj.run_status(Namespace(project=p.id))
    assert "2024-09 – 2026-08" in env["say"][0]
    assert env["caveats"] == [pj.t("uk", "note.stale")] and env["next"][0]["cmd"] == "wir analyze"
    assert env["files"]["data"].endswith("analysis.json")
