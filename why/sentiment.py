"""Sentiment models behind one small interface.

Every model returns a label (positive, neutral, negative) and a score from -1 to +1, so the
warehouse, the exports and the agreement report never care which model produced them."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

LABELS = ("positive", "neutral", "negative")


@dataclass(frozen=True)
class SentimentResult:
    label: str
    score: float  # -1 (negative) to +1 (positive)


class SentimentModel(Protocol):
    name: str

    def score(self, texts: Sequence[str]) -> list[SentimentResult]: ...


# VADER's documented cut points for the compound score
VADER_POSITIVE = 0.05
VADER_NEGATIVE = -0.05


def label_from_compound(compound: float) -> str:
    if compound >= VADER_POSITIVE:
        return "positive"
    if compound <= VADER_NEGATIVE:
        return "negative"
    return "neutral"


class VaderModel:
    """Lexicon and rule based baseline: fast, deterministic, no download."""

    name = "vader"

    def __init__(self) -> None:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

        self._analyzer = SentimentIntensityAnalyzer()

    def score(self, texts: Sequence[str]) -> list[SentimentResult]:
        results = []
        for text in texts:
            compound = self._analyzer.polarity_scores(text)["compound"]
            results.append(SentimentResult(label_from_compound(compound), round(compound, 4)))
        return results


class FinbertModel:
    """ProsusAI/finbert through transformers.

    transformers (and torch) are imported on first use, so VADER-only runs and the test suite
    never need them. score = P(positive) - P(negative); label = the most likely class."""

    name = "finbert"
    model_id = "ProsusAI/finbert"

    def __init__(self, batch_size: int = 16) -> None:
        self.batch_size = batch_size
        self._pipeline = None

    def _load(self):
        if self._pipeline is None:
            from transformers import pipeline

            self._pipeline = pipeline("text-classification", model=self.model_id, top_k=None)
        return self._pipeline

    def score(self, texts: Sequence[str]) -> list[SentimentResult]:
        if not texts:
            return []
        outputs = self._load()(list(texts), batch_size=self.batch_size, truncation=True)
        return [self._to_result(output) for output in outputs]

    @staticmethod
    def _to_result(output: list[dict] | dict) -> SentimentResult:
        if isinstance(output, dict):  # single-label output shape
            output = [output]
        probs = {item["label"].lower(): float(item["score"]) for item in output}
        label = max(probs, key=probs.__getitem__)
        if label not in LABELS:
            raise ValueError(f"unexpected FinBERT label {label!r}")
        score = probs.get("positive", 0.0) - probs.get("negative", 0.0)
        return SentimentResult(label, round(score, 4))


MODELS: dict[str, type] = {"vader": VaderModel, "finbert": FinbertModel}


def get_models(names: Iterable[str]) -> list[SentimentModel]:
    models = []
    for name in dict.fromkeys(n.strip().lower() for n in names):
        if name not in MODELS:
            raise ValueError(f"unknown model {name!r}; choose from {', '.join(MODELS)}")
        models.append(MODELS[name]())
    return models
