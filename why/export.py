"""JSON exports read by the frontend, under site/data/:

    latest.json            the daily edition
    trends.json            daily sentiment and counts per topic, last TREND_DAYS days
    model_agreement.json   VADER x FinBERT agreement (written by `why compare`)
    status.json            last run, history size, per topic and per day counts

Every export reads the warehouse's good_headlines view, so low quality titles never appear."""

import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import date, datetime, timedelta

from why import __version__, config, metrics
from why.config import Paths
from why.files import write_json
from why.sentiment import LABELS, SentimentResult
from why.timeutil import to_iso, utc_now
from why.warehouse import Warehouse

# keys of status.json "run", in order
RUN_FIELDS = (
    "run_date",
    "mode",
    "raw_records",
    "inserted",
    "seen_again",
    "scored",
    "failed_topics",
    "filtered_low_quality",
    "requests",
    "backfill",
)


def primary_model(available: Iterable[str]) -> str | None:
    available = set(available)
    for name in config.PRIMARY_MODEL_PREFERENCE:
        if name in available:
            return name
    return min(available) if available else None


def _iso_date(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _article(row: dict, scores: dict[str, SentimentResult]) -> dict:
    best = primary_model(scores)
    return {
        "id": row["headline_id"],
        "title": row["title"],
        "source": row["source"] or "Unknown",
        "link": row["link"] or "",
        "published": to_iso(row["published_at"]),
        "sentiment": (
            {"model": best, "label": scores[best].label, "score": scores[best].score}
            if best
            else None
        ),
        "scores": {m: {"label": r.label, "score": r.score} for m, r in sorted(scores.items())},
    }


def build_latest(
    wh: Warehouse,
    *,
    run_date: date | None = None,
    topics: list[dict] = config.TOPICS,
    limit: int = config.MAX_PER_TOPIC,
    generated_at: datetime | None = None,
) -> dict:
    """The daily edition: headlines seen on the most recent run date, grouped by topic."""
    run_date = run_date or wh.latest_run_date()
    rows = wh.edition(run_date, limit) if run_date else []
    scores = wh.scores([row["headline_id"] for row in rows])

    by_topic: dict[str, list[dict]] = defaultdict(list)
    models: set[str] = set()
    for row in rows:
        row_scores = scores.get(row["headline_id"], {})
        models.update(row_scores)
        by_topic[row["topic"]].append(_article(row, row_scores))

    return {
        "generated_at": to_iso(generated_at or utc_now()),
        "run_date": _iso_date(run_date),
        "date_label": (
            f"Yesterday, {run_date - timedelta(days=1):%b %d}" if run_date else "No edition yet"
        ),
        "models": sorted(models),
        "primary_model": primary_model(models),
        "topics": [
            {"label": t["label"], "query": t["query"], "articles": by_topic.get(t["label"], [])}
            for t in topics
        ],
    }


def build_trends(
    wh: Warehouse,
    *,
    end_date: date | None = None,
    days: int = config.TREND_DAYS,
    topics: list[dict] = config.TOPICS,
    generated_at: datetime | None = None,
) -> dict:
    """Daily mean sentiment and headline counts per topic over the last `days` days.

    Days are the date a headline was first seen, so a story that stays in the feed for two
    mornings counts once. Days without headlines appear with count 0 and no sentiment."""
    end_date = end_date or wh.latest_run_date()
    payload = {
        "generated_at": to_iso(generated_at or utc_now()),
        "start_date": None,
        "end_date": None,
        "days": days,
        "models": [],
        "primary_model": None,
        "topics": [{"label": t["label"], "series": []} for t in topics],
    }
    if end_date is None:
        return payload

    start = end_date - timedelta(days=days - 1)
    calendar = [start + timedelta(days=i) for i in range(days)]
    counts = {(topic, day): n for topic, day, n in wh.daily_counts(start, end_date)}
    stats: dict[tuple[str, date], dict] = defaultdict(dict)
    models: set[str] = set()
    for row in wh.daily_sentiment(start, end_date):
        models.add(row["model"])
        stats[(row["topic"], row["day"])][row["model"]] = {
            "avg": round(row["avg"], 4),
            "n": row["n"],
            **{label: row[label] for label in LABELS},
        }

    payload.update(
        start_date=start.isoformat(),
        end_date=end_date.isoformat(),
        models=sorted(models),
        primary_model=primary_model(models),
        topics=[
            {
                "label": t["label"],
                "series": [
                    {
                        "date": day.isoformat(),
                        "count": counts.get((t["label"], day), 0),
                        "sentiment": stats.get((t["label"], day), {}),
                    }
                    for day in calendar
                ],
            }
            for t in topics
        ],
    )
    return payload


def _correlation(xs: list[float], ys: list[float]) -> float | None:
    try:
        return round(statistics.correlation(xs, ys), 4)
    except statistics.StatisticsError:  # fewer than two points, or a constant series
        return None


def _agreement_numbers(labels_a: list[str], labels_b: list[str]) -> tuple[float, float] | None:
    if not labels_a:
        return None
    return (
        round(metrics.percent_agreement(labels_a, labels_b), 2),
        round(metrics.cohens_kappa(labels_a, labels_b), 4),
    )


def build_agreement(
    wh: Warehouse,
    model_a: str = "vader",
    model_b: str = "finbert",
    *,
    topics: list[dict] = config.TOPICS,
    generated_at: datetime | None = None,
    max_score_pairs: int = config.AGREEMENT_SCORE_PAIRS,
    max_disagreements: int = config.AGREEMENT_DISAGREEMENTS,
) -> dict:
    """How often two models give the same label to the same headlines. Agreement, not
    accuracy: there are no human labels here.

    Overall numbers count each story once. by_topic counts a story under every topic it was
    filed in. score_pairs is ordered by story id, a hash, so a capped list is an unbiased
    sample. disagreements lists stories with different labels, most recent run date first,
    then the largest score gap."""
    rank = {t["label"]: i for i, t in enumerate(topics)}
    topic_labels: dict[str, tuple[list[str], list[str]]] = defaultdict(lambda: ([], []))
    stories: dict[str, dict] = {}  # headline_id -> row under its first topic in config order
    for row in wh.paired_scores(model_a, model_b):
        labels_a, labels_b = topic_labels[row["topic"]]
        labels_a.append(row["label_a"])
        labels_b.append(row["label_b"])
        current = stories.get(row["headline_id"])
        order = (rank.get(row["topic"], len(rank)), row["topic"])
        if current is None or order < (rank.get(current["topic"], len(rank)), current["topic"]):
            stories[row["headline_id"]] = row
    pairs = [stories[headline_id] for headline_id in sorted(stories)]
    labels_a = [p["label_a"] for p in pairs]
    labels_b = [p["label_b"] for p in pairs]

    by_topic = []
    extra_topics = sorted(set(topic_labels) - set(rank))
    for label in [t["label"] for t in topics] + extra_topics:
        a, b = topic_labels.get(label, ([], []))
        numbers = _agreement_numbers(a, b)
        by_topic.append(
            {
                "topic": label,
                "n": len(a),
                "percent_agreement": numbers[0] if numbers else None,
                "cohens_kappa": numbers[1] if numbers else None,
            }
        )

    differing = [p for p in pairs if p["label_a"] != p["label_b"]]
    differing.sort(
        key=lambda p: (
            -p["last_run_date"].toordinal(),
            -abs(p["score_b"] - p["score_a"]),
            p["headline_id"],
        )
    )

    report = {
        "generated_at": to_iso(generated_at or utc_now()),
        "models": [model_a, model_b],
        "labels": list(LABELS),
        "n": len(pairs),
        "percent_agreement": None,
        "cohens_kappa": None,
        "score_correlation": None,
        "confusion_matrix": None,
        "label_distribution": None,
        "by_topic": by_topic,
        "score_pairs": [
            {"a": p["score_a"], "b": p["score_b"], "same": p["label_a"] == p["label_b"]}
            for p in pairs[:max_score_pairs]
        ],
        "disagreements": [
            {
                "id": p["headline_id"],
                "topic": p["topic"],
                "title": p["title"],
                "source": p["source"] or "Unknown",
                "link": p["link"] or "",
                "run_date": p["last_run_date"].isoformat(),
                "a": {"label": p["label_a"], "score": p["score_a"]},
                "b": {"label": p["label_b"], "score": p["score_b"]},
                "gap": round(p["score_b"] - p["score_a"], 4),
            }
            for p in differing[:max_disagreements]
        ],
    }
    numbers = _agreement_numbers(labels_a, labels_b)
    if numbers is None:
        return report
    report.update(
        percent_agreement=numbers[0],
        cohens_kappa=numbers[1],
        score_correlation=_correlation(
            [p["score_a"] for p in pairs], [p["score_b"] for p in pairs]
        ),
        confusion_matrix={
            "rows": model_a,
            "columns": model_b,
            "matrix": metrics.confusion_matrix(labels_a, labels_b, LABELS),
        },
        label_distribution={
            model_a: {label: Counter(labels_a)[label] for label in LABELS},
            model_b: {label: Counter(labels_b)[label] for label in LABELS},
        },
    )
    return report


def _run_status(run: dict | None) -> dict | None:
    if run is None:
        return None
    defaults = {"failed_topics": [], "scored": {}, "filtered_low_quality": 0, "requests": 0}
    return {key: run.get(key, defaults.get(key)) for key in RUN_FIELDS}


def build_status(
    wh: Warehouse,
    *,
    run: dict | None = None,
    latest: dict | None = None,
    topics: list[dict] = config.TOPICS,
    generated_at: datetime | None = None,
) -> dict:
    """Pipeline health for the frontend: the run that wrote the file (null when the status
    is rebuilt from the history), the size of the history, and per topic, per day and per
    source counts. Low quality titles are excluded from every count except
    history.excluded_low_quality."""
    latest = latest or build_latest(wh, topics=topics, generated_at=generated_at)
    overview = wh.history_overview()
    scored = wh.sentiment_counts()
    totals = wh.topic_totals()
    edition = {t["label"]: len(t["articles"]) for t in latest["topics"]}
    return {
        "generated_at": to_iso(generated_at or utc_now()),
        "version": __version__,
        "schedule": config.SCHEDULE,
        "run": _run_status(run),
        "history": {
            "headlines": overview["headlines"],
            "excluded_low_quality": wh.low_quality_rows(),
            "sentiment": scored,
            "first_run_date": _iso_date(overview["first_run_date"]),
            "last_run_date": _iso_date(overview["last_run_date"]),
            "run_days": overview["run_days"],
            "parquet_files": wh.parquet_files(),
        },
        "models": {"primary": primary_model(scored), "available": sorted(scored)},
        "topics": [
            {
                "label": t["label"],
                "query": t["query"],
                "edition": edition.get(t["label"], 0),
                "total": totals.get(t["label"], 0),
            }
            for t in topics
        ],
        "daily": [
            {"run_date": day.isoformat(), "new_headlines": new, "seen_again": again}
            for day, new, again in wh.daily_activity(config.STATUS_DAILY_RUNS)
        ],
        "sources": [
            {"source": source, "n": n} for source, n in wh.top_sources(config.STATUS_TOP_SOURCES)
        ],
        "config": {"max_per_topic": config.MAX_PER_TOPIC, "trend_days": config.TREND_DAYS},
    }


def write_site_exports(
    wh: Warehouse,
    paths: Paths,
    *,
    generated_at: datetime | None = None,
    run: dict | None = None,
) -> None:
    """latest.json, trends.json and status.json. model_agreement.json is written by compare."""
    latest = build_latest(wh, generated_at=generated_at)
    write_json(paths.latest_json, latest)
    write_json(paths.trends_json, build_trends(wh, generated_at=generated_at))
    write_json(
        paths.status_json, build_status(wh, run=run, latest=latest, generated_at=generated_at)
    )
