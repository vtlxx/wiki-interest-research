"""Raw provider data -> clean daily/monthly series, redirects selection, share per million."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from .providers.base import Move, Redirect

DATA_START = date(2015, 7, 1)


def fill_daily(raw: dict[date, int], start: date, end: date) -> pd.Series:
    index = pd.date_range(start, end, freq="D")
    if not raw:
        return pd.Series(0.0, index=index)
    s = pd.Series({pd.Timestamp(d): float(v) for d, v in raw.items()})
    return s.reindex(index, fill_value=0.0).astype(float)


def last_complete_day(project_raw: dict[date, int], today: date) -> date:
    yesterday = today - timedelta(days=1)
    if not project_raw:
        return today - timedelta(days=2)
    return min(max(project_raw), yesterday)


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.year * 12 + (d.month - 1) + n, 12)
    return date(y, m + 1, 1)


def first_full_month(d: date) -> date:
    """First day of the first calendar month that starts on or after `d`."""
    return d if d.day == 1 else add_months(d.replace(day=1), 1)


def _month_end(first: date) -> date:
    return add_months(first, 1) - timedelta(days=1)


def month_bounds(last_day: date) -> tuple[date, date]:
    first = last_day.replace(day=1)
    if last_day != _month_end(first):
        first = add_months(first, -1)
    return first, _month_end(first)


def window_bounds(last_month_start: date, months: int, date_from: str | None, date_to: str | None) -> tuple[date, date]:
    end_first = last_month_start
    if date_to:
        requested = date.fromisoformat(date_to + "-01")
        end_first = min(requested, last_month_start)
    start = date.fromisoformat(date_from + "-01") if date_from else add_months(end_first, -(months - 1))
    return max(start, DATA_START), _month_end(end_first)


def young_start(created: date | None, start: date) -> tuple[date, bool]:
    if created is None:
        return start, False
    ready = created + timedelta(days=90)
    first_full = first_full_month(ready)
    if first_full <= start:
        return start, False
    return first_full, True


@dataclass(frozen=True)
class RedirectSelection:
    included: list[str]
    coverage: float | None
    dominant: str | None
    unchecked: list[str]


def select_redirects(redirects: list[Redirect], main_views_60d: int | None, move_sources: set[str],
                     threshold: float = 0.01, dominant_share: float = 0.3) -> RedirectSelection:
    main = main_views_60d or 0
    included, unchecked = [], []
    known_total, included_total = main, main
    for r in redirects:
        if r.views_60d is None:
            if r.title in move_sources:
                included.append(r.title)
            else:
                unchecked.append(r.title)
            continue
        known_total += r.views_60d
        take = (r.title in move_sources
                or (main > 0 and r.views_60d >= threshold * main)
                or (main == 0 and r.views_60d > 0))
        if take:
            included.append(r.title)
            included_total += r.views_60d
    if main_views_60d is None:  # unknown main views: shares of the total would be guesses, so claim none
        return RedirectSelection(included, None, None, unchecked)
    coverage = included_total / known_total if known_total > 0 else None
    dominant = next((r.title for r in redirects if r.title in included and r.views_60d
                     and known_total > 0 and r.views_60d > dominant_share * known_total), None)
    return RedirectSelection(included, coverage, dominant, unchecked)


def combine(series: list[pd.Series]) -> pd.Series:
    if not series:
        return pd.Series(dtype=float)
    out = series[0].copy()
    for s in series[1:]:
        out = out.add(s, fill_value=0.0)
    return out


def monthly(daily: pd.Series, start: date, end: date) -> pd.Series:
    part = daily[(daily.index >= pd.Timestamp(start)) & (daily.index <= pd.Timestamp(end))]
    return part.resample("MS").sum()


def share(topic: pd.Series, project: pd.Series) -> pd.Series:
    proj = project.reindex(topic.index)
    return (topic / proj.where(proj > 0)) * 1_000_000


def history_months(topic_daily: pd.Series, created: date | None, end: date) -> int:
    nonzero = topic_daily[topic_daily > 0]
    first = created or (nonzero.index[0].date() if len(nonzero) else None)
    if first is None:
        return 0
    first_full = first_full_month(first)
    end_first, _ = month_bounds(end)
    return max(0, (end_first.year - first_full.year) * 12 + end_first.month - first_full.month + 1)


def renamed_within(moves: list[Move], start: date, end: date) -> list[Move]:
    return [m for m in moves if start <= m.when <= end]
