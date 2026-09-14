from why.dedup import dedup_key, normalize_link


def test_tracking_noise_does_not_change_the_key():
    base = "https://news.google.com/rss/articles/CBMiABC?oc=5"
    variants = [
        "https://news.google.com/rss/articles/CBMiABC?oc=6",
        "http://www.news.google.com/rss/articles/CBMiABC/?utm_source=x&utm_medium=email",
        "https://NEWS.google.com/rss/articles/CBMiABC#top",
    ]
    key = dedup_key(base, "t", "s")
    assert all(dedup_key(v, "other title", "other source") == key for v in variants)


def test_meaningful_query_parameters_are_kept_and_sorted():
    assert normalize_link("https://example.com/a?id=2&page=1") == "https://example.com/a?id=2&page=1"
    assert normalize_link("https://example.com/a?page=1&id=2") == "https://example.com/a?id=2&page=1"
    assert dedup_key("https://example.com/a?id=1", "t", "s") != dedup_key(
        "https://example.com/a?id=2", "t", "s"
    )


def test_without_a_link_the_key_falls_back_to_title_and_source():
    assert normalize_link("#") is None
    assert normalize_link("") is None
    key = dedup_key("#", "Fed  holds rates", "Reuters")
    assert key == dedup_key(None, "fed holds rates", " reuters ")
    assert key != dedup_key(None, "Fed holds rates", "Bloomberg")
