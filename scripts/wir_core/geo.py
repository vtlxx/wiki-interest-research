"""Country context: project audience by country and per-day country breakdown of spikes."""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from .providers.base import GeoRow


def parse_dp_lines(lines: Iterable[str], qids: set[str]) -> dict[str, list[GeoRow]]:
    out: dict[str, list[GeoRow]] = {q: [] for q in qids}
    for line in lines:
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 7 or parts[5] not in out:
            continue
        try:
            views = int(float(parts[6]))
        except ValueError:
            continue
        out[parts[5]].append(GeoRow(parts[0], parts[1], parts[2], parts[4], parts[5], views))
    return out


def top_countries(month_lists: list[list[tuple[str, int]]], n: int = 5) -> list[tuple[str, float]]:
    totals: dict[str, int] = defaultdict(int)
    for month in month_lists:
        for code, views in month:
            totals[code] += views
    grand = sum(totals.values())
    if grand == 0:
        return []
    ranked = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
    return [(code, views / grand) for code, views in ranked]


def spike_breakdown(rows: list[GeoRow], project: str) -> list[tuple[str, float]]:
    mine = [r for r in rows if r.project == project]
    total = sum(r.views for r in mine)
    if total == 0:
        return []
    return [(r.code, r.views / total) for r in sorted(mine, key=lambda r: (-r.views, r.code))]
