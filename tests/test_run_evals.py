import json
from pathlib import Path

from wir_core.cli import build_parser

ROOT = Path(__file__).resolve().parents[1]
EVALS = json.loads((ROOT / "evals" / "evals.json").read_text("utf-8"))


def _subcommands() -> set[str]:
    parser = build_parser()
    action = next(a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction")
    return set(action.choices)


def test_evals_use_real_subcommands_and_known_checks():
    commands, known = _subcommands(), set(EVALS["check_defaults"]) | {"commands_in_order", "max_tool_calls"}
    ids = [e["id"] for e in EVALS["evals"]]
    assert len(ids) == len(set(ids)) == 12
    for e in EVALS["evals"]:
        assert set(e["checks"]) <= known, e["id"]
        assert set(e["checks"]["commands_in_order"]) <= commands, e["id"]
        assert e["turns"] and all(t["prompt"].strip() for t in e["turns"])


def test_continued_scenarios_point_to_an_earlier_one():
    seen = set()
    for e in EVALS["evals"]:
        if "continues" in e:
            assert e["continues"] in seen, e["id"]
        seen.add(e["id"])


def test_command_orders_follow_the_skill_workflow():
    """analyze is followed by verify (SKILL.md step 4); publish comes after verify; a new project starts with scope."""
    for e in EVALS["evals"]:
        order = e["checks"]["commands_in_order"]
        for i, cmd in enumerate(order):
            if cmd == "analyze":
                assert "verify" in order[i + 1:], e["id"]
            if cmd == "publish":
                assert "verify" in order[:i], e["id"]
        if order and "continues" not in e:
            assert order[0] == "scope", e["id"]
        assert e["checks"]["max_tool_calls"] >= len(order) + 1, e["id"]   # + reading SKILL.md


# ---- harness: pure parts --------------------------------------------------------------------
import sys  # noqa: E402

sys.path.insert(0, str(ROOT / "evals"))
import run_evals as rv  # noqa: E402

E = {e["id"]: e for e in EVALS["evals"]}


def test_plan_keeps_chains_in_one_session_and_orders_attempts():
    sessions = rv.plan_sessions(EVALS["evals"], attempts=3)
    chains = [[e["id"] for e in s.evals] for s in sessions if s.attempt == 1]
    assert ["E1", "E4"] in chains and ["E3", "E5"] in chains and ["E4"] not in chains
    assert len(sessions) == 3 * 10 and [s.attempt for s in sessions] == sorted(s.attempt for s in sessions)
    only = rv.plan_sessions(EVALS["evals"], attempts=1, only={"E4", "E7"})
    assert [[e["id"] for e in s.evals] for s in only] == [["E1", "E4"], ["E7"]]
    assert only[0].key == "E1+E4-1"


def test_needs_reply():
    ask = {"state": "input_required", "ask": {"question": "?"}}
    missing = {"state": "failed", "error": {"code": "MISSING_LANGS"}}
    analysed = {"state": "ready", "files": {"data": "a/analysis.json"}}
    assert rv.needs_reply([ask]) and rv.needs_reply([missing]) and rv.needs_reply([])
    assert rv.needs_reply([{"state": "ready", "say": ["scope ok"]}])     # stopped before analysing
    assert not rv.needs_reply([ask, {"state": "ready"}, analysed])


CTX = rv.Ctx(home="/Users/jdoe", work=["/private/var/folders/x/T/wir-eval-1", "/var/folders/x/T/wir-eval-1"],
             user="jdoe", host="jdoes-mbp.local", sessions=["3b5003a7-57bf-4fda-8b99-cfe0bdd7823b"],
             contact="jd@example.org")


def test_scrub_and_find_leaks():
    raw = json.dumps({"cwd": "/private/var/folders/x/T/wir-eval-1", "sessionId": "3b5003a7-57bf-4fda-8b99-cfe0bdd7823b",
                      "text": json.dumps({"p": "/Users/jdoe/progs/skill/SKILL.md", "who": "JDoe on jdoes-mbp.local",
                                          "mail": "Mail me: john.doe@corp.example", "ua": "(jd@example.org)"}),
                      "uuid": "0f8fad5b-d9cb-469f-a165-70867728950e"})
    assert set(rv.find_leaks(raw, CTX)) >= {"/Users/", "email", "home", "user", "host", "session", "contact"}
    clean = rv.scrub(raw, CTX)
    assert rv.find_leaks(clean, CTX) == []
    for token in ("<work>", "<home>/progs/skill/SKILL.md", "<user> on <host>", "<email>", "<session>", "<uuid>"):
        assert token in clean
    assert "wir-eval" not in clean


def _prompt(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def test_split_turns():
    events = [_prompt("first"), {"type": "assistant", "message": {"content": [{"type": "text", "text": "a"}]}},
              _prompt("reply"), {"type": "system"}, _prompt("second"),
              {"type": "assistant", "message": {"content": [{"type": "text", "text": "b"}]}}]
    parts = rv.split_turns(events, {"E1": "first", "E4": "second"})
    assert [len(parts["E1"]), len(parts["E4"])] == [4, 2] and parts["E4"][0]["message"]["content"] == "second"


def test_summarize_totals():
    def res(eid, attempt, verdict, failed=(), calls=5, secs=60.0, cost=0.2):
        checks = [rv.Check("a", "PASS")] + [rv.Check(f, "FAIL") for f in failed]
        return rv.Result(eid, attempt, verdict, checks, calls, secs, cost)
    results = [res("E1", 1, "PASS"), res("E1", 2, "FAIL", ["must_ask"], calls=7),
               res("E1", 3, "INVALID"), res("E2", 1, "PASS", cost=0.4)]
    text = rv.summarize(results, {"claude": "2.1.247", "model": "claude-haiku-4-5-20251001", "date": "2026-09-27"})
    assert "| E1 | 1/2 | 2/3 | 6.0 | 60 s | $0.20 | must_ask ×1 |" in text
    assert "| E2 | 1/1 | 1/1 | 5.0 | 60 s | $0.40 | — |" in text
    assert "Scenario attempts passed: 2/3" in text and "INVALID: E1-3" in text and "total cost (API-equivalent): $1.00" in text
