"""JSON exports read by the frontend: site/data/latest.json, trends.json, model_agreement.json."""

import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import date, datetime, timedelta

from why import config, metrics
from why.config import Paths
from why.files import write_json
from why.sentiment import LABELS, SentimentResult
from why.timeutil import to_iso, utc_now
from why.warehouse import Warehouse


def primary_model(available: Iterable[str]) -> str | None:
    available = set(available)
    for name in config.PRIMARY_MODEL_PREFERENCE:
        if name in available:
            return name
    return min(available) if available else None


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
        "run_date": run_date.isoformat() if run_date else None,
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


def build_agreement(
    wh: Warehouse,
    model_a: str = "vader",
    model_b: str = "finbert",
    *,
    generated_at: datetime | None = None,
) -> dict:
    """How often two models give the same label to the same headlines. Agreement, not
    accuracy: there are no human labels here."""
    pairs = wh.label_pairs(model_a, model_b)
    labels_a = [p[0] for p in pairs]
    labels_b = [p[1] for p in pairs]
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
    }
    if not pairs:
        return report
    report.update(
        percent_agreement=round(metrics.percent_agreement(labels_a, labels_b), 2),
        cohens_kappa=round(metrics.cohens_kappa(labels_a, labels_b), 4),
        score_correlation=_correlation([p[2] for p in pairs], [p[3] for p in pairs]),
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


def write_site_exports(
    wh: Warehouse, paths: Paths, *, generated_at: datetime | None = None
) -> None:
    write_json(paths.latest_json, build_latest(wh, generated_at=generated_at))
    write_json(paths.trends_json, build_trends(wh, generated_at=generated_at))
