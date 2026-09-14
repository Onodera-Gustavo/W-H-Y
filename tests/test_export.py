from datetime import date

import pytest

from tests.helpers import NOW, make_record
from why import export
from why.sentiment import SentimentResult
from why.warehouse import Warehouse


def scored_warehouse(tmp_path, records, scores):
    """Warehouse with `records` loaded and {title: {model: SentimentResult}} applied."""
    wh = Warehouse(tmp_path)
    wh.upsert_headlines(records)
    ids = {title: hid for hid, title in wh.pending_sentiment("any")}
    for title, by_model in scores.items():
        for model, result in by_model.items():
            wh.add_sentiment(model, [(ids[title], result)], NOW)
    return wh


def test_latest_json_has_the_fields_the_frontend_reads(tmp_path):
    records = [
        make_record("Stocks <b>rally</b>", published_at="2026-09-14T08:00:00Z"),
        make_record("Oil slides", published_at="2026-09-14T06:00:00Z"),
        make_record("Old but seen", run_date="2026-09-13", collected_at="2026-09-13T09:00:00Z"),
    ]
    scores = {
        "Stocks <b>rally</b>": {
            "vader": SentimentResult("positive", 0.4),
            "finbert": SentimentResult("positive", 0.8),
        },
        "Oil slides": {"vader": SentimentResult("negative", -0.3)},
    }
    with scored_warehouse(tmp_path, records, scores) as wh:
        latest = export.build_latest(wh, generated_at=NOW)

    top_keys = {"generated_at", "run_date", "date_label", "models", "primary_model", "topics"}
    assert top_keys <= set(latest)
    assert latest["run_date"] == "2026-09-14"
    assert latest["date_label"] == "Yesterday, Sep 13"
    assert latest["primary_model"] == "finbert"
    assert [t["label"] for t in latest["topics"]][:2] == ["Markets", "Tesla"]

    markets = latest["topics"][0]
    assert {"label", "query", "articles"} <= set(markets)
    assert [a["title"] for a in markets["articles"]] == ["Stocks <b>rally</b>", "Oil slides"]

    top, second = markets["articles"]
    assert {"id", "title", "link", "source", "published", "sentiment", "scores"} <= set(top)
    assert top["published"] == "2026-09-14T08:00:00Z"
    assert top["sentiment"] == {"model": "finbert", "label": "positive", "score": 0.8}
    assert set(top["scores"]) == {"finbert", "vader"}
    assert second["sentiment"]["model"] == "vader"  # falls back when FinBERT did not score it
    assert latest["topics"][1]["articles"] == []


def test_latest_json_on_an_empty_warehouse(tmp_path):
    with Warehouse(tmp_path) as wh:
        latest = export.build_latest(wh, generated_at=NOW)
    assert latest["run_date"] is None
    assert all(t["articles"] == [] for t in latest["topics"])


def test_trends_average_per_topic_per_day(tmp_path):
    def rec(title, day, topic="Markets"):
        return make_record(title, topic=topic, run_date=day, collected_at=f"{day}T09:00:00Z")

    records = [
        rec("a", "2026-09-12"),
        rec("b", "2026-09-12"),
        rec("c", "2026-09-14"),
        rec("t", "2026-09-14", topic="Tesla"),
        rec("too old", "2026-09-01"),
    ]
    scores = {
        "a": {"vader": SentimentResult("positive", 0.5)},
        "b": {"vader": SentimentResult("negative", -0.1)},
        "c": {"vader": SentimentResult("neutral", 0.0)},
        "t": {"vader": SentimentResult("negative", -0.6)},
        "too old": {"vader": SentimentResult("negative", -1.0)},
    }
    with scored_warehouse(tmp_path, records, scores) as wh:
        trends = export.build_trends(wh, end_date=date(2026, 9, 14), days=3, generated_at=NOW)

    assert (trends["start_date"], trends["end_date"]) == ("2026-09-12", "2026-09-14")
    assert trends["days"] == 3
    assert trends["primary_model"] == "vader"
    markets, tesla = trends["topics"][0], trends["topics"][1]

    assert [d["date"] for d in markets["series"]] == ["2026-09-12", "2026-09-13", "2026-09-14"]
    assert [d["count"] for d in markets["series"]] == [2, 0, 1]
    day_one = markets["series"][0]["sentiment"]["vader"]
    assert day_one["avg"] == pytest.approx(0.2)
    assert [day_one[k] for k in ("n", "positive", "neutral", "negative")] == [2, 1, 0, 1]
    assert markets["series"][1]["sentiment"] == {}
    assert tesla["series"][2]["sentiment"]["vader"]["avg"] == pytest.approx(-0.6)


def test_agreement_report(tmp_path):
    records = [make_record(t) for t in ("a", "b", "c", "d")]
    def pair(vader, finbert):
        return {"vader": SentimentResult(*vader), "finbert": SentimentResult(*finbert)}

    scores = {
        "a": pair(("positive", 0.5), ("positive", 0.9)),
        "b": pair(("positive", 0.2), ("neutral", 0.0)),
        "c": pair(("negative", -0.4), ("negative", -0.7)),
        "d": {"vader": SentimentResult("neutral", 0.0)},  # only one model: not paired
    }
    with scored_warehouse(tmp_path, records, scores) as wh:
        report = export.build_agreement(wh, generated_at=NOW)
        empty = export.build_agreement(wh, "vader", "nobody", generated_at=NOW)

    assert report["n"] == 3
    assert report["percent_agreement"] == pytest.approx(66.67)
    assert report["confusion_matrix"]["matrix"] == [[1, 1, 0], [0, 0, 0], [0, 0, 1]]
    assert report["label_distribution"]["finbert"] == {"positive": 1, "neutral": 1, "negative": 1}
    assert -1 <= report["cohens_kappa"] <= 1
    assert report["score_correlation"] > 0.9
    assert empty["n"] == 0 and empty["cohens_kappa"] is None
