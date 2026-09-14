"""Collect headlines from the Google News RSS search feed."""

import logging
from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode

import feedparser
import requests

from why import config
from why.timeutil import as_utc, to_iso, utc_now

log = logging.getLogger(__name__)

Fetcher = Callable[[str, requests.Session | None], bytes]


def feed_url(query: str, days_back: int = config.DAYS_BACK) -> str:
    # "when:1d" asks Google News for the window up front; is_recent() still filters locally
    params = {"q": f"{query} when:{days_back}d", **config.FEED_PARAMS}
    return f"{config.FEED_URL}?{urlencode(params)}"


def parse_published(value: str | None) -> datetime | None:
    """RFC 822 date from the feed as aware UTC, or None when missing or invalid."""
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return as_utc(dt)  # no offset in the string: assume UTC


def is_recent(
    published: str | None, days_back: int = config.DAYS_BACK, now: datetime | None = None
) -> bool:
    """True when the item is inside the window.

    Items with a missing or unparseable date are kept (the feed occasionally omits it);
    they land with published_at = null."""
    dt = parse_published(published)
    if dt is None:
        return True
    return dt >= as_utc(now or utc_now()) - timedelta(days=days_back)


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


def parse_feed(
    content: bytes,
    topic: str,
    *,
    collected_at: datetime,
    run_date: date,
    max_items: int = config.MAX_PER_TOPIC,
    days_back: int = config.DAYS_BACK,
) -> list[dict]:
    """Feed bytes to raw records, newest first, at most max_items."""
    feed = feedparser.parse(content)
    if feed.bozo and not feed.entries:
        log.warning("%s: feed could not be parsed (%s)", topic, feed.get("bozo_exception"))
    records = []
    for entry in feed.entries:
        published = entry.get("published")
        if not is_recent(published, days_back, now=collected_at):
            continue
        source_title = (entry.get("source") or {}).get("title")
        title, source = split_title(entry.get("title"), source_title)
        if not title:
            continue
        records.append(
            {
                "topic": topic,
                "title": title,
                "source": source,
                "link": entry.get("link") or "",
                "published_at": to_iso(parse_published(published)),
                "collected_at": to_iso(collected_at),
                "run_date": run_date.isoformat(),
            }
        )
    # ISO strings sort chronologically; undated items go last
    records.sort(key=lambda r: r["published_at"] or "", reverse=True)
    return records[:max_items]


def fetch_feed(query: str, session: requests.Session | None = None) -> bytes:
    http = session or requests
    response = http.get(
        feed_url(query),
        headers={"User-Agent": config.USER_AGENT},
        timeout=config.REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.content


def collect(
    topics: Iterable[dict],
    *,
    run_date: date,
    now: datetime | None = None,
    fetch: Fetcher | None = None,
) -> tuple[list[dict], list[str]]:
    """One request per topic. A topic that fails is logged and skipped, so the rest still
    land. Returns (records, labels of failed topics)."""
    now = now or utc_now()
    fetch = fetch or fetch_feed
    records: list[dict] = []
    failed: list[str] = []
    with requests.Session() as session:
        for topic in topics:
            try:
                content = fetch(topic["query"], session)
            except requests.RequestException as exc:
                log.warning("%s: download failed (%s)", topic["label"], exc)
                failed.append(topic["label"])
                continue
            items = parse_feed(content, topic["label"], collected_at=now, run_date=run_date)
            log.info("%-8s %d headlines", topic["label"], len(items))
            records.extend(items)
    return records, failed
