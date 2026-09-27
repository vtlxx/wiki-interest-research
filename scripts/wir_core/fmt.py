"""Number/date formatting shared by say/facts, charts and reports (the only place numbers become text)."""
from __future__ import annotations

import math
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
    if round(x, 1) >= 100:
        text = f"{x:.0f}"
    elif round(x, 2) >= 10:
        text = f"{x:.1f}"
    elif x == 0 or round(x, 2) > 0:
        text = f"{x:.2f}"
    else:  # tiny shares keep one significant digit instead of printing as 0.00
        text = f"{x:.{min(6, -math.floor(math.log10(abs(x))))}f}"
    return text.replace(".", ",") if ui == "uk" else text


def number(x: float, ui: str) -> str:
    """A plain number such as a ranking weight (0.35 / 0,35)."""
    text = f"{x:g}"
    return text.replace(".", ",") if ui == "uk" else text


def day(d: date | str) -> str:
    return d if isinstance(d, str) else d.isoformat()
