"""User-facing strings. Only en and uk are shipped; any other UI language falls back to en."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

SUPPORTED = ("en", "uk")
_DIR = Path(__file__).resolve().parent / "locales"


def ui_lang(ui: str | None) -> str:
    return ui if ui in SUPPORTED else "en"


@lru_cache(maxsize=None)
def _table(ui: str) -> dict:
    return json.loads((_DIR / f"{ui}.json").read_text("utf-8"))


def t(ui: str | None, key: str, **kw) -> str:
    table = _table(ui_lang(ui))
    template = table.get(key) or _table("en")[key]
    return template.format(**kw)


def lang_name(code: str, ui: str | None) -> str:
    return _table(ui_lang(ui))["langs"].get(code) or _table("en")["langs"].get(code) or code
