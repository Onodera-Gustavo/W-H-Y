"""Command line: `py -m why run`, `py -m why backfill` and `py -m why compare`."""

import argparse
import logging
import time
from collections.abc import Callable, Iterable, Sequence
from datetime import date, datetime

from why import backfill, config, export, ingest, quality, raw, sentiment
from why.files import write_json
from why.timeutil import utc_now
from why.warehouse import Warehouse

log = logging.getLogger("why")


def _score_pending(
    wh: Warehouse, models: Sequence[sentiment.SentimentModel], now: datetime
) -> dict[str, int]:
    scored = {}
    for model in models:
        pending = wh.pending_sentiment(model.name)
        results = model.score([title for _, title in pending])
        ids = [headline_id for headline_id, _ in pending]
        scored[model.name] = wh.add_sentiment(
            model.name, list(zip(ids, results, strict=True)), scored_at=now
        )
    return scored


def update_warehouse(
    paths: config.Paths,
    batches: Iterable[list[dict]],
    models: Sequence[sentiment.SentimentModel],
    *,
    now: datetime,
    run: dict,
) -> dict:
    """The part shared by run and backfill: load raw batches on top of the Parquet history,
    score what is missing, export Parquet, the site JSON and status.json.

    `run` describes the run for status.json; it is completed with the load counts and
    returned."""
    with Warehouse(paths.history_dir) as wh:
        run["history_before"] = wh.load_history()["headlines"]
        raw_records = inserted = seen_again = flagged = 0
        for batch in batches:
            batch_inserted, batch_seen = wh.upsert_headlines(batch)
            raw_records += len(batch)
            inserted += batch_inserted
            seen_again += batch_seen
            flagged += sum(quality.is_low_quality(record.get("title")) for record in batch)
        run.update(raw_records=raw_records, inserted=inserted, seen_again=seen_again)
        # dropped at ingest plus stored titles hidden at load (raw files predating a rule)
        run["filtered_low_quality"] = run.get("filtered_low_quality", 0) + flagged
        run["scored"] = _score_pending(wh, models, now)
        wh.export_history()
        run["history_after"] = wh.count("headlines")
        export.write_site_exports(wh, paths, generated_at=now, run=run)
    return run


def run_pipeline(
    paths: config.Paths,
    *,
    run_date: date | None = None,
    model_names: Sequence[str] = config.DEFAULT_MODELS,
    now: datetime | None = None,
) -> dict:
    """Collect (or replay) a day, land it raw, load the warehouse, score, export.

    Today is fetched from the feed. A past date is replayed from its raw partition without
    touching the network, which rebuilds the history or backfills a new model."""
    now = now or utc_now()
    today = now.date()
    run_date = run_date or today
    if run_date > today:
        raise ValueError(f"run date {run_date} is in the future")
    models = sentiment.get_models(model_names)  # fail on a bad name before any request

    run = {
        "run_date": run_date.isoformat(),
        "mode": "fetch" if run_date == today else "replay",
        "failed_topics": [],
        "filtered_low_quality": 0,
        "requests": 0,
        "backfill": None,
    }
    if run_date == today:
        collection = ingest.collect(config.TOPICS, run_date=run_date, now=now)
        run.update(
            failed_topics=collection.failed,
            filtered_low_quality=collection.low_quality,
            requests=collection.requests,
        )
        if len(collection.failed) == len(config.TOPICS):
            raise RuntimeError("every topic failed to download, nothing to load")
        raw.write_partition(paths.raw_dir, run_date, collection.records)
    batch = raw.read_partition(paths.raw_dir, run_date)
    if run_date != today and not batch:
        raise FileNotFoundError(f"no raw partition for {run_date} under {paths.raw_dir}")
    return update_warehouse(paths, [batch], models, now=now, run=run)


def backfill_pipeline(
    paths: config.Paths,
    *,
    days: int,
    model_names: Sequence[str] = config.DEFAULT_MODELS,
    sleep: float = config.BACKFILL_SLEEP,
    now: datetime | None = None,
    fetch: ingest.Fetcher | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], datetime] = utc_now,
) -> dict:
    """Fetch the past run dates that have no raw partition (today-days to today-1), then load
    every raw partition, score what is missing and export, exactly like a run."""
    now = now or utc_now()
    if sleep < 0:
        raise ValueError("sleep must be zero or more seconds")
    dates = backfill.run_dates(now.date(), days)
    models = sentiment.get_models(model_names)  # fail on a bad name before any request

    result = backfill.collect_days(
        paths.raw_dir, dates, fetch=fetch, pacer=ingest.Pacer(sleep, sleeper), clock=clock
    )
    run = {
        "run_date": dates[-1].isoformat(),
        "mode": "backfill",
        "failed_topics": result.failed_topics,
        "filtered_low_quality": result.low_quality,
        "requests": result.requests,
        "backfill": {
            "days": days,
            "first_run_date": dates[0].isoformat(),
            "last_run_date": dates[-1].isoformat(),
            "fetched": [d.isoformat() for d in result.fetched],
            "skipped": [d.isoformat() for d in result.skipped],
            "empty": [d.isoformat() for d in result.empty],
            "records": result.records,
        },
    }
    batches = (raw.read_partition(paths.raw_dir, d) for d in raw.partition_dates(paths.raw_dir))
    return update_warehouse(paths, batches, models, now=now, run=run)


def compare(
    paths: config.Paths,
    model_a: str = "vader",
    model_b: str = "finbert",
    now: datetime | None = None,
) -> dict:
    with Warehouse(paths.history_dir) as wh:
        wh.load_history()
        report = export.build_agreement(wh, model_a, model_b, generated_at=now)
    write_json(paths.agreement_json, report)
    return report


def _model_list(value: str) -> list[str]:
    names = [name.strip().lower() for name in value.split(",") if name.strip()]
    unknown = sorted(set(names) - set(sentiment.MODELS))
    if not names or unknown:
        raise argparse.ArgumentTypeError(
            f"unknown model(s) {', '.join(unknown) or value!r}; "
            f"choose from {', '.join(sentiment.MODELS)}"
        )
    return names


def _days(value: str) -> int:
    try:
        days = int(value)
    except ValueError:
        days = 0
    if not 1 <= days <= config.BACKFILL_MAX_DAYS:
        raise argparse.ArgumentTypeError(
            f"expected a whole number from 1 to {config.BACKFILL_MAX_DAYS}, got {value!r}"
        )
    return days


def _seconds(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError:
        seconds = -1.0
    if not seconds >= 0:
        raise argparse.ArgumentTypeError(f"expected zero or more seconds, got {value!r}")
    return seconds


def _add_models_option(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--models",
        type=_model_list,
        default=list(config.DEFAULT_MODELS),
        metavar="NAMES",
        help="comma separated sentiment models: vader, finbert (default: vader)",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="why", description="WHY (What Happened Yesterday): headline sentiment pipeline."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run_cmd = sub.add_parser("run", help="collect, load, score and export one day")
    run_cmd.add_argument(
        "--date",
        type=date.fromisoformat,
        metavar="YYYY-MM-DD",
        help="run date in UTC (default: today). A past date is replayed from its raw partition.",
    )
    _add_models_option(run_cmd)
    backfill_cmd = sub.add_parser(
        "backfill",
        help="fetch past days from Google News date search, then load, score and export",
        description=(
            "Fetch run dates today-N to today-1 (headlines published the day before each), "
            "skipping dates that already have a raw partition, then load every partition, "
            "score what is missing and export. HTTP 403 or 429 aborts with exit code 1."
        ),
    )
    backfill_cmd.add_argument(
        "--days",
        type=_days,
        required=True,
        metavar="N",
        help=f"how many past run dates to cover, 1 to {config.BACKFILL_MAX_DAYS}",
    )
    _add_models_option(backfill_cmd)
    backfill_cmd.add_argument(
        "--sleep",
        type=_seconds,
        default=config.BACKFILL_SLEEP,
        metavar="SECONDS",
        help=f"pause between two requests (default: {config.BACKFILL_SLEEP:g})",
    )
    sub.add_parser("compare", help="VADER x FinBERT agreement over the stored history")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S"
    )
    paths = config.Paths.from_env()
    try:
        if args.command in ("run", "backfill"):
            if args.command == "run":
                s = run_pipeline(paths, run_date=args.date, model_names=args.models)
            else:
                s = backfill_pipeline(
                    paths, days=args.days, model_names=args.models, sleep=args.sleep
                )
            log.info(
                "%s %s (%s): %d requests, %d raw records, %d new, %d seen again, "
                "%d low quality filtered, history %d to %d rows, scored %s",
                args.command, s["run_date"], s["mode"], s["requests"], s["raw_records"],
                s["inserted"], s["seen_again"], s["filtered_low_quality"],
                s["history_before"], s["history_after"], s["scored"],
            )  # fmt: skip
            if s["failed_topics"]:
                log.warning("topics that failed: %s", ", ".join(s["failed_topics"]))
            log.info("wrote %s", paths.status_json)
        else:
            r = compare(paths)
            if r["n"]:
                log.info(
                    "%s x %s on %d headlines: %.1f%% agreement, kappa %.3f",
                    *r["models"], r["n"], r["percent_agreement"], r["cohens_kappa"],
                )  # fmt: skip
            else:
                log.info("no headline scored by both models yet (run --models vader,finbert)")
            log.info("wrote %s", paths.agreement_json)
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        log.error("%s", exc)
        return 1
    return 0
