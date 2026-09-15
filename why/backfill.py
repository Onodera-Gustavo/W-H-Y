"""Backfill: rebuild past editions from Google News date search.

The daily run only sees the last 24 hours, so a fresh deployment starts with an empty trend
chart. `python -m why backfill --days N` fills the gap once, with the daily run's semantics:
partition date=R is the run of morning R and its edition is labeled "Yesterday, R-1", so run
date R holds headlines published on UTC day R-1 (see ingest.day_query for the search window).

Politeness: one request per topic per run date, strictly sequential, a pause between requests
(3 seconds by default), the project User-Agent and no retries. HTTP 403 or 429 aborts the
whole backfill at once. Run dates that already have a raw partition are skipped, so a later
backfill resumes where an aborted one stopped and a live daily run is never overwritten."""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from why import config, ingest, raw
from why.timeutil import utc_now

log = logging.getLogger(__name__)

COLLECTION = "backfill"  # value of the "collection" field of every backfilled raw record


class BackfillAborted(RuntimeError):
    """The feed answered 403 or 429: stop requesting."""


@dataclass
class BackfillResult:
    run_dates: list[date]
    fetched: list[date] = field(default_factory=list)  # partitions written
    skipped: list[date] = field(default_factory=list)  # partitions that already existed
    empty: list[date] = field(default_factory=list)  # nothing to write, retried next time
    records: int = 0
    low_quality: int = 0
    requests: int = 0
    failed_topics: list[str] = field(default_factory=list)  # "Label (YYYY-MM-DD)"


def run_dates(today: date, days: int) -> list[date]:
    """The run dates a backfill covers: today-days to today-1, ascending."""
    if not 1 <= days <= config.BACKFILL_MAX_DAYS:
        raise ValueError(f"days must be between 1 and {config.BACKFILL_MAX_DAYS}, got {days}")
    return [today - timedelta(days=offset) for offset in range(days, 0, -1)]


def edition_day(run_date: date) -> date:
    """The UTC day whose headlines make the edition of run date R: R-1."""
    return run_date - timedelta(days=1)


def collect_days(
    raw_dir: Path,
    dates: Sequence[date],
    *,
    topics: list[dict] = config.TOPICS,
    fetch: ingest.Fetcher | None = None,
    pacer: ingest.Pacer | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> BackfillResult:
    """Fetch and land every run date that has no raw partition yet.

    Raises BackfillAborted on HTTP 403 or 429; partitions written before stay on disk and
    nothing is written for the run date that was interrupted."""
    pacer = pacer or ingest.Pacer(config.BACKFILL_SLEEP)
    result = BackfillResult(run_dates=list(dates))
    for run_date in dates:
        if raw.partition_exists(raw_dir, run_date):
            log.info("%s: raw partition already exists, skipped", run_date)
            result.skipped.append(run_date)
            continue
        day = edition_day(run_date)
        collection = ingest.collect(
            topics,
            run_date=run_date,
            fetch=fetch,
            query=lambda query, day=day: ingest.day_query(query, day),
            in_window=ingest.on_utc_day(day),
            extra={"collection": COLLECTION},
            pacer=pacer,
            clock=clock,
        )
        result.requests += collection.requests
        result.low_quality += collection.low_quality
        if collection.blocked:
            log.error(
                "backfill aborted: HTTP %d on run date %s after %d requests in total; "
                "%d run dates written before it are kept", collection.blocked, run_date,
                result.requests, len(result.fetched),
            )  # fmt: skip
            raise BackfillAborted(
                f"HTTP {collection.blocked} from the feed on run date {run_date}, "
                f"backfill aborted after {result.requests} requests"
            )
        result.failed_topics.extend(f"{label} ({run_date})" for label in collection.failed)
        if not collection.records:
            log.warning("%s: no headline published on %s, nothing written", run_date, day)
            result.empty.append(run_date)
            continue
        raw.write_partition(raw_dir, run_date, collection.records)
        result.fetched.append(run_date)
        result.records += len(collection.records)
        log.info("%s: %d headlines published on %s landed", run_date, len(collection.records), day)
    log.info(
        "backfill requests: %d in total (%d run dates fetched, %d skipped, %d empty)",
        result.requests, len(result.fetched), len(result.skipped), len(result.empty),
    )  # fmt: skip
    return result
