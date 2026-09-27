"""Number/date formatting shared by say/facts, charts and reports (the only place numbers become text)."""
from __future__ import annotations

from datetime import date


def pct(x: float | None, signed: bool = True) -> str:
    if x is None:
        return "—"
    v = round(x * 100)
    sign = "+" if (v > 0 and signed) else ("-" if v < 0 else "")
    return f"{sign}{abs(v)}%"


def ci(lo: float | None, hi: float | None) -> str:
    if lo is None or hi is None:
        return "—"
    return f"{pct(lo)[:-1]}…{pct(hi)}"


def integer(n: float | None, ui: str) -> str:
    if n is None:
        return "—"
    text = f"{int(round(n)):,}"
    return text.replace(",", " ") if ui == "uk" else text


def share(x: float | None, ui: str) -> str:
    if x is None:
        return "—"
    # thresholds on the rounded value, so 99.96 prints as "100", not "100.0"
    text = f"{x:.0f}" if round(x, 1) >= 100 else (f"{x:.1f}" if round(x, 2) >= 10 else f"{x:.2f}")
    return text.replace(".", ",") if ui == "uk" else text


def day(d: date | str) -> str:
    return d if isinstance(d, str) else d.isoformat()
