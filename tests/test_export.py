import json
from datetime import date

import pytest

from tests.helpers import NOW, make_record
from why import __version__, config, export
from why.sentiment import SentimentResult
from why.warehouse import Warehouse

JUNK = "Are Investors Undervaluing Global Partners (GLP) Right Now?"


def scored_warehouse(tmp_path, records, scores):
    """Warehouse with `records` loaded and {title: {model: SentimentResult}} applied."""
    wh = Warehouse(tmp_path)
    wh.upsert_headlines(records)
    ids = dict(wh.con.execute("SELECT title, headline_id FROM headlines").fetchall())
    for title, by_model in scores.items():
        for model, result in by_model.items():
            wh.add_sentiment(model, [(ids[title], result)], NOW)
    return wh


def pair(vader, finbert):
    return {"vader": SentimentResult(*vader), "finbert": SentimentResult(*finbert)}


def on_day(title, day, topic="Markets", **kwargs):
    return make_record(title, topic=topic, run_date=day, collected_at=f"{day}T09:00:00Z", **kwargs)


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
        status = export.build_status(wh, generated_at=NOW)
        agreement = export.build_agreement(wh, generated_at=NOW)
    assert latest["run_date"] is None
    assert all(t["articles"] == [] for t in latest["topics"])
    assert status["history"]["headlines"] == 0 and status["daily"] == []
    assert status["models"] == {"primary": None, "available": []}
    assert agreement["score_pairs"] == [] and agreement["disagreements"] == []


def test_trends_average_per_topic_per_day(tmp_path):
    records = [
        on_day("a", "2026-09-12"),
        on_day("b", "2026-09-12"),
        on_day("c", "2026-09-14"),
        on_day("t", "2026-09-14", topic="Tesla"),
        on_day("too old", "2026-09-01"),
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
        default = export.build_trends(wh, generated_at=NOW)

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

    assert default["days"] == 30 and len(default["topics"][0]["series"]) == 30
    assert default["start_date"] == "2026-08-16"
    assert sum(d["count"] for d in default["topics"][0]["series"]) == 4  # the 1st is inside 30 days


def test_agreement_report(tmp_path):
    records = [make_record(t) for t in ("a", "b", "c", "d")]
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
    assert all(t["n"] == 0 and t["cohens_kappa"] is None for t in empty["by_topic"])


def test_agreement_by_topic_score_pairs_and_disagreements(tmp_path):
    shared = "https://example.com/news/shared-story"
    records = [
        on_day("m1", "2026-09-13"),
        on_day("m2", "2026-09-14"),
        on_day("m3", "2026-09-14"),
        on_day("t1", "2026-09-14", topic="Tesla"),
        on_day("shared", "2026-09-12", topic="Tesla", link=shared),
        on_day("shared", "2026-09-12", topic="Markets", link=shared),
        on_day(JUNK, "2026-09-14"),
    ]
    scores = {
        "m1": pair(("positive", 0.6), ("negative", -0.6)),  # the largest gap, but older
        "m2": pair(("positive", 0.1), ("neutral", 0.0)),
        "m3": pair(("negative", -0.2), ("positive", 0.7)),
        "t1": pair(("neutral", 0.0), ("neutral", 0.02)),
        "shared": pair(("neutral", 0.0), ("negative", -0.5)),
        JUNK: pair(("positive", 0.9), ("negative", -0.9)),  # scored before the rule existed
    }
    with scored_warehouse(tmp_path, records, scores) as wh:
        report = export.build_agreement(wh, generated_at=NOW)
        capped = export.build_agreement(
            wh, generated_at=NOW, max_score_pairs=2, max_disagreements=1
        )

    assert report["n"] == 5  # the shared story counts once, the screener not at all
    assert [d["title"] for d in report["disagreements"]] == ["m3", "m2", "m1", "shared"]
    assert report["disagreements"][0] == {
        "id": report["disagreements"][0]["id"],
        "topic": "Markets",
        "title": "m3",
        "source": "Reuters",
        "link": "https://example.com/news/m3",
        "run_date": "2026-09-14",
        "a": {"label": "negative", "score": -0.2},
        "b": {"label": "positive", "score": 0.7},
        "gap": 0.9,
    }
    assert report["disagreements"][-1]["topic"] == "Markets"  # first configured topic wins

    assert [t["topic"] for t in report["by_topic"]] == [t["label"] for t in config.TOPICS]
    by_topic = {t["topic"]: t for t in report["by_topic"]}
    assert by_topic["Markets"]["n"] == 4
    assert by_topic["Tesla"] == {
        "topic": "Tesla",
        "n": 2,
        "percent_agreement": 50.0,
        "cohens_kappa": by_topic["Tesla"]["cohens_kappa"],
    }
    assert by_topic["AI"] == {
        "topic": "AI", "n": 0, "percent_agreement": None, "cohens_kappa": None,
    }  # fmt: skip

    assert len(report["score_pairs"]) == 5
    assert all(set(p) == {"a", "b", "same"} for p in report["score_pairs"])
    assert sum(p["same"] for p in report["score_pairs"]) == 1
    assert {"a": 0.0, "b": 0.02, "same": True} in report["score_pairs"]
    assert (len(capped["score_pairs"]), len(capped["disagreements"]), capped["n"]) == (2, 1, 5)
    assert capped["score_pairs"] == report["score_pairs"][:2]  # deterministic order
    assert JUNK not in json.dumps(report)


def test_low_quality_titles_are_hidden_from_every_export(tmp_path):
    records = [
        make_record("Oil slides on weak demand"),
        make_record(JUNK),
        make_record("symbol__ Stock Quote Price and Forecast", topic="Tesla", source="CNN"),
    ]
    with Warehouse(tmp_path) as wh:
        wh.upsert_headlines(records)
        pending = [title for _, title in wh.pending_sentiment("vader")]
        assert pending == ["Oil slides on weak demand"]  # junk is never scored
        # history scored before the rules existed still carries scores for the junk
        for (headline_id,) in wh.con.execute("SELECT headline_id FROM headlines").fetchall():
            wh.add_sentiment("vader", [(headline_id, SentimentResult("positive", 0.5))], NOW)
            wh.add_sentiment("finbert", [(headline_id, SentimentResult("negative", -0.5))], NOW)

        latest = export.build_latest(wh, generated_at=NOW)
        trends = export.build_trends(wh, generated_at=NOW)
        agreement = export.build_agreement(wh, generated_at=NOW)
        status = export.build_status(wh, generated_at=NOW)

    dumped = json.dumps([latest, trends, agreement, status])
    assert JUNK not in dumped and "symbol__" not in dumped and "CNN" not in dumped
    articles = [a["title"] for t in latest["topics"] for a in t["articles"]]
    assert articles == ["Oil slides on weak demand"]
    assert sum(d["count"] for t in trends["topics"] for d in t["series"]) == 1
    assert agreement["n"] == 1 and len(agreement["disagreements"]) == 1
    assert status["history"]["headlines"] == 1
    assert status["history"]["excluded_low_quality"] == 2
    assert status["history"]["sentiment"] == {"finbert": 1, "vader": 1}


def test_status_json(tmp_path):
    records = [
        on_day("Fed holds rates", "2026-09-13"),
        on_day("Fed holds rates", "2026-09-14"),  # same link: seen again
        on_day("Oil slides", "2026-09-14", source="Bloomberg"),
        on_day("Tesla rallies", "2026-09-14", topic="Tesla"),
    ]
    neutral = {"vader": SentimentResult("neutral", 0.0)}
    scores = {"Fed holds rates": neutral, "Oil slides": neutral, "Tesla rallies": neutral}
    run = {
        "run_date": "2026-09-14",
        "mode": "replay",
        "raw_records": 3,
        "inserted": 0,
        "seen_again": 3,
        "scored": {"vader": 0},
        "failed_topics": [],
        "filtered_low_quality": 0,
        "requests": 0,
        "backfill": None,
        "history_before": 3,  # internal: not part of status.json
    }
    with scored_warehouse(tmp_path, records, scores) as wh:
        status = export.build_status(wh, run=run, generated_at=NOW)
        rebuilt = export.build_status(wh, generated_at=NOW)

    assert list(status) == [
        "generated_at", "version", "schedule", "run", "history", "models", "topics", "daily",
        "sources", "config",
    ]  # fmt: skip
    assert status["generated_at"] == "2026-09-14T09:00:00Z"
    assert (status["version"], status["schedule"]) == (__version__, "0 9 * * *")
    assert status["run"] == {key: run[key] for key in export.RUN_FIELDS}
    assert rebuilt["run"] is None
    assert status["history"] == {
        "headlines": 3,
        "excluded_low_quality": 0,
        "sentiment": {"vader": 3},
        "first_run_date": "2026-09-13",
        "last_run_date": "2026-09-14",
        "run_days": 2,
        "parquet_files": 0,
    }
    assert status["models"] == {"primary": "vader", "available": ["vader"]}
    assert status["topics"][:3] == [
        {"label": "Markets", "query": "stock market", "edition": 2, "total": 2},
        {"label": "Tesla", "query": "TSLA Tesla", "edition": 1, "total": 1},
        {"label": "AI", "query": "artificial intelligence", "edition": 0, "total": 0},
    ]
    assert status["daily"] == [
        {"run_date": "2026-09-13", "new_headlines": 1, "seen_again": 0},
        {"run_date": "2026-09-14", "new_headlines": 2, "seen_again": 1},
    ]
    assert status["sources"] == [{"source": "Reuters", "n": 2}, {"source": "Bloomberg", "n": 1}]
    assert status["config"] == {"max_per_topic": 8, "trend_days": 30}
