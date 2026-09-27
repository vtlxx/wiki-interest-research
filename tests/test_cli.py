import types

import pytest

from wir_core import cli


def test_parser_scope_flags():
    args = cli.build_parser().parse_args(
        ["scope", "intermittent fasting", "--langs", "pl,cs", "--ui", "uk", "--period", "24m",
         "--set", 'pl=Głodówka lecznicza', "--add-lang", "sk", "--fork"])
    assert args.command == "scope" and args.topic == "intermittent fasting"
    assert args.set_title == ["pl=Głodówka lecznicza"] and args.add_lang == ["sk"] and args.fork


@pytest.mark.parametrize("argv", [["analyze", "--offline", "--weights", "momentum=0.6"],
                                  ["verify"], ["publish", "--notes", "n.md"], ["status"]])
def test_parser_other_commands(argv):
    assert cli.build_parser().parse_args(argv).command == argv[0]


def test_bad_args_json_error(wir_env, run_cli):
    code, env = run_cli("scope", "--bogus")
    assert code == 3 and env["state"] == "failed" and env["error"]["code"] == "BAD_ARGS"


def test_not_implemented(wir_env, run_cli, monkeypatch):
    monkeypatch.setitem(cli.COMMANDS, "status", ("wir_core.does_not_exist", "run_status"))
    code, env = run_cli("status")
    assert code == 3 and env["error"]["code"] == "NOT_IMPLEMENTED"


def test_internal_error_is_json(wir_env, run_cli, monkeypatch):
    fake = types.ModuleType("wir_core._boom")
    fake.run = lambda args: 1 / 0
    monkeypatch.setitem(__import__("sys").modules, "wir_core._boom", fake)
    monkeypatch.setitem(cli.COMMANDS, "status", ("wir_core._boom", "run"))
    code, env = run_cli("status")
    assert code == 3 and env["error"]["code"] == "INTERNAL"
    assert "ZeroDivisionError" in env["error"]["message"]


def test_command_result_emitted(wir_env, run_cli, monkeypatch):
    fake = types.ModuleType("wir_core._ok")
    fake.run = lambda args: {"ok": True, "state": "ready", "say": ["done"]}
    monkeypatch.setitem(__import__("sys").modules, "wir_core._ok", fake)
    monkeypatch.setitem(cli.COMMANDS, "status", ("wir_core._ok", "run"))
    assert run_cli("status") == (0, {"ok": True, "state": "ready", "say": ["done"]})


def test_unemittable_result_is_json(wir_env, run_cli, monkeypatch):
    fake = types.ModuleType("wir_core._none")
    fake.run = lambda args: None
    monkeypatch.setitem(__import__("sys").modules, "wir_core._none", fake)
    monkeypatch.setitem(cli.COMMANDS, "status", ("wir_core._none", "run"))
    code, env = run_cli("status")
    assert code == 3 and env["error"]["code"] == "INTERNAL"
