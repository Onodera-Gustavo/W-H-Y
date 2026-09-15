"""Pipeline settings: topics, limits and where files live."""

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from why import __version__

TOPICS: list[dict[str, str]] = [
    {"label": "Markets", "query": "stock market"},
    {"label": "Tesla", "query": "TSLA Tesla"},
    {"label": "AI", "query": "artificial intelligence"},
    {"label": "Economy", "query": "economy inflation"},
    {"label": "Tech", "query": "technology startups"},
    {"label": "Energy", "query": "oil energy"},
]

MAX_PER_TOPIC = 8  # headlines per topic in the daily edition
DAYS_BACK = 1  # recency window, relative to collection time
TREND_DAYS = 30  # window of trends.json (the frontend offers 7, 14 and 30 days)

# status.json and model_agreement.json list sizes
STATUS_DAILY_RUNS = 30  # most recent run dates listed under "daily"
STATUS_TOP_SOURCES = 10
AGREEMENT_SCORE_PAIRS = 2000
AGREEMENT_DISAGREEMENTS = 60

# cron of .github/workflows/pipeline.yml, echoed in status.json (a test keeps them in sync)
SCHEDULE = "0 9 * * *"

FEED_URL = "https://news.google.com/rss/search"
FEED_PARAMS = {"hl": "en-US", "gl": "US", "ceid": "US:en"}
REQUEST_TIMEOUT = 20  # seconds
USER_AGENT = (
    f"W-H-Y/{__version__} (+https://github.com/Onodera-Gustavo/W-H-Y; "
    "daily headline digest, one request per topic)"
)
# the feed asking us to stop: the run stops requesting at once instead of trying the next topic
BLOCKING_STATUS = frozenset({403, 429})

BACKFILL_MAX_DAYS = 60
BACKFILL_SLEEP = 3.0  # seconds between two backfill requests

DEFAULT_MODELS = ("vader",)
# the site shows the first of these models that scored a headline
PRIMARY_MODEL_PREFERENCE = ("finbert", "vader")

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Paths:
    data_dir: Path  # raw/ and history/ (the `data` branch in CI)
    site_data_dir: Path  # JSON exports read by the frontend

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def history_dir(self) -> Path:
        return self.data_dir / "history"

    @property
    def latest_json(self) -> Path:
        return self.site_data_dir / "latest.json"

    @property
    def trends_json(self) -> Path:
        return self.site_data_dir / "trends.json"

    @property
    def agreement_json(self) -> Path:
        return self.site_data_dir / "model_agreement.json"

    @property
    def status_json(self) -> Path:
        return self.site_data_dir / "status.json"

    @classmethod
    def from_env(cls) -> Self:
        """Repository defaults, overridable with WHY_DATA_DIR and WHY_SITE_DATA_DIR."""
        return cls(
            data_dir=Path(os.environ.get("WHY_DATA_DIR") or ROOT / "data"),
            site_data_dir=Path(os.environ.get("WHY_SITE_DATA_DIR") or ROOT / "site" / "data"),
        )

    @classmethod
    def under(cls, root: Path) -> Self:
        root = Path(root)
        return cls(data_dir=root / "data", site_data_dir=root / "site" / "data")


def slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") or "topic"
