import sys
import types

import pytest

from why import sentiment
from why.sentiment import FinbertModel, SentimentResult, VaderModel, label_from_compound


@pytest.mark.parametrize(
    ("compound", "label"),
    [
        (0.05, "positive"),
        (0.9, "positive"),
        (0.0499, "neutral"),
        (0.0, "neutral"),
        (-0.0499, "neutral"),
        (-0.05, "negative"),
        (-0.9, "negative"),
    ],
)
def test_vader_thresholds(compound, label):
    assert label_from_compound(compound) == label


def test_vader_scores_obvious_headlines():
    good, bad, flat = VaderModel().score(
        [
            "Investors cheer excellent earnings and strong growth",
            "Markets crash amid fears of a terrible recession",
            "Company to hold annual meeting on Tuesday",
        ]
    )
    assert good.label == "positive" and good.score > 0.05
    assert bad.label == "negative" and bad.score < -0.05
    assert flat == SentimentResult("neutral", 0.0)


def test_finbert_imports_transformers_lazily(monkeypatch):
    monkeypatch.delitem(sys.modules, "transformers", raising=False)
    FinbertModel()
    assert "transformers" not in sys.modules
    assert FinbertModel().score([]) == []


def test_finbert_adapter_with_a_fake_pipeline(monkeypatch):
    calls = {}

    def fake_pipeline(task, model, top_k):
        calls["init"] = (task, model, top_k)

        def classify(texts, **kwargs):
            calls["texts"], calls["kwargs"] = texts, kwargs
            outputs = [
                [
                    {"label": "positive", "score": 0.7},
                    {"label": "neutral", "score": 0.2},
                    {"label": "negative", "score": 0.1},
                ],
                [
                    {"label": "Negative", "score": 0.6},
                    {"label": "neutral", "score": 0.3},
                    {"label": "positive", "score": 0.1},
                ],
                {"label": "neutral", "score": 0.9},  # top_k=1 shape
            ]
            return outputs[: len(texts)]

        return classify

    fake = types.ModuleType("transformers")
    fake.pipeline = fake_pipeline
    monkeypatch.setitem(sys.modules, "transformers", fake)

    model = FinbertModel(batch_size=4)
    results = model.score(["beat", "miss", "meeting"])
    model.score(["again"])  # the pipeline is built once

    assert calls["init"] == ("text-classification", "ProsusAI/finbert", None)
    assert calls["kwargs"] == {"batch_size": 4, "truncation": True}
    assert results == [
        SentimentResult("positive", 0.6),
        SentimentResult("negative", -0.5),
        SentimentResult("neutral", 0.0),
    ]


def test_get_models_rejects_unknown_names():
    assert [m.name for m in sentiment.get_models(["VADER", "vader"])] == ["vader"]
    with pytest.raises(ValueError, match="unknown model"):
        sentiment.get_models(["gpt"])
