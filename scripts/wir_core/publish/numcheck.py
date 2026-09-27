"""Strict check that every number the model wrote exists in the project's data (or is a rounding of it).

Numbers written as words ("forty-eight") are not checked; the sign is not checked either (the notes say
"fell by 47%", the data says "-47%"). A percentage must match a percentage of the data; counts such as the
number of languages, "12 months" or the window's years are accepted only as plain numbers."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

SEP = "   ,"                 # thousands separators: space, NBSP, narrow NBSP, comma
NUM = re.compile(
    r"(?<![\w.,])(?P<sign>[-+−])?"
    rf"(?P<int>\d{{1,3}}(?:[{SEP}]\d{{3}})+(?!\d)|\d+)"
    r"(?:[.,](?P<frac>\d+))?"
    r"(?:\s?(?P<suf>тис\.|тис\b|тыс\.|тыс\b|тисяч\w*|млн\b|млрд\b|мільйон\w*|мільярд\w*|"
    r"thousand\b|million\b|billion\b|k\b|K\b|M\b|bn\b))?")
SCALE = [("тис", 1e3), ("тыс", 1e3), ("thousand", 1e3), ("k", 1e3), ("K", 1e3), ("млн", 1e6), ("мільйон", 1e6),
         ("million", 1e6), ("M", 1e6), ("млрд", 1e9), ("мільярд", 1e9), ("billion", 1e9), ("bn", 1e9)]
PERCENT = re.compile(r"\s?%|\s*(?:percent|per cent|відсот|процент)", re.I)
CI_LABEL = re.compile(r"\s?%\s*(?:CI|ДІ|ДИ|confidence|довір)", re.I)
# the start of an interval whose end is a percentage ("-55…-38%") is a percentage too
RANGE_TO_PERCENT = re.compile(r"\s?(?:…|\.\.\.?|–|—|-)\s?[-+−]?\d[\d.,]*\s?%")
COMMENT = re.compile(r"<!--.*?-->", re.S)
ISO_DATE = re.compile(r"(?<!\d)(?P<y>\d{4})-(?P<m>\d{2})(?:-(?P<d>\d{2}))?(?!\d)")
DMY_DATE = re.compile(r"(?<![\d.])(?P<d>\d{2})\.(?P<m>\d{2})\.\d{4}(?!\d)")
FIXED = (12, 52, 90)                        # "12 months", "52 weeks", "90% CI"
UNITS = (1e3, 1e6)                          # "per 1 million", "на 1 тис." — only right after per/на/за or "/"
PER = re.compile(r"(?:\bper|\bна|\bза|/)\s*$", re.I)


@dataclass(frozen=True)
class Token:
    text: str
    value: float
    decimals: int
    scale: float
    pos: int = field(default=-1, compare=False)
    percent: bool = field(default=False, compare=False)
    per: bool = field(default=False, compare=False)


class Allowed(list):
    """All allowed values (plain numbers may match any of them); `.percent` = the ones a percentage may match."""
    percent: list[float]


def _scale(suffix: str | None) -> float:
    return next((mult for prefix, mult in SCALE if suffix and suffix.startswith(prefix)), 1.0)


def extract(text: str) -> list[Token]:
    text = COMMENT.sub(" ", text)
    tokens = []
    for m in NUM.finditer(text):
        integer = re.sub(rf"[{SEP}]", "", m.group("int"))
        frac = m.group("frac") or ""
        scale = _scale(m.group("suf"))
        value = float(f"{integer}.{frac}" if frac else integer) * scale
        after = text[m.end():]
        percent = bool(PERCENT.match(after) or RANGE_TO_PERCENT.match(after)) and not CI_LABEL.match(after)
        per = bool(PER.search(text[:m.start()]))
        tokens.append(Token(m.group(0).strip(), value, len(frac), scale, m.start("int"), percent, per))
    return tokens


def _date_parts(text: str) -> set[int]:
    """Positions of the month/day parts of dates: they are not numbers; an ISO date's year is checked as one."""
    positions = set()
    for m in ISO_DATE.finditer(text):
        if 1 <= int(m.group("m")) <= 12 and (m.group("d") is None or 1 <= int(m.group("d")) <= 31):
            positions.update(m.start(g) for g in ("m", "d") if m.group(g))
    for m in DMY_DATE.finditer(text):
        if 1 <= int(m.group("m")) <= 12 and 1 <= int(m.group("d")) <= 31:
            positions.add(m.start("d"))     # "01.09" reads as one number; the year after the dot is skipped
    return positions


def numbers(text: str) -> list[Token]:
    """Tokens of `text` without the parts of dates."""
    skip = _date_parts(COMMENT.sub(" ", text))
    return [tok for tok in extract(text) if tok.pos not in skip]


def strings(obj) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in strings(v)]
    if isinstance(obj, (list, tuple)):
        return [s for v in obj for s in strings(v)]
    return []


def allowed_values(analysis: dict, summary: dict) -> Allowed:
    """Numbers of say/facts/caveats (percentages kept apart), plus counts that may appear as plain numbers:
    the window's years, the period, languages and articles, units and numbers in the topic's own names."""
    data = [tok for s in strings(summary) for tok in numbers(s)]
    values = {tok.value for tok in data}
    start = date.fromisoformat(analysis["window"]["start"])
    end = date.fromisoformat(analysis["window"].get("last_day") or analysis["window"]["end"])
    values.update(range(start.year, end.year + 1))
    proj = analysis["project"]
    months = proj.get("period_months") or 24
    values.update({months, len(proj["langs"]), *FIXED})
    if months % 12 == 0:
        values.add(months // 12)
    values.update(len(res.get("titles", [])) for res in analysis["langs"].values())
    usable = sum(1 for res in analysis["langs"].values() if res.get("usable"))
    if usable:
        values.add(usable)
    names = [proj.get("label") or "", proj.get("topic") or ""] + [
        x["title"] for res in analysis["langs"].values() for x in res.get("titles", [])]
    values.update(tok.value for name in names for tok in extract(name))
    allowed = Allowed(sorted(float(v) for v in values))
    allowed.percent = sorted({tok.value for tok in data if tok.percent})
    return allowed


def _candidates(token: Token, allowed: list[float]) -> list[float]:
    return getattr(allowed, "percent", allowed) if token.percent else allowed


def _ok(token: Token, allowed: list[float]) -> bool:
    tolerance = 0.5 * 10 ** (-token.decimals) * token.scale + 1e-9
    if token.per and any(abs(token.value - u) <= tolerance for u in UNITS):
        return True
    return any(abs(token.value - a) <= tolerance for a in _candidates(token, allowed))


def check(text: str, allowed: list[float]) -> list[Token]:
    """Tokens that are neither a value of `allowed` (within rounding) nor part of a date."""
    return [tok for tok in numbers(text) if not _ok(tok, allowed)]


def nearest_values(token: Token, allowed: list[float], k: int = 3) -> list[float]:
    """Closest values the token could be replaced with; a year is suggested only for something that looks like one."""
    def is_year(v: float) -> bool:
        return 1900 <= v <= 2100 and float(v).is_integer()

    looks_like_year = token.scale == 1 and is_year(token.value)
    pool = [a for a in _candidates(token, allowed) if looks_like_year or not is_year(a)]
    return sorted(pool, key=lambda a: abs(a - token.value))[:k]


def nearest(token: Token, allowed: list[float]) -> float | None:
    found = nearest_values(token, allowed, 1)
    return found[0] if found else None
