from datetime import UTC, datetime

import pytest
import requests

from tests.helpers import NOW
from why import ingest


def parse(feed_bytes, **kwargs):
    return ingest.parse_feed(
        feed_bytes, "Markets", collected_at=NOW, run_date=NOW.date(), **kwargs
    )


def test_parse_feed_builds_raw_records(feed_bytes):
    records = parse(feed_bytes)

    assert [r["title"] for r in records] == [
        "Stocks rally as Fed signals a pause",
        "Stocks rally as Fed signals a pause",  # duplicate link, removed later by the dedup key
        "S&P 500 - Nasdaq close at record highs",
        "Oil slides on weak demand outlook",
        "Markets brace for Friday jobs report",  # undated items go last
    ]
    first = records[0]
    assert first == {
        "topic": "Markets",
        "title": "Stocks rally as Fed signals a pause",
        "source": "Reuters",
        "link": "https://news.google.com/rss/articles/CBMiTEST0001?oc=5",
        "published_at": "2026-09-14T07:30:00Z",
        "collected_at": "2026-09-14T09:00:00Z",
        "run_date": "2026-09-14",
    }
    assert records[3]["source"] == "CNBC"  # taken from the title when <source> is missing
    assert records[4]["published_at"] is None


def test_parse_feed_drops_old_items_and_caps_the_list(feed_bytes):
    assert all("Old story" not in r["title"] for r in parse(feed_bytes))
    assert len(parse(feed_bytes, max_items=2)) == 2


def test_is_recent_assumes_utc_when_the_date_has_no_offset():
    now = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)
    assert ingest.is_recent("Mon, 14 Sep 2026 08:00:00", now=now)
    assert not ingest.is_recent("Sat, 12 Sep 2026 08:00:00", now=now)
    assert ingest.parse_published("Mon, 14 Sep 2026 08:00:00").tzinfo is UTC


def test_is_recent_keeps_items_with_invalid_or_missing_dates():
    assert ingest.is_recent("not a date", now=NOW)
    assert ingest.is_recent("", now=NOW)
    assert ingest.parse_published("not a date") is None


@pytest.mark.parametrize(
    ("raw_title", "source", "expected"),
    [
        ("Tesla - the stock that will not quit - Yahoo Finance", "Yahoo Finance",
         ("Tesla - the stock that will not quit", "Yahoo Finance")),
        ("Tesla - the stock that will not quit - Yahoo Finance", None,
         ("Tesla - the stock that will not quit", "Yahoo Finance")),
        ("Fed holds rates - Reuters", "Reuters", ("Fed holds rates", "Reuters")),
        ("No source suffix here", None, ("No source suffix here", "Unknown")),
    ],
)  # fmt: skip
def test_split_title_handles_dashes_inside_headlines(raw_title, source, expected):
    assert ingest.split_title(raw_title, source) == expected


def test_feed_url_asks_for_english_us_results_inside_the_window():
    url = ingest.feed_url("TSLA Tesla")
    assert url.startswith("https://news.google.com/rss/search?q=TSLA+Tesla+when%3A1d")
    assert "hl=en-US" in url and "gl=US" in url and "ceid=US%3Aen" in url


def test_collect_makes_one_request_per_topic_and_skips_failures(feed_bytes):
    topics = [{"label": "A", "query": "a"}, {"label": "B", "query": "b"}]
    calls = []

    def fetch(query, session):
        calls.append(query)
        if query == "b":
            raise requests.ConnectionError("boom")
        return feed_bytes

    records, failed = ingest.collect(topics, run_date=NOW.date(), now=NOW, fetch=fetch)

    assert calls == ["a", "b"]
    assert failed == ["B"]
    assert {r["topic"] for r in records} == {"A"}
