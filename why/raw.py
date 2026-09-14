"""Raw landing zone: the feed as collected, one JSONL file per topic per day.

    data/raw/date=YYYY-MM-DD/<topic>.jsonl

The warehouse is always loaded from these files, so any day can be replayed without network."""

import json
from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from pathlib import Path

from why.config import slug
from why.dedup import dedup_key
from why.files import atomic_write_text


def partition_dir(raw_dir: Path, run_date: date) -> Path:
    return Path(raw_dir) / f"date={run_date.isoformat()}"


def record_key(record: dict) -> str:
    return dedup_key(record.get("link"), record.get("title"), record.get("source"))


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def write_partition(raw_dir: Path, run_date: date, records: Iterable[dict]) -> dict[str, int]:
    """Merge records into the day's partition. Returns lines per topic file.

    Idempotent: a record whose key is already in the file keeps its first version and the
    output is sorted, so re-running a day with the same feed rewrites identical bytes. A later
    run on the same day only adds the stories that are new."""
    by_topic: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        by_topic[record["topic"]].append(record)

    folder = partition_dir(raw_dir, run_date)
    counts = {}
    for topic, new_records in by_topic.items():
        path = folder / f"{slug(topic)}.jsonl"
        merged: dict[str, dict] = {}
        for record in _read_jsonl(path) + new_records:
            merged.setdefault(record_key(record), record)
        rows = sorted(
            merged.items(),
            key=lambda item: (item[1].get("published_at") or "", item[0]),
            reverse=True,
        )
        lines = (json.dumps(rec, ensure_ascii=False, sort_keys=True) for _, rec in rows)
        atomic_write_text(path, "".join(line + "\n" for line in lines))
        counts[topic] = len(rows)
    return counts


def read_partition(raw_dir: Path, run_date: date) -> list[dict]:
    records: list[dict] = []
    for path in sorted(partition_dir(raw_dir, run_date).glob("*.jsonl")):
        records.extend(_read_jsonl(path))
    return records
