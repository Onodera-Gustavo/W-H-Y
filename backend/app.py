"""
WHY — app.py
Servidor Flask que expõe as notícias como API JSON.

Rotas:
    GET /api/news          → todas as notícias de todos os tópicos
    GET /api/news/<label>  → notícias de um tópico específico (ex: /api/news/Tesla)
    GET /                  → serve o index.html

Uso:
    pip install flask feedparser
    python app.py
"""

from flask import Flask, jsonify, send_from_directory, abort
from flask_cors import CORS
import os
import sys

# permite importar scraper mesmo rodando de fora do diretório backend
sys.path.insert(0, os.path.dirname(__file__))
from scraper import fetch_all, TOPICS

app = Flask(__name__, static_folder="../frontend", static_url_path="")
CORS(app)  # permite chamadas do frontend durante dev local

# cache simples em memória (invalida a cada hora)
_cache = {"data": None, "fetched_at": None}


def _get_data():
    """Retorna dados do cache ou busca novos."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    if _cache["data"] is None or (now - _cache["fetched_at"]) > timedelta(hours=1):
        print("🔄 Buscando notícias frescas...")
        _cache["data"]       = fetch_all()
        _cache["fetched_at"] = now
    return _cache["data"]


@app.route("/api/news")
def api_all_news():
    return jsonify(_get_data())


@app.route("/api/news/<string:label>")
def api_topic_news(label):
    data   = _get_data()
    topics = [t for t in data["topics"] if t["label"].lower() == label.lower()]
    if not topics:
        abort(404, description=f"Tópico '{label}' não encontrado.")
    return jsonify({"generated_at": data["generated_at"], "date_label": data["date_label"], **topics[0]})


@app.route("/")
def index():
    frontend_dir = os.path.join(os.path.dirname(__file__), "../frontend")
    return send_from_directory(frontend_dir, "index.html")


if __name__ == "__main__":
    print("🚀 WHY server iniciando em http://localhost:5000")
    app.run(debug=True, port=5000)