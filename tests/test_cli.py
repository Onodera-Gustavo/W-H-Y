import json
from datetime import UTC, date, datetime, timedelta

import pytest

from tests.helpers import NOW, FixedModel, rss
from why import config, ingest, sentiment
from why.cli import compare, main, run_pipeline

TOPICS = len(config.TOPICS)
UNIQUE_PER_TOPIC = 4  # the fixture has 6 items: 1 too old, 1 duplicate link


def snapshot(folder):
    return {p.relative_to(folder): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_running_twice_does_not_duplicate_anything(paths, offline_feed):
    first = run_pipeline(paths, now=NOW)
    raw_after_first = snapshot(paths.raw_dir)

    second = run_pipeline(paths, now=NOW + timedelta(hours=1))

    assert len(offline_feed) == 2 * TOPICS  # one request per topic per run
    assert first["inserted"] == UNIQUE_PER_TOPIC * TOPICS
    assert first["scored"] == {"vader": UNIQUE_PER_TOPIC}  # same links in every topic
    assert second["inserted"] == 0
    assert second["seen_again"] == UNIQUE_PER_TOPIC * TOPICS
    assert second["history_after"] == first["history_after"] == UNIQUE_PER_TOPIC * TOPICS
    assert second["scored"] == {"vader": 0}
    assert snapshot(paths.raw_dir) == raw_after_first

    assert list((paths.history_dir / "headlines").glob("*.parquet"))
    assert list((paths.history_dir / "sentiment").glob("*.parquet"))
    latest = read_json(paths.latest_json)
    trends = read_json(paths.trends_json)
    assert sum(len(t["articles"]) for t in latest["topics"]) == UNIQUE_PER_TOPIC * TOPICS
    assert trends["end_date"] == "2026-09-14"


def test_past_dates_are_replayed_from_raw_without_network(paths, offline_feed):
    run_pipeline(paths, now=NOW)
    replay = run_pipeline(paths, run_date=NOW.date(), now=NOW + timedelta(days=1))

    assert len(offline_feed) == TOPICS  # the replay made no request
    assert replay["mode"] == "replay"
    assert replay["inserted"] == 0

    with pytest.raises(FileNotFoundError):
        run_pipeline(paths, run_date=date(2026, 9, 1), now=NOW)
    with pytest.raises(ValueError, match="future"):
        run_pipeline(paths, run_date=date(2026, 9, 15), now=NOW)


def test_run_and_replay_write_status_json(paths, offline_feed):
    run_pipeline(paths, now=NOW)
    status = read_json(paths.status_json)

    assert status["run"] == {
        "run_date": "2026-09-14",
        "mode": "fetch",
        "raw_records": UNIQUE_PER_TOPIC * TOPICS,
        "inserted": UNIQUE_PER_TOPIC * TOPICS,
        "seen_again": 0,
        "scored": {"vader": UNIQUE_PER_TOPIC},
        "failed_topics": [],
        "filtered_low_quality": 0,
        "requests": TOPICS,
        "backfill": None,
    }
    assert status["history"]["parquet_files"] == 2
    assert status["topics"][0] == {
        "label": "Markets", "query": "stock market", "edition": 4, "total": 4,
    }  # fmt: skip
    assert status["config"]["trend_days"] == 30

    run_pipeline(paths, run_date=NOW.date(), now=NOW + timedelta(days=1))
    replay = read_json(paths.status_json)["run"]
    assert (replay["mode"], replay["requests"], replay["seen_again"]) == ("replay", 0, 24)


def test_the_daily_run_keeps_eight_good_headlines_per_topic(paths, monkeypatch):
    newest = datetime(2026, 9, 14, 8, 30, tzinfo=UTC)
    junk = [
        {"title": "symbol__ Stock Quote Price and Forecast", "published": newest},
        {"title": "Are Investors Undervaluing Global Partners (GLP) Right Now?",
         "published": newest},
    ]  # fmt: skip
    news = [
        {"title": f"Headline {i}", "published": newest - timedelta(minutes=10 + i)}
        for i in range(12)
    ]
    feed = rss(junk + news)
    monkeypatch.setattr(ingest, "fetch_feed", lambda search, session=None: feed)

    summary = run_pipeline(paths, now=NOW)

    assert summary["filtered_low_quality"] == 2 * TOPICS
    latest = read_json(paths.latest_json)
    for topic in latest["topics"]:
        assert [a["title"] for a in topic["articles"]] == [f"Headline {i}" for i in range(8)]


def test_compare_writes_the_agreement_report(paths, offline_feed, monkeypatch):
    monkeypatch.setitem(sentiment.MODELS, "finbert", FixedModel)
    run_pipeline(paths, model_names=["vader", "finbert"], now=NOW)

    report = compare(paths, now=NOW)

    assert report["n"] == UNIQUE_PER_TOPIC
    assert sum(map(sum, report["confusion_matrix"]["matrix"])) == UNIQUE_PER_TOPIC
    stored = read_json(paths.agreement_json)
    assert stored["models"] == ["vader", "finbert"]
    assert {"by_topic", "score_pairs", "disagreements"} <= set(stored)
    assert len(stored["score_pairs"]) == UNIQUE_PER_TOPIC


def test_cli_entry_point(paths, offline_feed, monkeypatch, capsys):
    monkeypatch.setenv("WHY_DATA_DIR", str(paths.data_dir))
    monkeypatch.setenv("WHY_SITE_DATA_DIR", str(paths.site_data_dir))

    assert main(["run", "--models", "vader"]) == 0
    assert main(["compare"]) == 0
    assert paths.agreement_json.exists()
    assert paths.status_json.exists()
    assert main(["run", "--date", "2000-01-01"]) == 1  # no raw partition to replay

    with pytest.raises(SystemExit):
        main(["run", "--models", "gpt"])
    assert "unknown model" in capsys.readouterr().err


def test_the_workflow_schedule_is_the_one_status_json_reports():
    workflow = (config.ROOT / ".github" / "workflows" / "pipeline.yml").read_text(encoding="utf-8")
    assert f'cron: "{config.SCHEDULE}"' in workflow
