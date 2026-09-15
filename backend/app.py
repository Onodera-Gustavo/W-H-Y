"""
WHY: local web server.

Serves the frontend and the pipeline's output. It never scrapes; run the pipeline first.

Routes:
    GET /                  frontend/index.html
    GET /<path>            any file under frontend/ (pages, assets/js/*.js, assets/css/*.css)
    GET /data/<name>.json  the site exports, at the same relative URL as on GitHub Pages
    GET /api/news          latest edition (site/data/latest.json, or built from the Parquet history)
    GET /api/news/<label>  one topic of the latest edition (e.g. /api/news/Tesla)
    GET /api/trends        daily sentiment per topic, last 30 days
    GET /api/agreement     VADER x FinBERT agreement report
    GET /api/status        last run, history size, per topic and per day counts

Usage:
    py -m why run
    py backend/app.py      (WHY_DEBUG=1 turns on Flask debug mode, PORT changes the port)
"""

import mimetypes
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

# The Windows registry can map .js to text/plain, and browsers refuse to run ES modules served
# with a non JavaScript type. Pin the types the frontend uses.
for extension, mime in {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml",
    ".json": "application/json",
}.items():
    mimetypes.add_type(mime, extension)


def create_app(paths: config.Paths | None = None, frontend_dir: Path | None = None) -> Flask:
    paths = paths or config.Paths.from_env()
    frontend_dir = Path(frontend_dir or FRONTEND_DIR)
    app = Flask(__name__, static_folder=str(frontend_dir), static_url_path="")

    exports: dict[str, tuple[Path, Callable[[Warehouse], dict]]] = {
        "latest.json": (paths.latest_json, export.build_latest),
        "trends.json": (paths.trends_json, export.build_trends),
        "model_agreement.json": (paths.agreement_json, export.build_agreement),
        "status.json": (paths.status_json, export.build_status),
    }

    def load(name: str) -> dict | None:
        """Exported JSON when present, otherwise computed from the local Parquet history."""
        export_file, build = exports[name]
        if export_file.exists():
            return read_json(export_file)
        if any((paths.history_dir / "headlines").glob("*.parquet")):
            with Warehouse(paths.history_dir) as wh:
                wh.load_history()
                return build(wh)
        return None

    def no_data():
        return jsonify(error="no data yet", hint="run: py -m why run"), 503

    def respond(name: str):
        data = load(name)
        return jsonify(data) if data else no_data()

    @app.get("/api/news")
    def news():
        return respond("latest.json")

    @app.get("/api/news/<string:label>")
    def topic_news(label: str):
        data = load("latest.json")
        if not data:
            return no_data()
        for topic in data["topics"]:
            if topic["label"].lower() == label.lower():
                meta = {k: data.get(k) for k in ("generated_at", "run_date", "date_label")}
                return jsonify({**meta, "primary_model": data.get("primary_model"), **topic})
        return jsonify(error=f"topic {label!r} not found"), 404

    @app.get("/api/trends")
    def trends():
        return respond("trends.json")

    @app.get("/api/agreement")
    def agreement():
        return respond("model_agreement.json")

    @app.get("/api/status")
    def status():
        return respond("status.json")

    @app.get("/data/<string:name>")
    def data_file(name: str):
        if name not in exports:
            return jsonify(error=f"no export named {name!r}"), 404
        return respond(name)

    @app.get("/")
    def index():
        return send_from_directory(frontend_dir, "index.html")

    return app


if __name__ == "__main__":
    debug = os.environ.get("WHY_DEBUG", "").lower() in {"1", "true", "yes"}
    port = int(os.environ.get("PORT", "5000"))
    print(f"WHY server on http://localhost:{port}")
    create_app().run(host="127.0.0.1", port=port, debug=debug)
