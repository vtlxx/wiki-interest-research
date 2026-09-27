import pytest

from wir_core.errors import WirError
from wir_core.rank import parse_weights, rank_langs, supply_status


def test_supply_status():
    assert supply_status("missing", None, [], [5000, 6000]) == "missing"
    assert supply_status("section", 40000, [], [5000]) == "short"
    assert supply_status("found", 1000, [], [9000, 10000, 12000]) == "short"
    assert supply_status("found", 9000, [], [9000, 10000]) == "normal"
    assert supply_status("found", 9000, ["Q17437796"], []) == "featured"
    assert supply_status("found", 9000, ["Q17437798"], []) == "good"
    assert supply_status("found", 1000, [], [9000]) == "normal"      # one peer is not enough to judge


def test_parse_weights():
    assert parse_weights(None) == {"level": 0.35, "momentum": 0.35, "size": 0.2, "gap": 0.1}
    w = parse_weights("momentum=0.6, level=0.2")
    assert w == {"level": 0.2, "momentum": 0.6, "size": 0.2, "gap": 0.1}
    for bad in ["speed=1", "momentum=-1", "momentum=x", "level=0,momentum=0,size=0,gap=0"]:
        with pytest.raises(WirError):
            parse_weights(bad)


def rows():
    return [
        {"lang": "pl", "level": 12.0, "momentum": 0.10, "size": 5000, "gap": 0.0, "trust": "high"},
        {"lang": "cs", "level": 30.0, "momentum": 0.40, "size": 800, "gap": 1.0, "trust": "medium"},
        {"lang": "sk", "level": 50.0, "momentum": 0.90, "size": 100, "gap": 1.0, "trust": "low"},
        {"lang": "de", "level": 5.0, "momentum": None, "size": 20000, "gap": 0.0, "trust": "high"},
    ]


def test_rank_orders_and_eligibility():
    ranked = rank_langs(rows(), parse_weights(None))
    order = [r.lang for r in ranked]
    assert order[0] == "sk" and order[1] == "cs"
    eligible = {r.lang: r.eligible for r in ranked}
    assert eligible == {"sk": False, "cs": True, "pl": True, "de": False}
    assert set(ranked[0].components) == {"level", "momentum", "size", "gap"}


def test_weights_change_ranking():
    ranked = rank_langs(rows(), parse_weights("level=0,momentum=0,size=1,gap=0"))
    assert ranked[0].lang == "de"


def test_single_language():
    ranked = rank_langs(rows()[:1], parse_weights(None))
    assert ranked[0].score == pytest.approx(1.0 - 0.1)  # all components 1 except gap 0 (weight 0.1)
