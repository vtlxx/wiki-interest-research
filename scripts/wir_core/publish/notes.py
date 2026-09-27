"""Parse the model-written notes.md into sections, with limits that keep the PDF on one page."""
from __future__ import annotations

import re

from ..errors import EXIT_USAGE, WirError
from ..i18n import SUPPORTED, t

LIMITS = {"conclusion": 420, "recommendation": 420, "next": 260}
KEYS = {"conclusion": "notes.h.conclusion", "recommendation": "notes.h.recommendation", "next": "notes.h.next"}
COMMENT = re.compile(r"<!--.*?-->", re.S)
HEADING = re.compile(r"^#{1,3}\s*(.+?)\s*$")


def _clean(heading: str) -> str:
    return heading.strip("*_ ").rstrip(":").strip("*_ ").casefold()


def _heading_map() -> dict[str, str]:
    return {t(ui, name).casefold(): key for ui in SUPPORTED for key, name in KEYS.items()}


def _names(key: str) -> str:
    return " / ".join(f"'{t(ui, KEYS[key])}'" for ui in SUPPORTED)


def parse_notes(text: str) -> dict[str, str]:
    headings = _heading_map()
    sections: dict[str, list[str]] = {}
    current = None
    for line in COMMENT.sub("", text).splitlines():
        m = HEADING.match(line)
        if m:
            current = headings.get(_clean(m.group(1)))
            if current:
                sections[current] = []
            continue
        if current:
            sections[current].append(line)
    out = {k: " ".join(" ".join(v).split()) for k, v in sections.items() if " ".join(v).strip()}
    missing = [k for k in ("conclusion", "recommendation") if k not in out]
    if missing:
        raise WirError("NOTES_INCOMPLETE", f"notes.md lacks the section(s): {', '.join(missing)}",
                       fix=f"Write text under the heading(s) {', '.join(_names(k) for k in missing)} in notes.md "
                           "(keep the headings), then run wir publish again.", exit_code=EXIT_USAGE)
    for key, body in out.items():
        if len(body) > LIMITS[key]:
            raise WirError("NOTES_TOO_LONG", f"section '{key}' has {len(body)} characters (limit {LIMITS[key]})",
                           fix=f"Shorten the {_names(key)} section of notes.md to at most {LIMITS[key]} characters, "
                               "then run wir publish again.", exit_code=EXIT_USAGE)
    return out
