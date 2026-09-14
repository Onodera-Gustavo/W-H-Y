"""DuckDB warehouse for headlines and sentiment scores.

DuckDB runs in memory during a run. The durable copy is Parquet under data/history, one file
per table per month, loaded at the start and exported at the end. Monthly files keep diffs on
the `data` branch small: a daily run normally rewrites only the current month."""

import os
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from pathlib import Path

import duckdb

from why.dedup import dedup_key
from why.sentiment import SentimentResult
from why.timeutil import parse_iso, to_naive_utc

SCHEMA = """
CREATE TABLE IF NOT EXISTS headlines (
    headline_id    VARCHAR   NOT NULL,  -- dedup key: normalized link, or title + source
    topic          VARCHAR   NOT NULL,
    title          VARCHAR   NOT NULL,
    source         VARCHAR,
    link           VARCHAR,
    published_at   TIMESTAMP,           -- UTC, null when the feed had no usable date
    first_seen_at  TIMESTAMP NOT NULL,  -- UTC
    last_seen_at   TIMESTAMP NOT NULL,  -- UTC
    first_run_date DATE      NOT NULL,
    last_run_date  DATE      NOT NULL,
    PRIMARY KEY (headline_id, topic)
);

CREATE TABLE IF NOT EXISTS sentiment (
    headline_id VARCHAR   NOT NULL,
    model       VARCHAR   NOT NULL,
    label       VARCHAR   NOT NULL,     -- positive, neutral, negative
    score       DOUBLE    NOT NULL,     -- -1 to +1
    scored_at   TIMESTAMP NOT NULL,     -- UTC
    PRIMARY KEY (headline_id, model)
);
"""

# table: (month expression for data/history/<table>/YYYY-MM.parquet, sort order inside the file)
PARTITIONS = {
    "headlines": ("strftime(first_run_date, '%Y-%m')", "first_run_date, topic, headline_id"),
    "sentiment": ("strftime(scored_at, '%Y-%m')", "scored_at, headline_id, model"),
}


class Warehouse:
    def __init__(self, history_dir: Path, database: str = ":memory:") -> None:
        self.history_dir = Path(history_dir)
        self.con = duckdb.connect(database)
        self.con.execute(SCHEMA)

    def __enter__(self) -> "Warehouse":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.con.close()

    def count(self, table: str = "headlines") -> int:
        return self.con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    # history

    def load_history(self) -> dict[str, int]:
        """Replace table contents with the Parquet history, if any. Returns rows per table."""
        counts = {}
        for table in PARTITIONS:
            files = sorted((self.history_dir / table).glob("*.parquet"))
            self.con.execute(f"DELETE FROM {table}")
            if files:
                self.con.execute(
                    f"INSERT INTO {table} BY NAME SELECT * FROM read_parquet(?)",
                    [[str(path) for path in files]],
                )
            counts[table] = self.count(table)
        return counts

    def export_history(self) -> list[Path]:
        """Write one Parquet file per table per month, atomically. Rows are sorted, so a month
        whose data did not change comes out byte for byte the same and git sees no diff."""
        written: list[Path] = []
        for table, (month_expr, order_by) in PARTITIONS.items():
            folder = self.history_dir / table
            folder.mkdir(parents=True, exist_ok=True)
            months = self.con.execute(
                f"SELECT DISTINCT {month_expr} FROM {table} ORDER BY 1"
            ).fetchall()
            for (month,) in months:
                final = folder / f"{month}.parquet"
                tmp = folder / f"{month}.parquet.tmp"
                target = str(tmp).replace("'", "''")
                self.con.execute(
                    f"COPY (SELECT * FROM {table} WHERE {month_expr} = '{month}' "
                    f"ORDER BY {order_by}) TO '{target}' (FORMAT parquet, COMPRESSION zstd)"
                )
                os.replace(tmp, final)
                written.append(final)
            for stale in set(folder.glob("*.parquet")) - set(written):
                stale.unlink()
        return written

    # loading

    def upsert_headlines(self, records: Iterable[dict]) -> tuple[int, int]:
        """Load raw records. Returns (inserted, seen_again).

        A story already stored for the topic is not duplicated: only its first/last seen
        columns move. Inside one batch the earliest sighting wins."""
        rows = [
            (
                i,
                dedup_key(r.get("link"), r.get("title"), r.get("source")),
                r["topic"],
                r["title"],
                r.get("source") or None,
                r.get("link") or None,
                to_naive_utc(parse_iso(r.get("published_at"))),
                to_naive_utc(parse_iso(r["collected_at"])),
                date.fromisoformat(r["run_date"]),
            )
            for i, r in enumerate(records)
        ]
        if not rows:
            return 0, 0

        self.con.execute(
            """
            CREATE OR REPLACE TEMP TABLE staging (
                ord INTEGER, headline_id VARCHAR, topic VARCHAR, title VARCHAR, source VARCHAR,
                link VARCHAR, published_at TIMESTAMP, collected_at TIMESTAMP, run_date DATE
            )
            """
        )
        self.con.executemany("INSERT INTO staging VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        self.con.execute(
            """
            CREATE OR REPLACE TEMP TABLE batch AS
            SELECT headline_id, topic, title, source, link, published_at,
                   min(collected_at) OVER w AS first_seen_at,
                   max(collected_at) OVER w AS last_seen_at,
                   min(run_date)     OVER w AS first_run_date,
                   max(run_date)     OVER w AS last_run_date
            FROM staging
            WINDOW w AS (PARTITION BY headline_id, topic)
            QUALIFY row_number() OVER (
                PARTITION BY headline_id, topic ORDER BY collected_at, ord
            ) = 1
            """
        )
        seen_again = self.con.execute(
            """
            UPDATE headlines AS h SET
                first_seen_at  = least(h.first_seen_at, b.first_seen_at),
                last_seen_at   = greatest(h.last_seen_at, b.last_seen_at),
                first_run_date = least(h.first_run_date, b.first_run_date),
                last_run_date  = greatest(h.last_run_date, b.last_run_date)
            FROM batch AS b
            WHERE h.headline_id = b.headline_id AND h.topic = b.topic
            """
        ).fetchone()[0]
        inserted = self.con.execute(
            """
            INSERT INTO headlines BY NAME
            SELECT * FROM batch AS b
            WHERE NOT EXISTS (
                SELECT 1 FROM headlines AS h
                WHERE h.headline_id = b.headline_id AND h.topic = b.topic
            )
            """
        ).fetchone()[0]
        return inserted, seen_again

    def pending_sentiment(self, model: str) -> list[tuple[str, str]]:
        """(headline_id, title) of every stored headline the model has not scored yet. A story
        filed under two topics is scored once."""
        return self.con.execute(
            """
            SELECT headline_id, min(title)
            FROM headlines AS h
            WHERE NOT EXISTS (
                SELECT 1 FROM sentiment AS s WHERE s.headline_id = h.headline_id AND s.model = ?
            )
            GROUP BY headline_id
            ORDER BY headline_id
            """,
            [model],
        ).fetchall()

    def add_sentiment(
        self, model: str, scored: Sequence[tuple[str, SentimentResult]], scored_at: datetime
    ) -> int:
        rows = [
            (headline_id, model, result.label, float(result.score), to_naive_utc(scored_at))
            for headline_id, result in scored
        ]
        if rows:
            self.con.executemany("INSERT INTO sentiment VALUES (?, ?, ?, ?, ?)", rows)
        return len(rows)

    # queries used by the exports

    def latest_run_date(self) -> date | None:
        return self.con.execute("SELECT max(last_run_date) FROM headlines").fetchone()[0]

    def edition(self, run_date: date, limit: int) -> list[dict]:
        """Headlines seen on run_date, newest first, at most `limit` per topic."""
        cursor = self.con.execute(
            """
            SELECT topic, headline_id, title, source, link, published_at
            FROM headlines
            WHERE ? BETWEEN first_run_date AND last_run_date
            QUALIFY row_number() OVER (
                PARTITION BY topic ORDER BY published_at DESC NULLS LAST, headline_id
            ) <= ?
            ORDER BY topic, published_at DESC NULLS LAST, headline_id
            """,
            [run_date, limit],
        )
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]

    def scores(self, headline_ids: Sequence[str]) -> dict[str, dict[str, SentimentResult]]:
        if not headline_ids:
            return {}
        rows = self.con.execute(
            """
            SELECT headline_id, model, label, score FROM sentiment
            WHERE list_contains(?, headline_id)
            ORDER BY headline_id, model
            """,
            [list(headline_ids)],
        ).fetchall()
        out: dict[str, dict[str, SentimentResult]] = {}
        for headline_id, model, label, score in rows:
            out.setdefault(headline_id, {})[model] = SentimentResult(label, score)
        return out

    def daily_counts(self, start: date, end: date) -> list[tuple[str, date, int]]:
        """Headlines per topic per day they were first seen."""
        return self.con.execute(
            """
            SELECT topic, first_run_date, count(*) FROM headlines
            WHERE first_run_date BETWEEN ? AND ?
            GROUP BY ALL ORDER BY ALL
            """,
            [start, end],
        ).fetchall()

    def daily_sentiment(self, start: date, end: date) -> list[dict]:
        """Mean score and label counts per topic, day first seen and model."""
        cursor = self.con.execute(
            """
            SELECT h.topic, h.first_run_date AS day, s.model,
                   count(*)                                    AS n,
                   avg(s.score)                                AS avg,
                   count(*) FILTER (WHERE s.label = 'positive') AS positive,
                   count(*) FILTER (WHERE s.label = 'neutral')  AS neutral,
                   count(*) FILTER (WHERE s.label = 'negative') AS negative
            FROM headlines AS h
            JOIN sentiment AS s USING (headline_id)
            WHERE h.first_run_date BETWEEN ? AND ?
            GROUP BY ALL ORDER BY ALL
            """,
            [start, end],
        )
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]

    def label_pairs(self, model_a: str, model_b: str) -> list[tuple[str, str, float, float]]:
        """(label_a, label_b, score_a, score_b) for every headline both models scored."""
        return self.con.execute(
            """
            SELECT a.label, b.label, a.score, b.score
            FROM sentiment AS a
            JOIN sentiment AS b ON a.headline_id = b.headline_id
            WHERE a.model = ? AND b.model = ?
            ORDER BY a.headline_id
            """,
            [model_a, model_b],
        ).fetchall()
