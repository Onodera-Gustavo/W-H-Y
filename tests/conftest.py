from pathlib import Path

import pytest

from why import ingest
from why.config import Paths

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def feed_bytes() -> bytes:
    return (FIXTURES / "google_news_sample.xml").read_bytes()


@pytest.fixture
def paths(tmp_path) -> Paths:
    return Paths.under(tmp_path)


@pytest.fixture
def offline_feed(monkeypatch, feed_bytes) -> list[str]:
    """Every topic download returns the local fixture. Yields the queries requested."""
    calls: list[str] = []

    def fake_fetch(query, session=None):
        calls.append(query)
        return feed_bytes

    monkeypatch.setattr(ingest, "fetch_feed", fake_fetch)
    return calls


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Any real HTTP call in a test is a bug."""

    def refuse(*args, **kwargs):
        raise AssertionError("tests must not touch the network")

    monkeypatch.setattr("requests.sessions.Session.request", refuse)
