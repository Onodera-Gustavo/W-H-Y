from datetime import UTC, datetime
from email.utils import format_datetime
from xml.sax.saxutils import escape

import requests

from why.config import slug
from why.sentiment import SentimentResult

NOW = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)


def make_record(
    title: str,
    *,
    topic: str = "Markets",
    link: str | None = None,
    source: str = "Reuters",
    published_at: str | None = "2026-09-14T07:00:00Z",
    collected_at: str = "2026-09-14T09:00:00Z",
    run_date: str = "2026-09-14",
) -> dict:
    return {
        "topic": topic,
        "title": title,
        "source": source,
        "link": link if link is not None else f"https://example.com/news/{slug(title)}",
        "published_at": published_at,
        "collected_at": collected_at,
        "run_date": run_date,
    }


def rss(items: list[dict]) -> bytes:
    """A small feed shaped like a Google News search result. Each item has a title, a
    published datetime (aware, or None) and optionally a source and a link."""
    entries = []
    for i, item in enumerate(items):
        source = item.get("source", "Reuters")
        link = item.get("link") or f"https://news.google.com/rss/articles/TEST{i:04d}?oc=5"
        published = item.get("published")
        pub_date = (
            f"<pubDate>{format_datetime(published, usegmt=True)}</pubDate>" if published else ""
        )
        entries.append(
            f"<item><title>{escape(item['title'])} - {escape(source)}</title>"
            f"<link>{escape(link)}</link>{pub_date}"
            f'<source url="https://example.com">{escape(source)}</source></item>'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        f"<title>test feed</title>{''.join(entries)}</channel></rss>"
    ).encode()


def http_error(status: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f"{status} error", response=response)


class FixedModel:
    """Stand-in sentiment model: the same answer for every headline."""

    def __init__(self, name: str = "finbert", label: str = "neutral", score: float = 0.0):
        self.name = name
        self._result = SentimentResult(label, score)

    def score(self, texts):
        return [self._result for _ in texts]
