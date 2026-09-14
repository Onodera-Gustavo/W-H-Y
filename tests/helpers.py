from datetime import UTC, datetime

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


class FixedModel:
    """Stand-in sentiment model: the same answer for every headline."""

    def __init__(self, name: str = "finbert", label: str = "neutral", score: float = 0.0):
        self.name = name
        self._result = SentimentResult(label, score)

    def score(self, texts):
        return [self._result for _ in texts]
