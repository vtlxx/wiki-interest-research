import pytest

from wir_core.pipeline import direction_of_growth, direction_of_trend, sign_of, verify_outcome
from wir_core.stats import Growth, Trend


# dirs: significant direction of each variant, spike-free G first; signs: sign of each point estimate
@pytest.mark.parametrize("main,dirs,signs,expected", [
    (1, [1, 1, 1, 1], [1, 1, 1, 1], "holds"),
    (1, [1, -1, 1], [1, -1, 1], "flips"),
    (-1, [-1, -1], [-1, -1], "holds"),
    (1, [0, 1, 1], [1, 1, 1], "weakens"),        # spike-free G has no direction
    (1, [1, 0, 1], [1, 1, 1], "holds"),          # a "stable" half-year of the same sign does not weaken
    (1, [1, 1, 0], [1, 1, 1], "holds"),          # nor a non-significant trend of the same sign
    (1, [1, 0, 1], [1, -1, 1], "weakens"),       # a variant pointing the other way, even if not significant
    (-1, [-1, -1, 0], [-1, -1, 1], "weakens"),
    (1, [1, 0], [1, 0], "holds"),                # a missing variant (no estimate) does not weaken
    (0, [0, 0, 0], [1, -1, 1], "holds"), (0, [0, 1, 0], [0, 1, 0], "weakens"), (0, [1, -1], [1, -1], "weakens")])
def test_verify_outcome(main, dirs, signs, expected):
    assert verify_outcome(main, dirs, signs) == expected


def test_signs():
    assert sign_of(Growth(-0.02, -0.1, 0.05, "stable", 26)) == -1
    assert sign_of(Trend(0.2, -0.1, 0.3, 0.5, 0.1, "hamed-rao")) == 1
    assert sign_of(None) == 0


def test_directions():
    assert direction_of_growth(Growth(0.3, 0.1, 0.5, "growing", 52)) == 1
    assert direction_of_growth(Growth(-0.3, -0.5, -0.1, "declining", 52)) == -1
    assert direction_of_growth(Growth(0.1, -0.1, 0.3, "unclear", 52)) == 0
    assert direction_of_growth(None) == 0
    assert direction_of_trend(Trend(0.2, 0.1, 0.3, 0.01, 0.4, "hamed-rao")) == 1
    assert direction_of_trend(Trend(-0.2, -0.3, -0.1, 0.5, -0.1, "hamed-rao")) == 0
