import hashlib
import re
import shlex
from pathlib import Path

from wir_core.cli import build_parser

ROOT = Path(__file__).resolve().parents[1]
SKILL = (ROOT / "SKILL.md").read_text("utf-8")
FORBIDDEN_IN_SKILL_DIR = ["roadmap", "needs_input", "answer_skeleton", "--from-run"]
# Names of other projects that must not appear in the shipped skill, stored as sha256 prefixes of the
# lower-case name so that this file does not name them either.
FORBIDDEN_NAME_HASHES = {"7300bbe1e2cae968", "5f6c80da67708cef", "ac4513f220dcadfa", "7ba711b22a780ecb",
                         "8a49a63072d6e30d", "3d40bb19795ea146"}
TOKEN = re.compile(r"[a-z0-9_]+(?:-[a-z0-9_]+)*")


def _name_hashes(text: str) -> set[str]:
    out = set()
    for token in set(TOKEN.findall(text.lower())):
        for candidate in {token, token.rstrip("0123456789")}:
            out.add(hashlib.sha256(candidate.encode()).hexdigest()[:16])
    return out


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


def _skill_files():
    for path in ROOT.rglob("*"):
        if (path.is_file() and "fixtures" not in path.parts and ".venv" not in path.parts
                and path.suffix in {".md", ".py", ".json", ".sh", ".toml"}):
            yield path


def test_no_forbidden_words_in_skill_dir():
    for path in _skill_files():
        if path.name == "test_skill_md.py":
            continue
        text = path.read_text("utf-8", errors="ignore")
        for word in FORBIDDEN_IN_SKILL_DIR:
            assert word.lower() not in text.lower(), f"'{word}' found in {path}"


def test_no_names_of_other_projects_in_skill_dir():
    for path in _skill_files():
        found = _name_hashes(path.read_text("utf-8", errors="ignore")) & FORBIDDEN_NAME_HASHES
        assert not found, f"a forbidden project name found in {path}"


def test_name_hashing_finds_a_name_in_any_case_and_with_a_number_suffix():
    target = hashlib.sha256(b"some-name").hexdigest()[:16]
    assert target in _name_hashes("see Some-Name42 here") and target not in _name_hashes("some names")


def test_references_exist_and_have_no_placeholders():
    for name in ("commands.md", "methodology.md", "limitations.md"):
        text = (ROOT / "references" / name).read_text("utf-8")
        assert "(paste" not in text and "TODO" not in text and "TBD" not in text
