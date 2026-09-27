"""Paths, version and environment-driven settings."""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

VERSION = "0.1.0"
# Contact for the Wikimedia User-Agent policy; users can override it with WIR_CONTACT.
DEFAULT_CONTACT = "https://github.com/vtlxx/wiki-interest-research"
# Audience-ranking weights (spec 6.9); shared by project.py (B04) and rank.py (B07).
DEFAULT_WEIGHTS = {"level": 0.35, "momentum": 0.35, "size": 0.2, "gap": 0.1}


def user_agent() -> str:
    contact = os.environ.get("WIR_CONTACT", "").strip() or DEFAULT_CONTACT
    return f"wiki-interest-research/{VERSION} ({contact}) python-httpx"


def skill_root() -> Path:
    return Path(__file__).resolve().parents[2]


def assets_dir() -> Path:
    return skill_root() / "assets"


def output_root() -> Path:
    env = os.environ.get("WIR_OUTPUT_DIR")
    return Path(env) if env else Path.cwd() / "wiki-interest-output"


def cache_dir() -> Path:
    env = os.environ.get("WIR_CACHE_DIR")
    if env:
        return Path(env)
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "wiki-interest-research"


def today_utc() -> date:
    pinned = os.environ.get("WIR_TODAY")
    if pinned:
        return date.fromisoformat(pinned)
    return datetime.now(timezone.utc).date()
