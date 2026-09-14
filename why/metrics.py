"""Agreement between two label sequences over the same items."""

from collections import Counter
from collections.abc import Sequence


def _check(a: Sequence[str], b: Sequence[str]) -> None:
    if len(a) != len(b):
        raise ValueError("label sequences must have the same length")
    if not a:
        raise ValueError("need at least one pair of labels")


def percent_agreement(a: Sequence[str], b: Sequence[str]) -> float:
    _check(a, b)
    return 100 * sum(x == y for x, y in zip(a, b, strict=True)) / len(a)


def cohens_kappa(a: Sequence[str], b: Sequence[str]) -> float:
    """kappa = (p_o - p_e) / (1 - p_e), where p_e is the agreement expected by chance from
    each rater's own label frequencies."""
    _check(a, b)
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    count_a, count_b = Counter(a), Counter(b)
    chance_hits = sum(count_a[label] * count_b[label] for label in count_a.keys() | count_b.keys())
    if chance_hits == n * n:  # both raters used one and the same label for everything
        return 1.0
    expected = chance_hits / (n * n)
    return (observed - expected) / (1 - expected)


def confusion_matrix(a: Sequence[str], b: Sequence[str], labels: Sequence[str]) -> list[list[int]]:
    """Rows are labels from `a`, columns labels from `b`, both in `labels` order."""
    _check(a, b)
    index = {label: i for i, label in enumerate(labels)}
    matrix = [[0] * len(labels) for _ in labels]
    for x, y in zip(a, b, strict=True):
        matrix[index[x]][index[y]] += 1
    return matrix
