import json
import re
from datetime import UTC, date, datetime, timedelta

import pytest
import requests

from tests.helpers import http_error, make_record, rss
from why import backfill, config, ingest, raw
from why.cli import backfill_pipeline, main, run_pipeline

TOPICS = len(config.TOPICS)
NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)  # today, for every test below
COLLECTED = datetime(2026, 9, 15, 12, 0, 5, tzinfo=UTC)
JUNK = "Are Investors Undervaluing Global Partners (GLP) Right Now?"


def window_feed(search: str) -> bytes:
    """Roughly what a date search returns: 12 items on every day from `after` to `before`,
    more than the cap, plus a screener headline as the newest item of the day in between."""
    match = re.fullmatch(r"(.+) after:(\S+) before:(\S+)", search)
    assert match, f"not a date search: {search!r}"
    query, after, before = match[1], date.fromisoformat(match[2]), date.fromisoformat(match[3])
    target = after + timedelta(days=1)
    items = [{"title": JUNK, "published": datetime(*target.timetuple()[:3], 23, 30, tzinfo=UTC)}]
    day = after
    while day <= before:
        for hour in range(0, 24, 2):
            items.append(
                {
                    "title": f"{query} story on {day} at {hour:02d}h",
                    "published": datetime(day.year, day.month, day.day, hour, tzinfo=UTC),
                    "link": f"https://example.com/{config.slug(query)}/{day}/{hour}",
                }
            )
        day += timedelta(days=1)
    return rss(items)


class FakeFeed:
    """Stands in for ingest.fetch_feed. `fail` maps a request number (from 1) to an HTTP
    status or an exception."""

    def __init__(self, fail: dict | None = None):
        self.calls: list[str] = []
        self.fail = fail or {}

    def __call__(self, search, session=None):
        self.calls.append(search)
        problem = self.fail.get(len(self.calls))
        if isinstance(problem, int):
            raise http_error(problem)
        if problem is not None:
            raise problem
        return window_feed(search)


def run_backfill(paths, feed, days):
    sleeps: list[float] = []
    summary = backfill_pipeline(
        paths, days=days, now=NOW, fetch=feed, sleeper=sleeps.append, clock=lambda: COLLECTED
    )
    return summary, sleeps


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_run_dates_go_from_today_minus_n_to_yesterday():
    today = date(2026, 9, 15)
    assert backfill.run_dates(today, 3) == [date(2026, 9, 12), date(2026, 9, 13), date(2026, 9, 14)]
    assert backfill.run_dates(today, 1) == [date(2026, 9, 14)]
    assert backfill.edition_day(date(2026, 9, 14)) == date(2026, 9, 13)
    for bad in (0, config.BACKFILL_MAX_DAYS + 1):
        with pytest.raises(ValueError, match="between 1 and 60"):
            backfill.run_dates(today, bad)


def test_each_run_date_holds_the_headlines_published_the_day_before(paths):
    feed = FakeFeed()
    summary, sleeps = run_backfill(paths, feed, days=2)

    assert len(feed.calls) == 2 * TOPICS
    assert feed.calls[0] == "stock market after:2026-09-11 before:2026-09-13"  # run date 13
    assert feed.calls[TOPICS] == "stock market after:2026-09-12 before:2026-09-14"  # run date 14
    assert sleeps == [config.BACKFILL_SLEEP] * (2 * TOPICS - 1)  # none before the first request

    for run_date, day in [(date(2026, 9, 13), "2026-09-12"), (date(2026, 9, 14), "2026-09-13")]:
        records = raw.read_partition(paths.raw_dir, run_date)
        assert len(records) == config.MAX_PER_TOPIC * TOPICS
        assert {r["published_at"][:10] for r in records} == {day}
        assert {r["run_date"] for r in records} == {run_date.isoformat()}
        assert {r["collection"] for r in records} == {"backfill"}
        assert {r["collected_at"] for r in records} == {"2026-09-15T12:00:05Z"}
        assert JUNK not in {r["title"] for r in records}
        markets = [r for r in records if r["topic"] == "Markets"]
        # newest first, and the screener item was dropped before the cap
        assert markets[0]["published_at"] == f"{day}T22:00:00Z"
        assert markets[-1]["published_at"] == f"{day}T08:00:00Z"

    assert summary["mode"] == "backfill"
    assert summary["run_date"] == "2026-09-14"
    assert summary["requests"] == 2 * TOPICS
    assert summary["filtered_low_quality"] == 2 * TOPICS
    assert summary["inserted"] == 2 * config.MAX_PER_TOPIC * TOPICS
    assert summary["backfill"] == {
        "days": 2,
        "first_run_date": "2026-09-13",
        "last_run_date": "2026-09-14",
        "fetched": ["2026-09-13", "2026-09-14"],
        "skipped": [],
        "empty": [],
        "records": 2 * config.MAX_PER_TOPIC * TOPICS,
    }


def test_a_failed_topic_is_logged_and_skipped(paths):
    feed = FakeFeed(fail={2: requests.ConnectionError("boom"), 3: http_error(500)})
    summary, _ = run_backfill(paths, feed, days=1)

    assert len(feed.calls) == TOPICS
    assert summary["failed_topics"] == ["Tesla (2026-09-14)", "AI (2026-09-14)"]
    landed = {r["topic"] for r in raw.read_partition(paths.raw_dir, date(2026, 9, 14))}
    assert landed == {t["label"] for t in config.TOPICS} - {"Tesla", "AI"}


def test_run_dates_that_already_have_a_partition_are_skipped(paths):
    live_day = date(2026, 9, 14)
    live = make_record("Live run headline", published_at="2026-09-14T08:00:00Z")
    raw.write_partition(paths.raw_dir, live_day, [live])
    live_bytes = (raw.partition_dir(paths.raw_dir, live_day) / "markets.jsonl").read_bytes()

    feed = FakeFeed()
    summary, _ = run_backfill(paths, feed, days=2)

    assert len(feed.calls) == TOPICS
    assert all(call.endswith("after:2026-09-11 before:2026-09-13") for call in feed.calls)
    assert (raw.partition_dir(paths.raw_dir, live_day) / "markets.jsonl").read_bytes() == live_bytes
    assert summary["backfill"]["fetched"] == ["2026-09-13"]
    assert summary["backfill"]["skipped"] == ["2026-09-14"]
    latest = read_json(paths.latest_json)
    assert latest["run_date"] == "2026-09-14"
    assert [a["title"] for a in latest["topics"][0]["articles"]] == ["Live run headline"]

    again_feed = FakeFeed()
    again, _ = run_backfill(paths, again_feed, days=2)  # resumable: nothing left to fetch
    assert again_feed.calls == []
    assert (again["requests"], again["inserted"]) == (0, 0)


@pytest.mark.parametrize("status", [429, 403])
def test_http_429_or_403_aborts_the_whole_backfill(paths, status):
    feed = FakeFeed(fail={TOPICS + 2: status})  # second topic of the second run date

    with pytest.raises(backfill.BackfillAborted, match=f"HTTP {status}"):
        run_backfill(paths, feed, days=3)

    assert len(feed.calls) == TOPICS + 2  # nothing requested after the block
    assert raw.partition_dates(paths.raw_dir) == [date(2026, 9, 12)]  # written before: kept
    assert not paths.status_json.exists()  # aborted before loading and exporting


def test_backfill_from_the_command_line(paths, monkeypatch, capsys):
    monkeypatch.setenv("WHY_DATA_DIR", str(paths.data_dir))
    monkeypatch.setenv("WHY_SITE_DATA_DIR", str(paths.site_data_dir))
    blocked = FakeFeed(fail={1: 429})
    monkeypatch.setattr(ingest, "fetch_feed", blocked)

    assert main(["backfill", "--days", "2", "--sleep", "0"]) == 1
    assert len(blocked.calls) == 1
    assert raw.partition_dates(paths.raw_dir) == []

    working = FakeFeed()
    monkeypatch.setattr(ingest, "fetch_feed", working)
    assert main(["backfill", "--days", "1", "--sleep", "0", "--models", "vader"]) == 0
    assert len(working.calls) == TOPICS
    assert read_json(paths.status_json)["run"]["mode"] == "backfill"

    bad_arguments = [
        ["--days", "0"],
        ["--days", "61"],
        ["--days", "x"],
        ["--days", "1", "--sleep", "-1"],
    ]
    for bad in bad_arguments:
        with pytest.raises(SystemExit):
            main(["backfill", *bad])
    assert "expected" in capsys.readouterr().err


def test_trends_status_and_replay_see_the_backfilled_days(paths):
    run_backfill(paths, FakeFeed(), days=3)

    trends = read_json(paths.trends_json)
    assert trends["days"] == config.TREND_DAYS == 30
    assert (trends["start_date"], trends["end_date"]) == ("2026-08-16", "2026-09-14")
    markets = trends["topics"][0]["series"]
    assert [(d["date"], d["count"]) for d in markets[-4:]] == [
        ("2026-09-11", 0),
        ("2026-09-12", 8),
        ("2026-09-13", 8),
        ("2026-09-14", 8),
    ]
    assert markets[-1]["sentiment"]["vader"]["n"] == 8

    status = read_json(paths.status_json)
    assert status["run"]["mode"] == "backfill"
    assert status["run"]["backfill"]["fetched"] == ["2026-09-12", "2026-09-13", "2026-09-14"]
    assert status["daily"] == [
        {"run_date": day, "new_headlines": 8 * TOPICS, "seen_again": 0}
        for day in ("2026-09-12", "2026-09-13", "2026-09-14")
    ]
    assert status["history"]["run_days"] == 3
    assert status["history"]["headlines"] == 3 * 8 * TOPICS

    latest = read_json(paths.latest_json)
    assert (latest["run_date"], latest["date_label"]) == ("2026-09-14", "Yesterday, Sep 13")

    replay = run_pipeline(paths, run_date=date(2026, 9, 13), now=NOW)  # same raw schema
    assert (replay["mode"], replay["inserted"], replay["seen_again"]) == ("replay", 0, 8 * TOPICS)
