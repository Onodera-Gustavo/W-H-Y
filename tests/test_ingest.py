from datetime import UTC, date, datetime, timedelta

import pytest
import requests

from tests.helpers import NOW, http_error, rss
from why import ingest


def parse(feed_bytes, **kwargs):
    return ingest.parse_feed(feed_bytes, "Markets", collected_at=NOW, run_date=NOW.date(), **kwargs)


def test_parse_feed_builds_raw_records(feed_bytes):
    parsed = parse(feed_bytes)
    records = parsed.records

    assert [r["title"] for r in records] == [
        "Stocks rally as Fed signals a pause",  # its copy with other tracking parameters is gone
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
    assert records[2]["source"] == "CNBC"  # taken from the title when <source> is missing
    assert records[3]["published_at"] is None
    assert (parsed.low_quality, parsed.outside_window) == (0, 1)


def test_parse_feed_drops_old_items_and_caps_the_list(feed_bytes):
    assert all("Old story" not in r["title"] for r in parse(feed_bytes).records)
    assert len(parse(feed_bytes, max_items=2).records) == 2


def test_low_quality_titles_are_dropped_before_the_cap():
    newest = datetime(2026, 9, 14, 8, 30, tzinfo=UTC)
    junk = [
        {"title": f"Are Investors Undervaluing Company {i} (CO{chr(65 + i)}) Right Now?",
         "published": newest - timedelta(minutes=i)}
        for i in range(5)
    ]  # fmt: skip
    news = [
        {"title": f"Real headline number {i}", "published": newest - timedelta(hours=1, minutes=i)}
        for i in range(10)
    ]
    parsed = parse(rss(junk + news))

    assert parsed.low_quality == 5
    assert [r["title"] for r in parsed.records] == [f"Real headline number {i}" for i in range(8)]


def test_extra_fields_are_added_without_replacing_the_schema(feed_bytes):
    records = parse(feed_bytes, extra={"collection": "backfill", "topic": "ignored"}).records
    assert {r["collection"] for r in records} == {"backfill"}
    assert {r["topic"] for r in records} == {"Markets"}


def test_is_recent_assumes_utc_when_the_date_has_no_offset():
    now = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)
    assert ingest.is_recent("Mon, 14 Sep 2026 08:00:00", now=now)
    assert not ingest.is_recent("Sat, 12 Sep 2026 08:00:00", now=now)
    assert ingest.parse_published("Mon, 14 Sep 2026 08:00:00").tzinfo is UTC


def test_is_recent_keeps_items_with_invalid_or_missing_dates():
    assert ingest.is_recent("not a date", now=NOW)
    assert ingest.is_recent("", now=NOW)
    assert ingest.parse_published("not a date") is None


def test_the_backfill_window_is_one_utc_day():
    on_the_12th = ingest.on_utc_day(date(2026, 9, 12))
    assert on_the_12th(datetime(2026, 9, 12, 0, 0, tzinfo=UTC))
    assert on_the_12th(datetime(2026, 9, 12, 23, 59, 59, tzinfo=UTC))
    assert not on_the_12th(datetime(2026, 9, 11, 23, 59, 59, tzinfo=UTC))
    assert not on_the_12th(datetime(2026, 9, 13, 0, 0, tzinfo=UTC))
    assert not on_the_12th(None)  # undated items cannot be placed on the day
    # 20:00 in California on the 12th is already the 13th in UTC
    assert not on_the_12th(ingest.parse_published("Sat, 12 Sep 2026 20:00:00 -0700"))


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


def test_day_query_covers_the_utc_day_with_pacific_calendar_dates():
    assert (
        ingest.day_query("stock market", date(2026, 9, 13))
        == "stock market after:2026-09-12 before:2026-09-14"
    )
    assert (
        ingest.day_query("oil energy", date(2026, 10, 1))
        == "oil energy after:2026-09-30 before:2026-10-02"
    )
    url = ingest.search_url(ingest.day_query("stock market", date(2026, 9, 13)))
    assert url.startswith(
        "https://news.google.com/rss/search?q=stock+market+after%3A2026-09-12+before%3A2026-09-14&"
    )


def test_collect_makes_one_request_per_topic_and_skips_failures(feed_bytes):
    topics = [{"label": "A", "query": "a"}, {"label": "B", "query": "b"}]
    calls = []

    def fetch(search, session):
        calls.append(search)
        if search.startswith("b "):
            raise requests.ConnectionError("boom")
        return feed_bytes

    result = ingest.collect(topics, run_date=NOW.date(), now=NOW, fetch=fetch)

    assert calls == ["a when:1d", "b when:1d"]
    assert result.failed == ["B"]
    assert (result.requests, result.blocked) == (2, None)
    assert {r["topic"] for r in result.records} == {"A"}


@pytest.mark.parametrize("status", [403, 429])
def test_collect_stops_at_once_when_the_feed_asks_to(feed_bytes, status):
    topics = [{"label": label, "query": label.lower()} for label in ("A", "B", "C")]
    calls = []

    def fetch(search, session):
        calls.append(search)
        if search.startswith("b "):
            raise http_error(status)
        return feed_bytes

    result = ingest.collect(topics, run_date=NOW.date(), now=NOW, fetch=fetch)

    assert calls == ["a when:1d", "b when:1d"]  # C is never requested
    assert result.blocked == status
    assert result.failed == ["B", "C"]
    assert result.requests == 2
    assert {r["topic"] for r in result.records} == {"A"}


def test_a_server_error_does_not_stop_the_collection(feed_bytes):
    topics = [{"label": label, "query": label.lower()} for label in ("A", "B", "C")]

    def fetch(search, session):
        if search.startswith("b "):
            raise http_error(500)
        return feed_bytes

    result = ingest.collect(topics, run_date=NOW.date(), now=NOW, fetch=fetch)
    assert (result.failed, result.blocked, result.requests) == (["B"], None, 3)


def test_a_pacer_waits_between_requests_but_not_before_the_first(feed_bytes):
    topics = [{"label": label, "query": label.lower()} for label in ("A", "B", "C")]
    sleeps = []
    pacer = ingest.Pacer(3.0, sleeps.append)

    def fetch(search, session):
        return feed_bytes

    ingest.collect(topics, run_date=NOW.date(), now=NOW, fetch=fetch, pacer=pacer)
    assert sleeps == [3.0, 3.0]
    ingest.collect(topics[:1], run_date=NOW.date(), now=NOW, fetch=fetch, pacer=pacer)
    assert sleeps == [3.0, 3.0, 3.0]  # a shared pacer also spaces two collections
