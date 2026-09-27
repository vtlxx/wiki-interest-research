"""Supply signal per language and transparent audience ranking (spec 6.9)."""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from .config import DEFAULT_WEIGHTS
from .errors import EXIT_USAGE, WirError
from .providers.base import BADGE_FEATURED, BADGE_GOOD

GAP_VALUE = {"missing": 1.0, "short": 1.0, "normal": 0.0, "good": 0.0, "featured": 0.0}


def supply_status(status: str, length: int | None, badges: list[str], peer_lengths: list[int]) -> str:
    if status == "missing":
        return "missing"
    if status == "section":
        return "short"
    if set(badges) & BADGE_FEATURED:
        return "featured"
    if set(badges) & BADGE_GOOD:
        return "good"
    peers = [p for p in peer_lengths if p]
    if length and len(peers) >= 2 and length < 0.3 * statistics.median(peers):
        return "short"
    return "normal"


def parse_weights(text: str | None) -> dict[str, float]:
    weights = dict(DEFAULT_WEIGHTS)
    if not text:
        return weights
    for part in text.split(","):
        if not part.strip():
            continue
        key, _, raw = part.partition("=")
        key = key.strip()
        try:
            value = float(raw)
        except ValueError:
            value = -1.0
        if key not in weights or value < 0:
            raise WirError("BAD_WEIGHTS", f"bad weight '{part.strip()}'",
                           fix="Use keys level, momentum, size, gap with non-negative numbers, "
                               "e.g. --weights momentum=0.6,level=0.2", exit_code=EXIT_USAGE)
        weights[key] = value
    if sum(weights.values()) <= 0:
        raise WirError("BAD_WEIGHTS", "all weights are zero", fix="Give at least one positive weight.",
                       exit_code=EXIT_USAGE)
    return weights


@dataclass(frozen=True)
class RankRow:
    lang: str
    score: float
    components: dict[str, float]
    eligible: bool


def _percentiles(values: list[float | None]) -> list[float]:
    known = sorted(v for v in values if v is not None)
    n = len(known)
    out = []
    for v in values:
        if v is None:
            out.append(0.0)
        elif n <= 1:
            out.append(1.0)
        else:
            below = sum(1 for k in known if k < v)
            equal = sum(1 for k in known if k == v)
            out.append((below + (equal - 1) / 2) / (n - 1))
    return out


def rank_langs(rows: list[dict], weights: dict[str, float]) -> list[RankRow]:
    comps = {
        "level": _percentiles([r["level"] for r in rows]),
        "momentum": _percentiles([r["momentum"] for r in rows]),
        "size": _percentiles([math.log1p(r["size"]) if r["size"] is not None else None for r in rows]),
        "gap": [float(r["gap"]) for r in rows],
    }
    total_w = sum(weights.values())
    ranked = []
    for i, r in enumerate(rows):
        c = {k: comps[k][i] for k in comps}
        score = sum(weights[k] * c[k] for k in c) / total_w
        ranked.append(RankRow(r["lang"], score, c, r["trust"] != "low" and r["momentum"] is not None))
    return sorted(ranked, key=lambda x: (-x.score, x.lang))
