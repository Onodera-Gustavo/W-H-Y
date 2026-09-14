"""Command line: `py -m why run` and `py -m why compare`."""

import argparse
import logging
from collections.abc import Sequence
from datetime import date, datetime

from why import config, export, ingest, raw, sentiment
from why.files import write_json
from why.timeutil import utc_now
from why.warehouse import Warehouse

log = logging.getLogger("why")


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

    failed: list[str] = []
    if run_date == today:
        records, failed = ingest.collect(config.TOPICS, run_date=run_date, now=now)
        if len(failed) == len(config.TOPICS):
            raise RuntimeError("every topic failed to download, nothing to load")
        raw.write_partition(paths.raw_dir, run_date, records)
    batch = raw.read_partition(paths.raw_dir, run_date)
    if run_date != today and not batch:
        raise FileNotFoundError(f"no raw partition for {run_date} under {paths.raw_dir}")

    with Warehouse(paths.history_dir) as wh:
        before = wh.load_history()["headlines"]
        inserted, seen_again = wh.upsert_headlines(batch)
        scored = {}
        for model in models:
            pending = wh.pending_sentiment(model.name)
            results = model.score([title for _, title in pending])
            ids = [headline_id for headline_id, _ in pending]
            scored[model.name] = wh.add_sentiment(
                model.name, list(zip(ids, results, strict=True)), scored_at=now
            )
        wh.export_history()
        export.write_site_exports(wh, paths, generated_at=now)
        after = wh.count("headlines")

    return {
        "run_date": run_date.isoformat(),
        "mode": "fetch" if run_date == today else "replay",
        "raw_records": len(batch),
        "inserted": inserted,
        "seen_again": seen_again,
        "history_before": before,
        "history_after": after,
        "scored": scored,
        "failed_topics": failed,
    }


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
    run_cmd.add_argument(
        "--models",
        type=_model_list,
        default=list(config.DEFAULT_MODELS),
        metavar="NAMES",
        help="comma separated sentiment models: vader, finbert (default: vader)",
    )
    sub.add_parser("compare", help="VADER x FinBERT agreement over the stored history")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S"
    )
    paths = config.Paths.from_env()
    try:
        if args.command == "run":
            s = run_pipeline(paths, run_date=args.date, model_names=args.models)
            log.info(
                "run %s (%s): %d raw records, %d new, %d seen again, history %d to %d rows, "
                "scored %s",
                s["run_date"], s["mode"], s["raw_records"], s["inserted"], s["seen_again"],
                s["history_before"], s["history_after"], s["scored"],
            )  # fmt: skip
            if s["failed_topics"]:
                log.warning("topics that failed: %s", ", ".join(s["failed_topics"]))
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
