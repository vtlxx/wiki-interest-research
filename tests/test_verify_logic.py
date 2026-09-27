import pytest

from wir_core.pipeline import direction_of_growth, direction_of_trend, verify_outcome
from wir_core.stats import Growth, Trend


@pytest.mark.parametrize("main,dirs,expected", [
    (1, [1, 1, 1, 1], "holds"), (1, [1, 0, 1], "weakens"), (1, [1, -1, 1], "flips"),
    (-1, [-1, -1], "holds"), (0, [0, 0, 0], "holds"), (0, [0, 1, 0], "weakens"), (0, [1, -1], "weakens")])
def test_verify_outcome(main, dirs, expected):
    assert verify_outcome(main, dirs) == expected


def test_directions():
    assert direction_of_growth(Growth(0.3, 0.1, 0.5, "growing", 52)) == 1
    assert direction_of_growth(Growth(-0.3, -0.5, -0.1, "declining", 52)) == -1
    assert direction_of_growth(Growth(0.1, -0.1, 0.3, "unclear", 52)) == 0
    assert direction_of_growth(None) == 0
    assert direction_of_trend(Trend(0.2, 0.1, 0.3, 0.01, 0.4, "hamed-rao")) == 1
    assert direction_of_trend(Trend(-0.2, -0.3, -0.1, 0.5, -0.1, "hamed-rao")) == 0
