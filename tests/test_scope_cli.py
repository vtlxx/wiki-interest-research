import json
import shlex

from wir_core.cli import build_parser


def assert_cmds_parse(env):
    for opt in env.get("ask", {}).get("options", []) + env.get("next", []):
        if "<" not in opt["cmd"]:
            build_parser().parse_args(shlex.split(opt["cmd"])[1:])


def test_fasting_pl_missing_then_drop(cli_fixtures, run_cli):
    cli_fixtures("scope_fasting")
    code, env = run_cli("scope", "intermittent fasting", "--langs", "pl,cs", "--ui", "uk")
    assert code == 2 and env["state"] == "input_required"
    assert env["facts"]["pl"]["status"] == "missing" and env["facts"]["cs"]["article"] == "Přerušovaný půst"
    cmds = [o["cmd"] for o in env["ask"]["options"]]
    assert "wir scope --drop-lang pl" in cmds and any(c.startswith("wir scope --set pl=") for c in cmds)
    assert_cmds_parse(env)
    assert any("Q1666254" in c for c in env["caveats"])
    code, env = run_cli("scope", "--drop-lang", "pl")
    assert code == 0 and list(env["facts"]) == ["cs"] and env["next"][0]["cmd"] == "wir analyze"


def test_set_proxy_title(cli_fixtures, run_cli):
    cli_fixtures("scope_fasting")
    run_cli("scope", "intermittent fasting", "--langs", "pl,cs", "--ui", "uk")
    code, env = run_cli("scope", "--set", "pl=Głodówka lecznicza")
    assert code == 0 and env["facts"]["pl"]["status"] == "proxy"
    assert any("Głodówka lecznicza" in c for c in env["caveats"])


def test_scope_idempotent(cli_fixtures, run_cli):
    cli_fixtures("scope_fasting")
    _, first = run_cli("scope", "Q1666254", "--langs", "cs", "--ui", "en")
    _, second = run_cli("scope", "Q1666254", "--langs", "cs", "--ui", "en")
    assert first["project"] == second["project"]
    assert any("already exists" in c for c in second["caveats"])
    assert not any("already exists" in c for c in first.get("caveats", []))


def test_language_aliases(cli_fixtures, run_cli):
    cli_fixtures("scope_fasting")
    code, env = run_cli("scope", "Q1666254", "--langs", "cz,ua", "--ui", "en")
    assert set(env["facts"]) == {"cs", "uk"}
    assert sum("not a wiki language code" in c for c in env["caveats"]) == 2


def test_ambiguous_topic_asks(cli_fixtures, run_cli, wir_env):
    cli_fixtures("scope_mercury")
    code, env = run_cli("scope", "Mercury", "--langs", "de,fr", "--ui", "en")
    assert code == 2 and len(env["ask"]["options"]) >= 2
    assert all(o["cmd"].startswith("wir scope Q") for o in env["ask"]["options"])
    assert_cmds_parse(env)
    assert not (wir_env / "out").exists() or not any((wir_env / "out").glob("*/project.json"))


def test_wiktionary_asks_for_words(cli_fixtures, run_cli):
    cli_fixtures("scope_wiktionary")
    code, env = run_cli("scope", "fasting", "--source", "wiktionary", "--langs", "en,pl", "--ui", "en")
    assert code == 2 and "Wiktionary" in env["ask"]["question"]
    assert any('--set en="<word>"' in o["cmd"] for o in env["ask"]["options"])


def test_status_after_scope(cli_fixtures, run_cli):
    cli_fixtures("scope_fasting")
    run_cli("scope", "Q1666254", "--langs", "cs", "--ui", "uk")
    code, env = run_cli("status")
    assert code == 0 and env["facts"]["cs"]["status"] == "found" and env["next"][0]["cmd"] == "wir analyze"
    assert json.loads((__import__("pathlib").Path(env["files"]["project"])).read_text())["qid"] == "Q1666254"
