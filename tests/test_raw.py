from tests.helpers import NOW, make_record
from why import ingest, raw


def test_rewriting_a_partition_is_idempotent(tmp_path, feed_bytes):
    run_date = NOW.date()
    records = ingest.parse_feed(feed_bytes, "Markets", collected_at=NOW, run_date=run_date)
    path = tmp_path / "date=2026-09-14" / "markets.jsonl"

    assert raw.write_partition(tmp_path, run_date, records) == {"Markets": 4}  # 5 parsed, 1 dup
    first_bytes = path.read_bytes()

    assert raw.write_partition(tmp_path, run_date, records) == {"Markets": 4}
    assert path.read_bytes() == first_bytes


def test_a_later_run_on_the_same_day_only_adds_new_stories(tmp_path, feed_bytes):
    run_date = NOW.date()
    records = ingest.parse_feed(feed_bytes, "Markets", collected_at=NOW, run_date=run_date)
    raw.write_partition(tmp_path, run_date, records)

    later = [dict(r, collected_at="2026-09-14T15:00:00Z") for r in records]
    later.append(make_record("A brand new story", collected_at="2026-09-14T15:00:00Z"))
    assert raw.write_partition(tmp_path, run_date, later) == {"Markets": 5}

    stored = raw.read_partition(tmp_path, run_date)
    assert len(stored) == 5
    # stories already in the file keep their first sighting
    old = [r for r in stored if r["title"] != "A brand new story"]
    assert {r["collected_at"] for r in old} == {"2026-09-14T09:00:00Z"}


def test_one_file_per_topic_and_missing_partition_reads_empty(tmp_path):
    run_date = NOW.date()
    raw.write_partition(
        tmp_path, run_date, [make_record("a", topic="Markets"), make_record("b", topic="Tesla")]
    )
    folder = raw.partition_dir(tmp_path, run_date)
    assert sorted(p.name for p in folder.iterdir()) == ["markets.jsonl", "tesla.jsonl"]
    assert raw.read_partition(tmp_path, run_date.replace(day=1)) == []
