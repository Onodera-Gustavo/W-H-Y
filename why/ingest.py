"""Collect headlines from the Google News RSS search feed.

The daily run asks for the last 24 hours with `when:1d`. The backfill asks for one past UTC
day with `after:` and `before:` (see day_query). Both parse a feed the same way: keep the items
inside the window, drop low quality titles, drop duplicate links, newest first, and only then
cap the topic at MAX_PER_TOPIC."""

import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode

import feedparser
import requests

from why import config, quality
from why.dedup import dedup_key
from why.timeutil import as_utc, to_iso, utc_now

log = logging.getLogger(__name__)

# (search string with its operators, session) -> feed bytes
Fetcher = Callable[[str, requests.Session | None], bytes]
# publication time (None when the feed gave no usable date) -> inside the window?
Window = Callable[[datetime | None], bool]


# search strings and URLs


def daily_query(query: str, days_back: int = config.DAYS_BACK) -> str:
    """Search string of the daily run. "when:1d" asks Google News for the window up front;
    recent_window() still filters locally."""
    return f"{query} when:{days_back}d"


def day_query(query: str, day: date) -> str:
    """Search string for the headlines published on one UTC day.

    Google News reads `after:X before:Y` as calendar dates in US Pacific time, half open:
    [X 00:00, Y 00:00) in America/Los_Angeles. Checked on 2026-09-15: "after:2026-09-09
    before:2026-09-10" returned pubDates from 2026-09-09T07:00Z to 2026-09-10T07:00Z, and
    "after:2026-09-09 before:2026-09-09" returned nothing. A UTC day starts at 16:00 or 17:00
    Pacific on the evening before, so it takes `after:day-1 before:day+1`: a 48 hour window
    that contains the whole UTC day in summer and winter time. on_utc_day() keeps the day."""
    after = day - timedelta(days=1)
    before = day + timedelta(days=1)
    return f"{query} after:{after.isoformat()} before:{before.isoformat()}"


def search_url(search: str) -> str:
    return f"{config.FEED_URL}?{urlencode({'q': search, **config.FEED_PARAMS})}"


def feed_url(query: str, days_back: int = config.DAYS_BACK) -> str:
    return search_url(daily_query(query, days_back))


# windows


def parse_published(value: str | None) -> datetime | None:
    """RFC 822 date from the feed as aware UTC, or None when missing or invalid."""
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return as_utc(dt)  # no offset in the string: assume UTC


def recent_window(now: datetime, days_back: int = config.DAYS_BACK) -> Window:
    """Window of the daily run: the last `days_back` days before `now`.

    Items with a missing or unparseable date are kept (the feed occasionally omits it);
    they land with published_at = null."""
    start = as_utc(now) - timedelta(days=days_back)

    def inside(published: datetime | None) -> bool:
        return published is None or published >= start

    return inside


def on_utc_day(day: date) -> Window:
    """Window of the backfill: published on `day`, in UTC. Undated items are dropped, since
    nothing places them on that day."""

    def inside(published: datetime | None) -> bool:
        return published is not None and published.date() == day

    return inside


def is_recent(
    published: str | None, days_back: int = config.DAYS_BACK, now: datetime | None = None
) -> bool:
    """True when the item is inside the daily window (see recent_window)."""
    return recent_window(now or utc_now(), days_back)(parse_published(published))


# parsing


def split_title(raw_title: str | None, source: str | None = None) -> tuple[str, str]:
    """Google News appends " - Source" to every title.

    When the feed names the source, strip exactly that suffix; otherwise split on the last
    " - ", so headlines that contain " - " themselves survive."""
    raw_title = (raw_title or "").strip()
    source = (source or "").strip()
    if source and raw_title.endswith(f" - {source}"):
        return raw_title[: -len(source) - 3].strip(), source
    if " - " in raw_title:
        head, tail = raw_title.rsplit(" - ", 1)
        return head.strip(), source or tail.strip()
    return raw_title, source or "Unknown"


@dataclass
class ParsedFeed:
    records: list[dict]  # newest first, at most max_items
    low_quality: int = 0  # titles removed by why.quality before the cap
    outside_window: int = 0


def parse_feed(
    content: bytes,
    topic: str,
    *,
    collected_at: datetime,
    run_date: date,
    max_items: int = config.MAX_PER_TOPIC,
    days_back: int = config.DAYS_BACK,
    in_window: Window | None = None,
    extra: dict | None = None,
) -> ParsedFeed:
    """Feed bytes to raw records.

    Items outside the window (default: the daily window before collected_at), low quality
    titles and repeated links are removed before the list is cut to max_items, so a topic
    still gets up to max_items real headlines. `extra` adds fields to every record."""
    in_window = in_window or recent_window(collected_at, days_back)
    feed = feedparser.parse(content)
    if feed.bozo and not feed.entries:
        log.warning("%s: feed could not be parsed (%s)", topic, feed.get("bozo_exception"))

    parsed = ParsedFeed(records=[])
    candidates = []
    for entry in feed.entries:
        published = parse_published(entry.get("published"))
        if not in_window(published):
            parsed.outside_window += 1
            continue
        source_title = (entry.get("source") or {}).get("title")
        title, source = split_title(entry.get("title"), source_title)
        if quality.is_low_quality(title):
            parsed.low_quality += 1
            continue
        candidates.append(
            {
                **(extra or {}),
                "topic": topic,
                "title": title,
                "source": source,
                "link": entry.get("link") or "",
                "published_at": to_iso(published),
                "collected_at": to_iso(collected_at),
                "run_date": run_date.isoformat(),
            }
        )

    # ISO strings sort chronologically; undated items go last. The sort is stable, so items
    # with the same time keep the feed's own order.
    candidates.sort(key=lambda r: r["published_at"] or "", reverse=True)
    seen: set[str] = set()
    for record in candidates:
        key = dedup_key(record["link"], record["title"], record["source"])
        if key in seen:
            continue
        seen.add(key)
        parsed.records.append(record)
        if len(parsed.records) >= max_items:
            break
    return parsed


# requests


class Pacer:
    """Keeps requests sequential and spaced: waits `seconds` before every request but the
    first. Sharing one pacer between several collections spaces all of their requests."""

    def __init__(self, seconds: float = 0.0, sleep: Callable[[float], None] = time.sleep):
        self.seconds = seconds
        self._sleep = sleep
        self._first = True

    def wait(self) -> None:
        if not self._first and self.seconds > 0:
            self._sleep(self.seconds)
        self._first = False


def blocking_status(exc: requests.RequestException) -> int | None:
    """403 or 429 when the error carries one of them, None otherwise."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return status if status in config.BLOCKING_STATUS else None


def fetch_feed(search: str, session: requests.Session | None = None) -> bytes:
    """GET one search. `search` is the whole q parameter, operators included. No retries."""
    http = session or requests
    response = http.get(
        search_url(search),
        headers={"User-Agent": config.USER_AGENT},
        timeout=config.REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.content


@dataclass
class Collection:
    records: list[dict] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)  # labels of topics without headlines
    low_quality: int = 0
    requests: int = 0
    blocked: int | None = None  # HTTP status that stopped the collection (403 or 429)


def collect(
    topics: Iterable[dict],
    *,
    run_date: date,
    now: datetime | None = None,
    fetch: Fetcher | None = None,
    query: Callable[[str], str] = daily_query,
    in_window: Window | None = None,
    extra: dict | None = None,
    pacer: Pacer | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> Collection:
    """One request per topic, in order.

    A topic that fails is logged and skipped, so the rest still land. HTTP 403 or 429 stops
    the collection at once: the remaining topics are not requested, they are reported as
    failed and `blocked` holds the status. collected_at is `now` when given, otherwise the
    clock at each request."""
    fetch = fetch or fetch_feed
    pacer = pacer or Pacer()
    topics = list(topics)
    result = Collection()
    with requests.Session() as session:
        for index, topic in enumerate(topics):
            pacer.wait()
            collected_at = now or clock()
            result.requests += 1
            try:
                content = fetch(query(topic["query"]), session)
            except requests.RequestException as exc:
                result.failed.append(topic["label"])
                status = blocking_status(exc)
                if status:
                    log.error(
                        "%s: HTTP %d, the feed asks to stop: no more requests",
                        topic["label"], status,
                    )  # fmt: skip
                    result.blocked = status
                    result.failed.extend(t["label"] for t in topics[index + 1 :])
                    break
                log.warning("%s: download failed (%s)", topic["label"], exc)
                continue
            parsed = parse_feed(
                content,
                topic["label"],
                collected_at=collected_at,
                run_date=run_date,
                in_window=in_window,
                extra=extra,
            )
            result.low_quality += parsed.low_quality
            result.records.extend(parsed.records)
            log.info(
                "%-8s %d headlines (%d low quality and %d outside the window dropped)",
                topic["label"], len(parsed.records), parsed.low_quality, parsed.outside_window,
            )  # fmt: skip
    return result
