from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from wir_core import stats as st

END = date(2026, 8, 31)


def daily(values, end=END):
    idx = pd.date_range(end=pd.Timestamp(end), periods=len(values), freq="D")
    return pd.Series(np.asarray(values, dtype=float), index=idx)


def project(n, level=1_000_000.0):
    return daily(np.full(n, level))


# ---- growth ---------------------------------------------------------------------------------
def test_growth_flat_is_stable():
    n = 7 * 104
    g = st.growth_yoy(daily(np.full(n, 100.0)), project(n), END)
    assert g.g == pytest.approx(0.0, abs=1e-9) and g.verdict == "stable" and g.weeks == 52


def test_growth_doubling_is_growing_with_positive_ci():
    rng = np.random.default_rng(1)
    n = 7 * 104
    values = np.r_[np.full(n // 2, 100.0), np.full(n // 2, 200.0)] + rng.normal(0, 10, n)
    g = st.growth_yoy(daily(values), project(n), END)
    assert g.g == pytest.approx(1.0, abs=0.05) and g.lo > 0.8 and g.verdict == "growing"


def test_growth_uses_share_not_raw():
    n = 7 * 104
    topic = daily(np.r_[np.full(n // 2, 100.0), np.full(n // 2, 50.0)])       # raw halves
    proj = daily(np.r_[np.full(n // 2, 2e6), np.full(n // 2, 1e6)])           # project halves too
    assert st.growth_yoy(topic, proj, END).g == pytest.approx(0.0, abs=1e-9)


def test_growth_deterministic_and_short_history():
    rng = np.random.default_rng(2)
    n = 7 * 104
    topic = daily(rng.poisson(50, n))
    assert st.growth_yoy(topic, project(n), END) == st.growth_yoy(topic, project(n), END)
    assert st.growth_yoy(daily(np.full(300, 5.0)), project(300), END) is None


def test_growth_half_year_lagged():
    n = 7 * 78
    values = np.full(n, 100.0)
    values[-7 * 26:] = 150.0
    g = st.growth_yoy(daily(values), project(n), END, weeks=26, lag_weeks=52)
    assert g.g == pytest.approx(0.5) and g.weeks == 26


@pytest.mark.parametrize("g,lo,hi,expected", [
    (0.30, 0.10, 0.50, "growing"), (0.04, 0.01, 0.07, "stable"), (-0.2, -0.3, -0.1, "declining"),
    (0.02, -0.05, 0.08, "stable"), (0.20, -0.05, 0.45, "unclear"), (-0.03, -0.2, 0.15, "unclear")])
def test_classify(g, lo, hi, expected):
    assert st.classify(g, lo, hi) == expected


def test_simple_yoy():
    s = daily(np.r_[np.full(364, 10.0), np.full(364, 12.0)])
    assert st.simple_yoy(s, END) == pytest.approx(0.2)
    assert st.simple_yoy(daily(np.full(100, 1.0)), END) is None



def test_growth_young_article_is_none_when_the_compared_span_predates_it():
    n = 7 * 104
    values = np.zeros(n)
    values[-600:] = 100.0                                        # created ~20 months ago, zero-filled before
    topic, proj = daily(values), project(n)
    first_day = END - timedelta(days=599)
    assert st.growth_yoy(topic, proj, END).g > 0.3              # the inflated G this guard prevents
    assert st.growth_yoy(topic, proj, END, first_day=first_day) is None
    assert st.simple_yoy(topic, END, first_day=first_day) is None


def test_growth_first_day_at_or_before_span_start_keeps_the_result():
    n = 7 * 104
    topic, proj = daily(np.full(n, 100.0)), project(n)
    span_start = END - timedelta(days=n - 1)
    for first in (span_start, date(2015, 7, 1)):
        assert st.growth_yoy(topic, proj, END, first_day=first) == st.growth_yoy(topic, proj, END)
        assert st.simple_yoy(topic, END, first_day=first) == st.simple_yoy(topic, END)
    half = st.growth_yoy(daily(np.full(7 * 78, 100.0)), project(7 * 78), END, weeks=26, lag_weeks=52,
                         first_day=END - timedelta(days=7 * 78 - 1))
    assert half is not None
    assert st.growth_yoy(daily(np.full(7 * 78, 100.0)), project(7 * 78), END, weeks=26, lag_weeks=52,
                         first_day=END - timedelta(days=7 * 78 - 2)) is None

# ---- trend / Mann-Kendall -------------------------------------------------------------------
def monthly(values, end="2026-08-01"):
    idx = pd.date_range(end=pd.Timestamp(end), periods=len(values), freq="MS")
    return pd.Series(np.asarray(values, dtype=float), index=idx)


def test_trend_detects_20pct_per_year():
    rng = np.random.default_rng(1)
    vals = 50 * (1.2 ** (np.arange(36) / 12)) * np.exp(rng.normal(0, 0.03, 36))
    tr = st.trend(monthly(vals), seasonal=False)
    assert tr.pct_per_year == pytest.approx(0.2, abs=0.02) and tr.p < 0.01 and tr.lo < tr.pct_per_year < tr.hi
    assert tr.lo < 0.2 < tr.hi
    assert tr.method == "hamed-rao"


def test_trend_zero_month_does_not_bias_scale():
    vals = 50 * (1.2 ** (np.arange(36) / 12))
    vals[10] = 0.0
    tr = st.trend(monthly(vals), seasonal=False)
    assert tr.pct_per_year == pytest.approx(0.2, abs=0.05)


def test_trend_flat_not_significant_and_short_none():
    rng = np.random.default_rng(4)
    tr = st.trend(monthly(50 * np.exp(rng.normal(0, 0.1, 30))), seasonal=False)
    assert tr.p > 0.05
    assert st.trend(monthly(np.arange(1, 11)), seasonal=False) is None


def test_trend_seasonal_method():
    months = np.arange(48)
    vals = 100 * (1.1 ** (months / 12)) * (1 + 0.5 * np.sin(2 * np.pi * months / 12))
    tr = st.trend(monthly(vals), seasonal=True)
    assert tr.method == "seasonal-mk" and tr.p < 0.01


@pytest.mark.parametrize("phase", [0, 3, 6, 9])
def test_trend_seasonal_flat_is_phase_invariant(phase):
    idx = pd.date_range(end="2026-08-01", periods=24, freq="MS")
    vals = 100 * (1 + 0.5 * np.cos(2 * np.pi * (idx.month.values - 1 - phase) / 12))
    tr = st.trend(pd.Series(vals, index=idx), seasonal=True)
    assert abs(tr.pct_per_year) < 0.02


def test_trend_seasonal_with_growth_recovers_pct_per_year():
    rng = np.random.default_rng(6)
    idx = pd.date_range(end="2026-08-01", periods=48, freq="MS")
    t = np.arange(48)
    vals = (50 * (1.2 ** (t / 12)) * (1 + 0.5 * np.cos(2 * np.pi * idx.month.values / 12))
            * np.exp(rng.normal(0, 0.03, 48)))
    tr = st.trend(pd.Series(vals, index=idx), seasonal=True)
    assert tr.pct_per_year == pytest.approx(0.2, abs=0.03)
    assert tr.lo < tr.pct_per_year < tr.hi and tr.lo < 0.2 < tr.hi
    assert tr.method == "seasonal-mk"


def test_mk_monotone():
    tau, p, s = st.mk_hamed_rao(np.arange(24, dtype=float))
    assert tau == pytest.approx(1.0) and p < 0.001 and s == 24 * 23 / 2



def _ar1(seed, phi=-0.6, n=24):
    rng = np.random.default_rng(seed)
    e = rng.standard_normal(n)
    x = np.zeros(n)
    x[0] = e[0]
    for i in range(1, n):
        x[i] = phi * x[i - 1] + e[i]
    return x


def _plain_mk_p(x):
    z = st._z(st._mk_s(x), st._var_s(x))
    return float(2 * (1 - st.norm.cdf(abs(z))))


def test_mk_negative_autocorrelation_noise_not_significant():
    tau, p, s = st.mk_hamed_rao(_ar1(4))
    assert p > 0.10


def test_mk_hamed_rao_never_more_significant_than_plain_mk():
    for seed in range(40):
        x = _ar1(seed)
        assert st.mk_hamed_rao(x)[1] >= _plain_mk_p(x) - 1e-12, seed


# ---- spikes ---------------------------------------------------------------------------------
def test_spike_episode_detected_and_despiked():
    n = 120
    values = np.full(n, 100.0)
    values[60:63] = 2000.0
    values[90] = 150.0                                  # small bump: not a spike
    topic, proj = daily(values), project(n)
    start, end = topic.index[0].date(), topic.index[-1].date()
    eps, clean = st.detect_spikes(topic, proj, start, end)
    assert len(eps) == 1
    ep = eps[0]
    assert ep.start == topic.index[60].date() and ep.end == topic.index[62].date()
    assert ep.extra_views == pytest.approx(3 * 1900.0) and ep.peak_views == 2000.0
    assert clean.iloc[61] == pytest.approx(100.0) and clean.iloc[90] == 150.0
    assert st.spike_share(eps, topic, start, end) == pytest.approx(5700.0 / values.sum())


def test_low_volume_blip_ignored():
    values = np.full(120, 5.0)
    values[50] = 60.0
    topic = daily(values)
    eps, _ = st.detect_spikes(topic, project(120), topic.index[0].date(), topic.index[-1].date())
    assert eps == []


# ---- seasonality ----------------------------------------------------------------------------
def test_seasonality_strong_with_peaks():
    months = np.arange(48)
    idx = pd.date_range(end="2026-08-01", periods=48, freq="MS")
    vals = 100 * np.exp(0.6 * np.cos(2 * np.pi * (idx.month.values - 9) / 12))   # peak in September
    s = st.seasonality(pd.Series(vals, index=idx))
    assert s.level == "strong" and s.strength > 0.9 and s.peaks[0] == 9 and len(s.profile) == 12


def test_seasonality_weak_for_noise_and_none_when_short():
    # 120 months: with only 36-48 months the month-of-year medians overfit noise (Fs is biased upward);
    # the pipeline therefore always passes the FULL history, and the bias is listed in references/limitations.md.
    rng = np.random.default_rng(5)
    s = st.seasonality(monthly(100 * np.exp(rng.normal(0, 0.1, 120))))
    assert s.level == "weak"
    assert st.seasonality(monthly(np.full(30, 1.0))) is None


# ---- BH ---------------------------------------------------------------------------------------
def test_bh_adjust():
    q = st.bh_adjust([0.01, 0.04, 0.03, 0.2, None])
    assert q[:4] == pytest.approx([0.04, 0.16 / 3, 0.16 / 3, 0.2]) and q[4] is None


# ---- share shift in an incident month -------------------------------------------------------
def monthly_share(values, first="2025-07-01"):
    return pd.Series(np.asarray(values, dtype=float), index=pd.date_range(first, periods=len(values), freq="MS"))


NOV = (date(2025, 11, 1), date(2025, 11, 30))


def test_share_shift_against_the_median_of_two_months_on_each_side():
    # Jul Aug Sep Oct [Nov] Dec Jan Feb: neighbours Sep, Oct, Dec, Jan -> median 100
    assert st.share_shift(monthly_share([10, 10, 90, 100, 150, 100, 110, 10]), *NOV) == pytest.approx(0.5)
    assert st.share_shift(monthly_share([10, 10, 90, 100, 60, 100, 110, 10]), *NOV) == pytest.approx(-0.4)


def test_share_shift_uses_the_months_that_exist():
    assert st.share_shift(monthly_share([100, 100, 100, 100, 120]), *NOV) == pytest.approx(0.2)   # ends in Nov
    assert st.share_shift(monthly_share([100, np.nan, 100, 100, 120]), *NOV) == pytest.approx(0.2)


def test_share_shift_is_none_without_the_month_or_a_baseline():
    assert st.share_shift(monthly_share([100, 100, 100]), *NOV) is None                  # Jul-Sep only
    assert st.share_shift(monthly_share([150], first="2025-11-01"), *NOV) is None       # no neighbours
    assert st.share_shift(monthly_share([0, 0, 0, 0, 5, 0, 0]), *NOV) is None             # zero baseline
