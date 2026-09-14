"""
WHY: local web server.

Serves the frontend and the pipeline's output. It never scrapes; run the pipeline first.

Routes:
    GET /                  frontend
    GET /api/news          latest edition (site/data/latest.json, or built from the Parquet history)
    GET /api/news/<label>  one topic of the latest edition (e.g. /api/news/Tesla)
    GET /api/trends        14-day sentiment per topic
    GET /api/agreement     VADER x FinBERT agreement report

Usage:
    py -m why run
    py backend/app.py      (WHY_DEBUG=1 turns on Flask debug mode, PORT changes the port)
"""

import os
import sys
from collections.abc import Callable
from pathlib import Path

from flask import Flask, jsonify, send_from_directory

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # lets `py backend/app.py` import the why package

from why import config, export  # noqa: E402
from why.files import read_json  # noqa: E402
from why.warehouse import Warehouse  # noqa: E402

FRONTEND_DIR = ROOT / "frontend"


def create_app(paths: config.Paths | None = None) -> Flask:
    paths = paths or config.Paths.from_env()
    app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")

    def load(export_file: Path, build: Callable[[Warehouse], dict]) -> dict | None:
        """Exported JSON when present, otherwise computed from the local Parquet history."""
        if export_file.exists():
            return read_json(export_file)
        if any((paths.history_dir / "headlines").glob("*.parquet")):
            with Warehouse(paths.history_dir) as wh:
                wh.load_history()
                return build(wh)
        return None

    def no_data():
        return jsonify(error="no data yet", hint="run: py -m why run"), 503

    @app.get("/api/news")
    def news():
        data = load(paths.latest_json, export.build_latest)
        return jsonify(data) if data else no_data()

    @app.get("/api/news/<string:label>")
    def topic_news(label: str):
        data = load(paths.latest_json, export.build_latest)
        if not data:
            return no_data()
        for topic in data["topics"]:
            if topic["label"].lower() == label.lower():
                meta = {k: data.get(k) for k in ("generated_at", "run_date", "date_label")}
                return jsonify({**meta, "primary_model": data.get("primary_model"), **topic})
        return jsonify(error=f"topic {label!r} not found"), 404

    @app.get("/api/trends")
    def trends():
        data = load(paths.trends_json, export.build_trends)
        return jsonify(data) if data else no_data()

    @app.get("/api/agreement")
    def agreement():
        data = load(paths.agreement_json, export.build_agreement)
        return jsonify(data) if data else no_data()

    @app.get("/")
    def index():
        return send_from_directory(FRONTEND_DIR, "index.html")

    return app


if __name__ == "__main__":
    debug = os.environ.get("WHY_DEBUG", "").lower() in {"1", "true", "yes"}
    port = int(os.environ.get("PORT", "5000"))
    print(f"WHY server on http://localhost:{port}")
    create_app().run(host="127.0.0.1", port=port, debug=debug)
