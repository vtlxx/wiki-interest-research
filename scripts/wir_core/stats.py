"""Statistics: growth with block-bootstrap CI, robust trend + Mann-Kendall, spikes, seasonality, BH."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd
from scipy.stats import norm, rankdata, theilslopes

SEED = 20260927


# ---- growth ---------------------------------------------------------------------------------
@dataclass(frozen=True)
class Growth:
    g: float
    lo: float
    hi: float
    verdict: str
    weeks: int


def classify(g: float, lo: float, hi: float) -> str:
    if lo > 0 and g >= 0.05:
        return "growing"
    if hi < 0 and g <= -0.05:
        return "declining"
    if lo >= -0.10 and hi <= 0.10:
        return "stable"
    return "unclear"


def _weekly(series: pd.Series, end: date, n_weeks: int) -> np.ndarray | None:
    start = end - timedelta(days=7 * n_weeks - 1)
    if len(series) == 0 or series.index[0] > pd.Timestamp(start) or series.index[-1] < pd.Timestamp(end):
        return None
    part = series[(series.index >= pd.Timestamp(start)) & (series.index <= pd.Timestamp(end))].to_numpy(float)
    if len(part) != 7 * n_weeks:
        return None
    return part.reshape(n_weeks, 7).sum(axis=1)


def _predates(first_day: date | None, end: date, n_weeks: int) -> bool:
    """True when the n_weeks span ending at `end` starts before `first_day` (the article did not exist yet,
    so its zero-filled early weeks would inflate the growth)."""
    return first_day is not None and end - timedelta(days=7 * n_weeks - 1) < first_day


def growth_yoy(topic_daily: pd.Series, project_daily: pd.Series, end: date, *, weeks: int = 52,
               lag_weeks: int = 52, block: int = 4, n_boot: int = 2000, seed: int = SEED,
               first_day: date | None = None) -> Growth | None:
    total = weeks + lag_weeks
    if _predates(first_day, end, total):
        return None
    t, p = _weekly(topic_daily, end, total), _weekly(project_daily, end, total)
    if t is None or p is None or np.any(p <= 0):
        return None
    share_w = t / p
    prev, cur = share_w[:weeks], share_w[-weeks:]
    if prev.mean() <= 0:
        return None
    g = float(cur.mean() / prev.mean() - 1)
    rng = np.random.default_rng(seed)
    n_blocks = math.ceil(weeks / block)
    starts = rng.integers(0, weeks - block + 1, size=(n_boot, n_blocks))
    idx = (starts[:, :, None] + np.arange(block)).reshape(n_boot, -1)[:, :weeks]
    denom = prev[idx].mean(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratios = np.where(denom > 0, cur[idx].mean(axis=1) / denom - 1, np.nan)
    lo, hi = np.nanpercentile(ratios, [5, 95])
    return Growth(g, float(lo), float(hi), classify(g, float(lo), float(hi)), weeks)


def simple_yoy(daily: pd.Series, end: date, *, first_day: date | None = None) -> float | None:
    if _predates(first_day, end, 104):
        return None
    w = _weekly(daily, end, 104)
    if w is None or w[:52].sum() <= 0:
        return None
    return float(w[52:].sum() / w[:52].sum() - 1)


# ---- trend ----------------------------------------------------------------------------------
@dataclass(frozen=True)
class Trend:
    pct_per_year: float
    lo: float
    hi: float
    p: float
    tau: float
    method: str


def _mk_s(x: np.ndarray) -> float:
    return float(sum(np.sign(x[i + 1:] - x[i]).sum() for i in range(len(x) - 1)))


def _var_s(x: np.ndarray) -> float:
    n = len(x)
    _, counts = np.unique(x, return_counts=True)
    ties = float((counts * (counts - 1) * (2 * counts + 5)).sum())
    return (n * (n - 1) * (2 * n + 5) - ties) / 18.0


def _z(s: float, var: float) -> float:
    if var <= 0 or s == 0:
        return 0.0
    return (s - 1) / math.sqrt(var) if s > 0 else (s + 1) / math.sqrt(var)


def mk_hamed_rao(x) -> tuple[float, float, float]:
    x = np.asarray(x, dtype=float)
    n = len(x)
    s, var = _mk_s(x), _var_s(x)
    slope = theilslopes(x, np.arange(n))[0]
    r = rankdata(x - slope * np.arange(n))
    r = r - r.mean()
    denom = float((r ** 2).sum())
    acc = 0.0
    if denom > 0:
        for k in range(1, n - 2):
            rho = float((r[:-k] * r[k:]).sum() / denom)
            if abs(rho) > 1.96 / math.sqrt(n):
                acc += (n - k) * (n - k - 1) * (n - k - 2) * rho
    factor = 1 + 2 * acc / (n * (n - 1) * (n - 2))
    var_mod = var * max(factor, 1.0)  # never shrink below plain MK: negative autocorrelation is not credited
    z = _z(s, var_mod)
    return s / (n * (n - 1) / 2), float(2 * (1 - norm.cdf(abs(z)))), s


def _mk_seasonal_stats(monthly: pd.Series) -> tuple[float, float, float]:
    s_total = var_total = pairs = 0.0
    for _, group in monthly.groupby(monthly.index.month):
        x = group.to_numpy(float)
        if len(x) < 2:
            continue
        s_total += _mk_s(x)
        var_total += _var_s(x)
        pairs += len(x) * (len(x) - 1) / 2
    return s_total, var_total, pairs


def mk_seasonal(monthly: pd.Series) -> tuple[float, float, float]:
    s_total, var_total, pairs = _mk_seasonal_stats(monthly)
    z = _z(s_total, var_total)
    tau = s_total / pairs if pairs else 0.0
    return tau, float(2 * (1 - norm.cdf(abs(z)))), s_total


def _seasonal_sen_slopes(y: np.ndarray, month: np.ndarray) -> np.ndarray:
    """Within-calendar-month pairwise slopes across years (Hirsch et al. 1982), in y-units per year."""
    slopes: list[float] = []
    for m in np.unique(month):
        vals = y[month == m]
        n = len(vals)
        for i in range(n):
            for j in range(i + 1, n):
                slopes.append((vals[j] - vals[i]) / (j - i))
    return np.array(slopes, dtype=float)


def _seasonal_sen_ci(slopes: np.ndarray, var_s: float, conf: float = 0.90) -> tuple[float, float]:
    n = len(slopes)
    if n == 0:
        return 0.0, 0.0
    ordered = np.sort(slopes)
    c = float(norm.ppf(1 - (1 - conf) / 2)) * math.sqrt(var_s) if var_s > 0 else 0.0
    lo_idx = int(np.clip(math.floor((n - c) / 2), 0, n - 1))
    hi_idx = int(np.clip(math.ceil((n + c) / 2), 0, n - 1))
    return float(ordered[lo_idx]), float(ordered[hi_idx])


def trend(monthly_share: pd.Series, seasonal: bool) -> Trend | None:
    s = monthly_share.dropna()
    if len(s) < 12:
        return None
    v = s.to_numpy(float)
    positive = v[v > 0]
    eps = float(positive.min()) / 2 if len(positive) else 1e-6
    y = np.log(np.where(v > 0, v, eps))
    if seasonal and len(y) >= 24:
        month = s.index.month.to_numpy()
        s_total, var_total, pairs = _mk_seasonal_stats(pd.Series(y, index=s.index))
        tau = s_total / pairs if pairs else 0.0
        p = float(2 * (1 - norm.cdf(abs(_z(s_total, var_total)))))
        slopes = _seasonal_sen_slopes(y, month)
        slope = float(np.median(slopes)) if len(slopes) else 0.0
        low, high = _seasonal_sen_ci(slopes, var_total)
        to_pct = lambda b: float(math.exp(b) - 1)  # noqa: E731  (slope already per year)
        method = "seasonal-mk"
    else:
        slope, _intercept, low, high = theilslopes(y, np.arange(len(y)), alpha=0.90)
        tau, p, _ = mk_hamed_rao(y)
        to_pct = lambda b: float(math.exp(12 * b) - 1)  # noqa: E731  (slope is per month)
        method = "hamed-rao"
    return Trend(to_pct(slope), to_pct(low), to_pct(high), p, tau, method)


# ---- spikes ---------------------------------------------------------------------------------
@dataclass(frozen=True)
class Episode:
    start: date
    end: date
    peak: date
    extra_views: float
    peak_views: float


def detect_spikes(topic_daily: pd.Series, project_daily: pd.Series, start: date, end: date, *,
                  half_window: int = 14, k: float = 5.0, min_ratio: float = 3.0,
                  min_extra: float = 100.0) -> tuple[list[Episode], pd.Series]:
    mask = (topic_daily.index >= pd.Timestamp(start)) & (topic_daily.index <= pd.Timestamp(end))
    t = topic_daily[mask]
    p = project_daily.reindex(t.index)
    sh = (t / p.where(p > 0)).fillna(0.0)
    window = 2 * half_window + 1
    med = sh.rolling(window, center=True, min_periods=7).median()
    mad = sh.rolling(window, center=True, min_periods=7).apply(
        lambda w: float(np.median(np.abs(w - np.median(w)))), raw=True)
    expected_views = (med * p).fillna(t)
    flag = (sh > med + k * 1.4826 * mad) & (sh >= min_ratio * med) & ((t - expected_views) >= min_extra)
    flag = flag.fillna(False)
    clean = topic_daily.copy()
    clean.loc[flag[flag].index] = expected_views[flag]
    episodes: list[Episode] = []
    days = list(flag[flag].index)
    group: list[pd.Timestamp] = []
    for day in days + [None]:
        if group and (day is None or (day - group[-1]).days > 2):
            extra = float((t[group] - expected_views[group]).sum())
            peak = t[group].idxmax()
            episodes.append(Episode(group[0].date(), group[-1].date(), peak.date(), extra, float(t[peak])))
            group = []
        if day is not None:
            group.append(day)
    episodes.sort(key=lambda e: -e.extra_views)
    return episodes, clean


def spike_share(episodes: list[Episode], topic_daily: pd.Series, start: date, end: date) -> float:
    mask = (topic_daily.index >= pd.Timestamp(start)) & (topic_daily.index <= pd.Timestamp(end))
    total = float(topic_daily[mask].sum())
    extra = sum(e.extra_views for e in episodes if start <= e.peak <= end)
    return extra / total if total > 0 else 0.0


# ---- seasonality ----------------------------------------------------------------------------
@dataclass(frozen=True)
class Seasonality:
    strength: float
    level: str
    peaks: list[int]
    profile: list[float]


def seasonality(monthly_share: pd.Series) -> Seasonality | None:
    s = monthly_share.dropna()
    if len(s) < 36:
        return None
    v = s.to_numpy(float)
    positive = v[v > 0]
    eps = float(positive.min()) / 2 if len(positive) else 1e-6
    y = np.log(np.where(v > 0, v, eps))
    weights = np.r_[0.5, np.ones(11), 0.5] / 12
    trend_part = np.convolve(y, weights, mode="valid")          # len = n - 12, centred on y[6:-6]
    detr = y[6:-6] - trend_part
    months = s.index.month.to_numpy()[6:-6]
    profile = np.array([np.median(detr[months == m]) if np.any(months == m) else 0.0 for m in range(1, 13)])
    profile -= profile.mean()
    seasonal_part = profile[months - 1]
    resid = detr - seasonal_part
    total_var = float(np.var(seasonal_part + resid))
    strength = max(0.0, 1 - float(np.var(resid)) / total_var) if total_var > 0 else 0.0
    level = "weak" if strength < 0.3 else ("moderate" if strength < 0.6 else "strong")
    peaks = [int(m) + 1 for m in np.argsort(-profile)[:2]]
    return Seasonality(strength, level, peaks, [float(v) for v in profile])


# ---- multiple comparisons --------------------------------------------------------------------
def bh_adjust(pvals: list[float | None]) -> list[float | None]:
    present = [(i, p) for i, p in enumerate(pvals) if p is not None]
    m = len(present)
    out: list[float | None] = [None] * len(pvals)
    running = 1.0
    for rank, (i, p) in reversed(list(enumerate(sorted(present, key=lambda x: x[1]), start=1))):
        running = min(running, p * m / rank)
        out[i] = min(running, 1.0)
    return out
