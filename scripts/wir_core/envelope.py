"""The single JSON object every command prints."""
from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from .errors import EXIT_INPUT, EXIT_OK, EXIT_USAGE, WirError

MAX_BYTES = 3000
TRUNCATED_NOTE = "Output truncated — the full details are in the project files."


def make(state: str, *, project: Any = None, say=None, facts=None, caveats=None, ask=None,
         next_=None, files=None, error=None) -> dict:
    env: dict[str, Any] = {"ok": state != "failed", "state": state}
    if project:
        env["project"] = str(project)
    for key, value in (("say", say), ("facts", facts), ("caveats", caveats), ("ask", ask),
                       ("next", next_), ("files", files), ("error", error)):
        if value:
            env[key] = value
    return env


def from_error(err: WirError, project: Any = None) -> dict:
    error = {"code": err.code, "message": err.message}
    if err.fix:
        error["fix"] = err.fix
    env = make("failed", project=project, error=error)
    env["_exit"] = err.exit_code
    return env


def _dumps(env: dict) -> str:
    return json.dumps(env, ensure_ascii=False, separators=(",", ":"), default=str)


def _size(env: dict) -> int:
    return len(_dumps(env).encode())


def _clip(value: Any, limit: int) -> Any:
    if isinstance(value, str):
        return value if len(value) <= limit else value[: limit - 1] + "…"
    if isinstance(value, list):
        return [_clip(v, limit) for v in value]
    if isinstance(value, dict):
        return {k: _clip(v, limit) for k, v in value.items()}
    return value


def fit(env: dict, optional: list[tuple[str, str]], note: str) -> dict:
    """Append optional (key, line) items in priority order while the output stays within the size limit;
    items that do not fit are skipped and replaced by one `note` (so _shrink never has to cut blindly)."""
    limit = MAX_BYTES - 120 - len(_dumps(note).encode()) - 1
    skipped = False
    for key, value in optional:
        env.setdefault(key, []).append(value)
        if _size(env) > limit:
            env[key].pop()
            skipped = True
    if skipped:
        env.setdefault("caveats", []).append(note)
    return env


def _shrink(env: dict) -> dict:
    truncated = False
    for key in ("caveats", "say", "next"):
        while key in env and len(env[key]) > 1 and _size(env) > MAX_BYTES - 120:
            env[key] = env[key][:-1]
            truncated = True
    if _size(env) > MAX_BYTES - 120 and "facts" in env:
        env["facts"] = {"see": "analysis.json"}
        truncated = True
    # Last resort: shorten long texts. ask/next/files hold commands and paths, so they stay intact.
    for limit in (400, 200, 100, 40):
        if _size(env) <= MAX_BYTES - 120:
            break
        for key in ("say", "facts", "caveats", "error"):
            if key in env:
                env[key] = _clip(env[key], limit)
        truncated = True
    if truncated:
        env.setdefault("caveats", []).append(TRUNCATED_NOTE)
    return env


def emit(env: dict, stream: TextIO | None = None) -> int:
    stream = stream or sys.stdout
    exit_code = env.pop("_exit", None)
    env = _shrink(env)
    stream.write(_dumps(env) + "\n")
    stream.flush()
    if exit_code is not None:
        return exit_code
    return {"ready": EXIT_OK, "input_required": EXIT_INPUT}.get(env["state"], EXIT_USAGE)
