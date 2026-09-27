import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wir_core.cache import Cache  # noqa: E402
from wir_core.fixtures import FixtureTransport  # noqa: E402
from wir_core.net import HttpClient  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REAL_CONTACT = os.environ.get("WIR_CONTACT")  # wir_env replaces it; live recording must not send a fake contact


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


@pytest.fixture
def recorded_client(tmp_path, monkeypatch):
    """HttpClient replaying tests/fixtures/<name>/; with WIR_REFRESH_FIXTURES=1 it records live instead."""
    monkeypatch.setenv("WIR_TODAY", os.environ.get("WIR_FIXTURE_TODAY", "2026-09-27"))

    def _make(name: str) -> HttpClient:
        directory = FIXTURES / name
        if os.environ.get("WIR_REFRESH_FIXTURES") == "1":
            return HttpClient(Cache(tmp_path / f"{name}.sqlite"), record_dir=directory)
        return HttpClient(Cache(tmp_path / f"{name}.sqlite"), transport=FixtureTransport([directory]),
                          min_interval=0)

    return _make


@pytest.fixture
def cli_fixtures(monkeypatch, wir_env):
    """In-process CLI runs replay tests/fixtures/<name>/ (or record into it with WIR_REFRESH_FIXTURES=1)."""
    def _use(name: str) -> Path:
        directory = FIXTURES / name
        if os.environ.get("WIR_REFRESH_FIXTURES") == "1":
            monkeypatch.setenv("WIR_RECORD", str(directory))
            monkeypatch.delenv("WIR_FIXTURES", raising=False)
            if REAL_CONTACT:
                monkeypatch.setenv("WIR_CONTACT", REAL_CONTACT)
            else:
                monkeypatch.delenv("WIR_CONTACT", raising=False)  # user agent falls back to DEFAULT_CONTACT
        else:
            monkeypatch.setenv("WIR_FIXTURES", str(directory))
        return directory
    return _use
