import pytest

from why.metrics import cohens_kappa, confusion_matrix, percent_agreement


def textbook_raters():
    """50 items: both yes 20, A yes and B no 5, A no and B yes 10, both no 15.
    p_o = 0.70, p_e = 0.5 * 0.6 + 0.5 * 0.4 = 0.50, kappa = 0.40."""
    a = ["yes"] * 20 + ["yes"] * 5 + ["no"] * 10 + ["no"] * 15
    b = ["yes"] * 20 + ["no"] * 5 + ["yes"] * 10 + ["no"] * 15
    return a, b


def test_kappa_and_agreement_on_a_known_example():
    a, b = textbook_raters()
    assert percent_agreement(a, b) == pytest.approx(70.0)
    assert cohens_kappa(a, b) == pytest.approx(0.40)
    assert confusion_matrix(a, b, ["yes", "no"]) == [[20, 5], [10, 15]]


def test_kappa_edge_cases():
    same = ["positive", "negative", "neutral", "positive"]
    assert cohens_kappa(same, same) == pytest.approx(1.0)
    assert cohens_kappa(["neutral"] * 3, ["neutral"] * 3) == 1.0
    # systematic disagreement is worse than chance
    assert cohens_kappa(["positive", "negative"], ["negative", "positive"]) < 0
    with pytest.raises(ValueError):
        cohens_kappa([], [])
    with pytest.raises(ValueError):
        percent_agreement(["a"], ["a", "b"])
