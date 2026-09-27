"""Strict check that every number the model wrote exists in the project's data (or is a rounding of it).

Numbers written as words ("forty-eight") are not checked; the sign is not checked either (the notes say
"fell by 47%", the data says "-47%")."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

SEP = "   ,"                 # thousands separators: space, NBSP, narrow NBSP, comma
NUM = re.compile(
    r"(?<![\w.,])(?P<sign>[-+−])?"
    rf"(?P<int>\d{{1,3}}(?:[{SEP}]\d{{3}})+(?!\d)|\d+)"
    r"(?:[.,](?P<frac>\d+))?"
    r"(?:\s?(?P<suf>тис\.?|тыс\.?|млн|млрд|k\b|K\b|M\b|bn\b))?")
SCALE = {"тис": 1e3, "тис.": 1e3, "тыс": 1e3, "тыс.": 1e3, "k": 1e3, "K": 1e3,
         "млн": 1e6, "M": 1e6, "млрд": 1e9, "bn": 1e9}
COMMENT = re.compile(r"<!--.*?-->", re.S)
ISO_DATE = re.compile(r"(?<!\d)(?P<y>\d{4})-(?P<m>\d{2})(?:-(?P<d>\d{2}))?(?!\d)")
# always allowed: "12 months", "52 weeks", "90% CI"
FIXED = (12, 52, 90)


@dataclass(frozen=True)
class Token:
    text: str
    value: float
    decimals: int
    scale: float
    pos: int = field(default=-1, compare=False)


def extract(text: str) -> list[Token]:
    tokens = []
    for m in NUM.finditer(COMMENT.sub(" ", text)):
        integer = re.sub(rf"[{SEP}]", "", m.group("int"))
        frac = m.group("frac") or ""
        scale = SCALE.get(m.group("suf") or "", 1.0)
        value = float(f"{integer}.{frac}" if frac else integer) * scale
        tokens.append(Token(m.group(0).strip(), value, len(frac), scale, m.start("int")))
    return tokens


def strings(obj) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in strings(v)]
    if isinstance(obj, (list, tuple)):
        return [s for v in obj for s in strings(v)]
    return []


def allowed_values(analysis: dict, summary: dict) -> list[float]:
    """Every number of say/facts/caveats, the window's years, the period, and the language/article counts."""
    values = {abs(t.value) for s in strings(summary) for t in extract(s)}
    start = date.fromisoformat(analysis["window"]["start"])
    end = date.fromisoformat(analysis["window"].get("last_day") or analysis["window"]["end"])
    values.update(range(start.year, end.year + 1))
    months = analysis["project"].get("period_months") or 24
    values.update({months, len(analysis["project"]["langs"]), *FIXED})
    if months % 12 == 0:
        values.add(months // 12)
    values.update(len(res.get("titles", [])) for res in analysis["langs"].values())
    usable = sum(1 for res in analysis["langs"].values() if res.get("usable"))
    if usable:
        values.add(usable)
    return sorted(float(v) for v in values)


def _ok(token: Token, allowed: list[float]) -> bool:
    tolerance = 0.5 * 10 ** (-token.decimals) * token.scale + 1e-9
    return any(abs(token.value - a) <= tolerance for a in allowed)


def _date_parts(text: str) -> set[int]:
    """Positions of the month/day parts of ISO dates: they are not numbers; the year is checked as one."""
    positions = set()
    for m in ISO_DATE.finditer(text):
        if 1 <= int(m.group("m")) <= 12 and (m.group("d") is None or 1 <= int(m.group("d")) <= 31):
            positions.update(m.start(g) for g in ("m", "d") if m.group(g))
    return positions


def check(text: str, allowed: list[float]) -> list[Token]:
    """Tokens that are neither a value of `allowed` (within rounding) nor the month/day of a date."""
    skip = _date_parts(COMMENT.sub(" ", text))
    return [tok for tok in extract(text) if tok.pos not in skip and not _ok(tok, allowed)]


def nearest(token: Token, allowed: list[float]) -> float | None:
    return min(allowed, key=lambda a: abs(a - token.value)) if allowed else None
