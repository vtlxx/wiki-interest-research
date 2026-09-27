import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


@pytest.fixture(autouse=True)
def _no_ambient_record_replay(monkeypatch):
    """A developer's exported WIR_RECORD / WIR_FIXTURES must not leak into unit tests."""
    monkeypatch.delenv("WIR_RECORD", raising=False)
    monkeypatch.delenv("WIR_FIXTURES", raising=False)


@pytest.fixture
def wir_env(monkeypatch, tmp_path):
    """Isolate cache, output dir and 'today' for every test that runs commands."""
    monkeypatch.setenv("WIR_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("WIR_OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("WIR_TODAY", "2026-09-27")
    monkeypatch.setenv("WIR_CONTACT", "tests")
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def run_cli(capsys):
    """Run `wir` in-process; returns (exit_code, parsed JSON). Asserts exactly one JSON line on stdout."""
    from wir_core import cli

    def _run(*argv: str):
        capsys.readouterr()
        code = cli.main(list(argv))
        out = capsys.readouterr().out
        lines = [line for line in out.splitlines() if line.strip()]
        assert len(lines) == 1, f"expected one JSON line, got: {out!r}"
        return code, json.loads(lines[0])

    return _run
