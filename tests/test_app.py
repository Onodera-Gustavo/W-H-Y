from backend.app import create_app
from tests.helpers import NOW
from why.cli import run_pipeline


def test_frontend_is_served(paths):
    client = create_app(paths).test_client()
    page = client.get("/")
    assert page.status_code == 200
    assert b"What Happened Yesterday" in page.data
    assert client.get("/style.css").status_code == 200


def test_api_without_data_explains_how_to_get_it(paths):
    response = create_app(paths).test_client().get("/api/news")
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


def test_api_falls_back_to_the_parquet_history(paths, offline_feed):
    run_pipeline(paths, now=NOW)
    paths.latest_json.unlink()

    news = create_app(paths).test_client().get("/api/news").get_json()
    assert sum(len(t["articles"]) for t in news["topics"]) == 24
