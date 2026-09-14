import json
from datetime import date, timedelta

import pytest

from tests.helpers import NOW, FixedModel
from why import config, sentiment
from why.cli import compare, main, run_pipeline

TOPICS = len(config.TOPICS)
UNIQUE_PER_TOPIC = 4  # the fixture has 6 items: 1 too old, 1 duplicate link


def snapshot(folder):
    return {p.relative_to(folder): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


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
    latest = json.loads(paths.latest_json.read_text(encoding="utf-8"))
    trends = json.loads(paths.trends_json.read_text(encoding="utf-8"))
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


def test_compare_writes_the_agreement_report(paths, offline_feed, monkeypatch):
    monkeypatch.setitem(sentiment.MODELS, "finbert", FixedModel)
    run_pipeline(paths, model_names=["vader", "finbert"], now=NOW)

    report = compare(paths, now=NOW)

    assert report["n"] == UNIQUE_PER_TOPIC
    assert sum(map(sum, report["confusion_matrix"]["matrix"])) == UNIQUE_PER_TOPIC
    stored = json.loads(paths.agreement_json.read_text(encoding="utf-8"))
    assert stored["models"] == ["vader", "finbert"]


def test_cli_entry_point(paths, offline_feed, monkeypatch, capsys):
    monkeypatch.setenv("WHY_DATA_DIR", str(paths.data_dir))
    monkeypatch.setenv("WHY_SITE_DATA_DIR", str(paths.site_data_dir))

    assert main(["run", "--models", "vader"]) == 0
    assert main(["compare"]) == 0
    assert paths.agreement_json.exists()
    assert main(["run", "--date", "2000-01-01"]) == 1  # no raw partition to replay

    with pytest.raises(SystemExit):
        main(["run", "--models", "gpt"])
    assert "unknown model" in capsys.readouterr().err
