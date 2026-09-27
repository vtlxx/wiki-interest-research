import re
import shlex
from pathlib import Path

from wir_core.cli import build_parser

ROOT = Path(__file__).resolve().parents[1]
SKILL = (ROOT / "SKILL.md").read_text("utf-8")


def top_level_keys() -> set[str]:
    head = SKILL.split("---")[1]
    return set(re.findall(r"^([a-z_-]+):", head, re.M))      # indented (nested/continued) lines are ignored


def test_frontmatter_only_spec_fields():
    assert top_level_keys() <= {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
    assert re.search(r"^name: wiki-interest-research$", SKILL, re.M)


def test_body_budget():
    body = SKILL.split("---", 2)[2]
    assert len(body.splitlines()) <= 200
    assert len(body) / 4 <= 2600          # ≈ tokens


def test_every_command_example_parses():
    commands = [c for c in re.findall(r"`(wir [^`]+)`", SKILL) if "--help" not in c]
    assert len(commands) >= 15
    parser = build_parser()
    for cmd in commands:
        cmd = re.sub(r"<[^>]+>", "x", cmd)          # placeholders like <topic>
        parser.parse_args(shlex.split(cmd)[1:])


def test_references_exist_and_have_no_placeholders():
    for name in ("commands.md", "methodology.md", "limitations.md"):
        text = (ROOT / "references" / name).read_text("utf-8")
        assert "(paste" not in text and "TODO" not in text and "TBD" not in text
