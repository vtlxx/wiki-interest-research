import json
from pathlib import Path

from wir_core import pipeline
from wir_core.net import BudgetExceeded


def load_analysis(env):
    return json.loads(Path(env["files"]["data"]).read_text())


def analyze_until_ready(run_cli, *args, attempts=6):
    """Large projects exceed the 90 s budget in record mode; the CLI then asks to run analyze again."""
    for _ in range(attempts):
        code, env = run_cli("analyze", *args)
        if not any(n["cmd"] == "wir analyze" for n in env.get("next", [])):
            return code, env
    raise AssertionError("analyze never finished")


def test_fasting_cs_end_to_end(cli_fixtures, run_cli):
    cli_fixtures("analyze_fasting")
    run_cli("scope", "Q1666254", "--langs", "pl,cs", "--ui", "uk")
    run_cli("scope", "--drop-lang", "pl")
    code, env = analyze_until_ready(run_cli)
    assert code == 0 and env["state"] == "ready"
    assert "cs" in env["facts"] and env["facts"]["cs"]["growth"] != "—"
    a = load_analysis(env)
    assert a["schema"] == 1 and a["langs"]["cs"]["trust"]["level"] in ("high", "medium", "low")
    assert a["langs"]["cs"]["monthly"] and a["provenance"]["params"] == {"agent": "user", "access": "all-access"}
    proj = Path(env["project"])
    for name in ("series_daily.csv", "series_monthly.csv", "notes.template.md"):
        assert (proj / name).exists()
    assert any(n["cmd"] == "wir publish" for n in env["next"])
    assert len(json.dumps(env, ensure_ascii=False).encode()) <= 3000


def test_offline_rerun_and_verify(cli_fixtures, run_cli, monkeypatch):
    cli_fixtures("analyze_fasting")
    run_cli("scope", "Q1666254", "--langs", "cs", "--ui", "en")
    _, env = analyze_until_ready(run_cli)
    proj = Path(env["project"])
    monkeypatch.delenv("WIR_RECORD", raising=False)
    monkeypatch.setenv("WIR_FIXTURES", "/nonexistent")   # any network use would now fail loudly
    code, env = run_cli("analyze", "--offline")
    assert code == 0 and "cs" in env["facts"]
    assert load_analysis(env)["provenance"]["requests"] == 0
    code, env = run_cli("verify")
    assert code == 0 and env["facts"]["cs"]["verify"] in ("the verdict holds", "the verdict weakens",
                                                          "the verdict reverses")
    assert load_analysis(env)["langs"]["cs"]["verify"]["variants"]["half_year"] is not None
    assert "Czech: robustness check" in (proj / "notes.template.md").read_text("utf-8")   # fallback when trimmed
    (proj / ".stale").write_text("")
    code, env = run_cli("verify")
    assert code == 5 and env["error"]["code"] == "STALE_ANALYSIS"
    code, env = run_cli("analyze", "--offline")
    assert code == 0 and not (proj / ".stale").exists()


def test_multi_language_ranking(cli_fixtures, run_cli):
    cli_fixtures("analyze_english")
    run_cli("scope", "Q1860", "--langs", "pl,cs,de,uk", "--ui", "en")
    code, env = analyze_until_ready(run_cli, "--weights", "momentum=0.6,level=0.2")
    a = load_analysis(env)
    assert code == 0 and len(a["ranking"]) == 4 and a["weights"]["momentum"] == 0.6
    assert any("Audiences to explore next" in s for s in a["summary"]["say"]) or not any(r["eligible"] for r in a["ranking"])
    assert all(a["langs"][l]["trend"] is None or a["langs"][l]["trend"]["q"] is not None for l in ("pl", "cs", "de", "uk"))
    assert len({a["langs"][l]["monthly"][-1]["month"] for l in ("pl", "cs", "de", "uk")}) == 1   # one shared window
    for name in ("Polish:", "Czech:", "German:", "Ukrainian:"):             # every headline survives the 3 KB limit
        assert any(s.startswith(name) for s in env["say"])
    assert env["caveats"][:2] == a["summary"]["caveats"][:2]
    code, env = run_cli("verify")
    assert code == 0 and all(f["verify"] for f in env["facts"].values())
    for name in ("Polish:", "Czech:", "German:", "Ukrainian:"):
        assert any(s.startswith(name) for s in env["say"])
    assert env["caveats"][:2] == a["summary"]["caveats"][:2]


def test_analyze_without_usable_langs(cli_fixtures, run_cli):
    cli_fixtures("analyze_fasting")
    run_cli("scope", "Q1666254", "--langs", "pl", "--ui", "en")
    code, env = run_cli("analyze")
    assert code == 5 and env["error"]["code"] == "NOTHING_TO_ANALYZE"


def test_time_budget_asks_to_continue_but_a_lasting_429_is_an_error(cli_fixtures, run_cli, monkeypatch):
    cli_fixtures("analyze_fasting")
    run_cli("scope", "Q1666254", "--langs", "cs", "--ui", "en")

    def out_of_time(status):
        def fetch(*_args, **_kw):
            raise BudgetExceeded(status)
        return fetch

    monkeypatch.setattr(pipeline, "fetch_lang", out_of_time(None))
    code, env = run_cli("analyze")
    assert code == 0 and env["next"] == [{"why": env["next"][0]["why"], "cmd": "wir analyze"}]
    assert "0 of 1" in env["say"][0]
    monkeypatch.setattr(pipeline, "fetch_lang", out_of_time(429))
    code, env = run_cli("analyze")
    assert code == 4 and env["error"]["code"] == "RATE_LIMITED"
