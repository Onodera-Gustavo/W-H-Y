from datetime import date

from tests.helpers import NOW, make_record
from why.sentiment import SentimentResult
from why.warehouse import Warehouse


def test_same_link_in_two_runs_is_stored_once(tmp_path):
    history = tmp_path / "history"
    day_one = make_record(
        "Fed holds rates",
        link="https://news.google.com/rss/articles/ABC?oc=5",
        collected_at="2026-09-13T09:00:00Z",
        run_date="2026-09-13",
    )
    day_two = make_record(
        "Fed holds rates",
        link="https://news.google.com/rss/articles/ABC/?oc=6&utm_source=x",
        collected_at="2026-09-14T09:00:00Z",
        run_date="2026-09-14",
    )

    with Warehouse(history) as wh:
        wh.load_history()
        assert wh.upsert_headlines([day_one]) == (1, 0)
        wh.export_history()

    with Warehouse(history) as wh:  # a new process, loading the Parquet history back
        assert wh.load_history()["headlines"] == 1
        assert wh.upsert_headlines([day_two]) == (0, 1)
        row = wh.con.execute(
            "SELECT count(*), min(first_run_date), max(last_run_date), min(link) FROM headlines"
        ).fetchone()

    assert row == (
        1,
        date(2026, 9, 13),
        date(2026, 9, 14),
        "https://news.google.com/rss/articles/ABC?oc=5",  # first sighting kept
    )


def test_duplicates_inside_one_batch_collapse(tmp_path):
    record = make_record("Oil slides")
    with Warehouse(tmp_path) as wh:
        assert wh.upsert_headlines([record, dict(record), dict(record)]) == (1, 0)
        assert wh.count() == 1


def test_story_under_two_topics_is_scored_once(tmp_path):
    link = "https://example.com/tesla-earnings"
    with Warehouse(tmp_path) as wh:
        wh.upsert_headlines(
            [
                make_record("Tesla earnings beat", topic="Markets", link=link),
                make_record("Tesla earnings beat", topic="Tesla", link=link),
            ]
        )
        assert wh.count() == 2
        pending = wh.pending_sentiment("vader")
        assert len(pending) == 1

        wh.add_sentiment("vader", [(pending[0][0], SentimentResult("positive", 0.4))], NOW)
        assert wh.pending_sentiment("vader") == []
        assert len(wh.pending_sentiment("finbert")) == 1  # a new model backfills history


def test_export_is_deterministic_and_partitioned_by_month(tmp_path):
    history = tmp_path / "history"
    records = [
        make_record("august story", run_date="2026-08-31", collected_at="2026-08-31T09:00:00Z"),
        make_record("september story"),
    ]
    with Warehouse(history) as wh:
        wh.upsert_headlines(records)
        files = wh.export_history()
        first = {p.name: p.read_bytes() for p in files}
        wh.export_history()
        second = {p.name: p.read_bytes() for p in files}

    assert sorted((history / "headlines").iterdir()) == [
        history / "headlines" / "2026-08.parquet",
        history / "headlines" / "2026-09.parquet",
    ]
    assert first == second
