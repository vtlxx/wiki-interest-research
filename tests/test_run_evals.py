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
