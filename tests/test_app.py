from backend.app import FRONTEND_DIR, create_app
from tests.helpers import NOW
from why.cli import run_pipeline


def test_frontend_is_served(paths):
    client = create_app(paths).test_client()
    page = client.get("/")
    assert page.status_code == 200
    assert page.data == (FRONTEND_DIR / "index.html").read_bytes()


def test_nested_frontend_files_are_served_with_module_friendly_types(paths, tmp_path):
    site = tmp_path / "frontend"
    (site / "assets" / "js").mkdir(parents=True)
    (site / "index.html").write_text("<h1>home</h1>", encoding="utf-8")
    (site / "trends.html").write_text("<h1>trends</h1>", encoding="utf-8")
    (site / "assets" / "js" / "app.js").write_text("export const x = 1;", encoding="utf-8")
    (site / "assets" / "style.css").write_text("body {}", encoding="utf-8")
    client = create_app(paths, frontend_dir=site).test_client()

    assert client.get("/").data == b"<h1>home</h1>"
    assert client.get("/trends.html").data == b"<h1>trends</h1>"
    script = client.get("/assets/js/app.js")
    assert script.status_code == 200
    assert script.mimetype == "text/javascript"
    assert client.get("/assets/style.css").mimetype == "text/css"
    assert client.get("/assets/js/missing.js").status_code == 404


def test_api_without_data_explains_how_to_get_it(paths):
    client = create_app(paths).test_client()
    for url in ("/api/news", "/api/status", "/data/latest.json"):
        response = client.get(url)
        assert response.status_code == 503
        assert "py -m why run" in response.get_json()["hint"]


def test_api_serves_the_pipeline_exports(paths, offline_feed):
    run_pipeline(paths, now=NOW)
    client = create_app(paths).test_client()

    news = client.get("/api/news").get_json()
    assert news["run_date"] == "2026-09-14"
    assert news["topics"][0]["articles"][0]["sentiment"]["model"] == "vader"

    tesla = client.get("/api/news/tesla").get_json()
    assert tesla["label"] == "Tesla" and tesla["date_label"] == "Yesterday, Sep 13"
    assert client.get("/api/news/unknown").status_code == 404
    assert client.get("/api/trends").get_json()["end_date"] == "2026-09-14"
    assert client.get("/api/agreement").get_json()["n"] == 0  # FinBERT never ran


def test_status_route_and_data_files(paths, offline_feed):
    run_pipeline(paths, now=NOW)
    client = create_app(paths).test_client()

    status = client.get("/api/status").get_json()
    assert status["run"]["mode"] == "fetch"
    assert status["schedule"] == "0 9 * * *"
    # the same relative URLs the static site uses
    assert client.get("/data/status.json").get_json() == status
    assert client.get("/data/latest.json").get_json()["run_date"] == "2026-09-14"
    assert client.get("/data/trends.json").get_json()["days"] == 30
    assert client.get("/data/secrets.json").status_code == 404

    paths.status_json.unlink()  # rebuilt from the Parquet history, without a run
    rebuilt = client.get("/api/status").get_json()
    assert rebuilt["run"] is None
    assert rebuilt["history"]["headlines"] == 24


def test_api_falls_back_to_the_parquet_history(paths, offline_feed):
    run_pipeline(paths, now=NOW)
    paths.latest_json.unlink()

    news = create_app(paths).test_client().get("/api/news").get_json()
    assert sum(len(t["articles"]) for t in news["topics"]) == 24
