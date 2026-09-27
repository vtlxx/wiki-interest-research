"""Known Wikimedia data problems (assets/incidents.json) and overlap checks."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

from .config import assets_dir


@dataclass(frozen=True)
class Incident:
    id: str
    start: date
    end: date
    projects: list[str]
    type: str
    severity: str
    note_en: str
    note_uk: str
    source: str | None


@lru_cache(maxsize=1)
def _load_cached() -> tuple[Incident, ...]:
    raw = json.loads((assets_dir() / "incidents.json").read_text("utf-8"))
    return tuple(Incident(r["id"], date.fromisoformat(r["start"]), date.fromisoformat(r["end"]), list(r["projects"]),
                          r["type"], r["severity"], r["note_en"], r["note_uk"], r.get("source")) for r in raw)


def load() -> list[Incident]:
    return list(_load_cached())


def overlapping(lang: str, start: date, end: date, severities: set[str] | None = None) -> list[Incident]:
    return [i for i in _load_cached()
            if ("*" in i.projects or lang in i.projects) and i.start <= end and i.end >= start
            and (severities is None or i.severity in severities)]
