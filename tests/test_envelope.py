import io
import json

from wir_core import envelope
from wir_core.errors import EXIT_NETWORK, WirError


def test_make_omits_empty_keys():
    env = envelope.make("ready", project="p", say=["a"], facts={}, caveats=[])
    assert env == {"ok": True, "state": "ready", "project": "p", "say": ["a"]}


def test_make_input_required_is_ok_true():
    env = envelope.make("input_required", ask={"question": "q", "options": []})
    assert env["ok"] is True and env["state"] == "input_required"


def test_from_error_sets_failed_and_exit():
    env = envelope.from_error(WirError("RATE_LIMITED", "slow down", fix="wir analyze --offline", exit_code=EXIT_NETWORK))
    assert env["ok"] is False and env["state"] == "failed"
    assert env["error"] == {"code": "RATE_LIMITED", "message": "slow down", "fix": "wir analyze --offline"}
    out = io.StringIO()
    assert envelope.emit(env, stream=out) == EXIT_NETWORK
    assert "_exit" not in json.loads(out.getvalue())


def test_emit_exit_codes_by_state():
    assert envelope.emit(envelope.make("ready"), stream=io.StringIO()) == 0
    assert envelope.emit(envelope.make("input_required"), stream=io.StringIO()) == 2


def test_emit_single_json_line():
    out = io.StringIO()
    envelope.emit(envelope.make("ready", say=["привіт"]), stream=out)
    text = out.getvalue()
    assert text.count("\n") == 1
    assert json.loads(text)["say"] == ["привіт"]


def test_emit_shrinks_to_max_bytes():
    env = envelope.make("ready", say=[f"sentence {i} " + "x" * 200 for i in range(40)],
                        caveats=[f"caveat {i} " + "y" * 200 for i in range(40)])
    out = io.StringIO()
    envelope.emit(env, stream=out)
    text = out.getvalue().strip()
    assert len(text.encode()) <= envelope.MAX_BYTES
    data = json.loads(text)
    assert data["caveats"][-1].startswith("Output truncated")


def test_emit_clips_long_strings_to_max_bytes():
    env = envelope.from_error(WirError("INTERNAL", "RuntimeError: " + "z" * 6000))
    env["say"] = ["x" * 5000]
    out = io.StringIO()
    envelope.emit(env, stream=out)
    text = out.getvalue().strip()
    assert len(text.encode()) <= envelope.MAX_BYTES
    data = json.loads(text)
    assert data["error"]["code"] == "INTERNAL" and data["error"]["message"].startswith("RuntimeError: z")


def test_emit_serializes_paths(tmp_path):
    out = io.StringIO()
    envelope.emit(envelope.make("ready", files={"data": tmp_path / "analysis.json"}), stream=out)
    assert json.loads(out.getvalue())["files"]["data"] == str(tmp_path / "analysis.json")
