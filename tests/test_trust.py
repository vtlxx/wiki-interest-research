from wir_core.trust import TrustInputs, assess


def base(**kw):
    values = dict(median_monthly_views=5000, history_months=60, spike_share=0.02, flips_without_spikes=False,
                  high_incidents=[], redirect_coverage=0.98, dominant_redirect=False, young_article=False,
                  renamed_in_window=False, project_yoy=-0.08, trend_conflict=False, is_proxy=False,
                  verify_outcome=None)
    values.update(kw)
    return TrustInputs(**values)


def codes(trust):
    return [r.code for r in trust.reasons]


def test_clean_series_is_high():
    t = assess(base())
    assert t.level == "high" and t.reasons == []


def test_critical_reason_forces_low():
    t = assess(base(median_monthly_views=12))
    assert t.level == "low" and codes(t)[0] == "tiny_volume"
    assert assess(base(spike_share=0.6)).level == "low"
    assert assess(base(flips_without_spikes=True)).level == "low"
    assert assess(base(history_months=8)).level == "low"
    assert assess(base(verify_outcome="flips")).level == "low"


def test_minor_reasons_step_down_and_floor():
    assert assess(base(median_monthly_views=150)).level == "medium"
    t = assess(base(median_monthly_views=150, spike_share=0.3))
    assert t.level == "low" and codes(t) == ["low_volume", "spiky"]
    t = assess(base(high_incidents=["bots_2025_11"], redirect_coverage=0.8, dominant_redirect=True,
                    young_article=True, renamed_in_window=True, project_yoy=0.4))
    assert t.level == "low" and len(t.reasons) == 5


def test_proxy_caps_medium():
    t = assess(base(is_proxy=True))
    assert t.level == "medium" and codes(t) == ["proxy"]


def test_history_between_12_and_24_is_minor():
    assert assess(base(history_months=18)).level == "medium"


def test_verify_weakens_is_minor():
    assert codes(assess(base(verify_outcome="weakens"))) == ["verify_weakens"]


def test_redirect_pair_counts_as_one_deduction():
    t = assess(base(redirect_coverage=0.8, dominant_redirect=True))
    assert t.level == "medium" and set(codes(t)) == {"redirect_coverage", "dominant_redirect"}


def test_young_and_renamed_pair_counts_as_one_deduction():
    t = assess(base(young_article=True, renamed_in_window=True))
    assert t.level == "medium" and set(codes(t)) == {"young_article", "renamed"}
