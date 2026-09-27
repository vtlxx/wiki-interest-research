"""The real entry point as agents call it: bash wrapper -> uv -> wir.py, via a symlinked skill dir."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(shutil.which("uv") is None or shutil.which("bash") is None,
                                reason="needs uv and bash")


def _run(cmd, cwd, env=None):
    proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    assert len(lines) == 1, f"expected one JSON line, got: {proc.stdout!r} / stderr {proc.stderr!r}"
    return proc.returncode, json.loads(lines[0])


def test_wrapper_through_symlinked_skill_dir(tmp_path):
    skills = tmp_path / "my project" / ".claude" / "skills"
    skills.mkdir(parents=True)
    (skills / "wiki-interest-research").symlink_to(SKILL, target_is_directory=True)
    code, env = _run([".claude/skills/wiki-interest-research/scripts/wir", "scope", "--bogus"], cwd=skills.parents[1])
    assert code == 3 and env["error"]["code"] == "BAD_ARGS"


def test_wrapper_through_symlinked_script(tmp_path):
    (tmp_path / "wir").symlink_to(SKILL / "scripts" / "wir")
    code, env = _run([str(tmp_path / "wir"), "scope", "--bogus"], cwd=tmp_path)
    assert code == 3 and env["error"]["code"] == "BAD_ARGS"


def test_wrapper_utf8_output_under_ascii_locale(tmp_path):
    env = dict(os.environ, LC_ALL="C", LANG="C", PYTHONIOENCODING="ascii")
    code, out = _run([str(SKILL / "scripts" / "wir"), "scope", "--source", "ґ"], cwd=tmp_path, env=env)
    assert code == 3 and "ґ" in out["error"]["message"]


def test_wrapper_without_uv(tmp_path):
    env = dict(os.environ, PATH="/usr/bin:/bin")
    code, out = _run([str(SKILL / "scripts" / "wir"), "status"], cwd=tmp_path, env=env)
    assert code == 3 and out["error"]["code"] == "UV_MISSING"
