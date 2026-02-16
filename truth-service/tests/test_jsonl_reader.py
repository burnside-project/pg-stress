import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from app.jsonl_reader import JSONLReader, CollectorSample


def test_find_latest_sample(sample_jsonl_dir):
    reader = JSONLReader(str(sample_jsonl_dir), "truth-test")
    sample = reader.find_latest_sample("database", max_age_seconds=300)

    assert sample is not None
    assert sample.metric_type == "database"
    assert sample.database_id == "truth-test"
    assert sample.counters["blks_hit"] == 500000
    assert sample.counters["blks_read"] == 1000
    assert sample.gauges["database_size_bytes"] == 172054207.0
    assert abs(sample.deltas["cache_hit_ratio"] - 0.998004) < 1e-6
    assert sample.labels["datname"] == "testdb"


def test_find_latest_sample_empty_dir(empty_jsonl_dir):
    reader = JSONLReader(str(empty_jsonl_dir), "truth-test")
    sample = reader.find_latest_sample("database", max_age_seconds=300)
    assert sample is None


def test_find_latest_sample_nonexistent_metric(sample_jsonl_dir):
    reader = JSONLReader(str(sample_jsonl_dir), "truth-test")
    sample = reader.find_latest_sample("activity", max_age_seconds=300)
    assert sample is None


def test_find_latest_sample_expired(sample_jsonl_dir):
    reader = JSONLReader(str(sample_jsonl_dir), "truth-test")
    # Use 0 max age — sample should be considered stale
    sample = reader.find_latest_sample("database", max_age_seconds=0)
    assert sample is None


def test_find_latest_sample_wrong_database_id(sample_jsonl_dir):
    reader = JSONLReader(str(sample_jsonl_dir), "wrong-db-id")
    sample = reader.find_latest_sample("database", max_age_seconds=300)
    assert sample is None


def test_read_all_samples(sample_jsonl_dir):
    reader = JSONLReader(str(sample_jsonl_dir), "truth-test")
    samples = reader.read_all_samples("database", max_age_seconds=300)
    assert len(samples) == 1
    assert samples[0].counters["blks_hit"] == 500000


def test_read_all_samples_empty(empty_jsonl_dir):
    reader = JSONLReader(str(empty_jsonl_dir), "truth-test")
    samples = reader.read_all_samples("database", max_age_seconds=300)
    assert samples == []


def test_multiple_lines(tmp_path):
    """Test reading the last line from a multi-line JSONL file."""
    db_dir = tmp_path / "database"
    db_dir.mkdir()

    now = datetime.now(timezone.utc)
    lines = []
    for i in range(3):
        ts = (now - timedelta(seconds=(2 - i) * 10)).isoformat()
        sample = {
            "SampleID": f"sample-{i}",
            "Timestamp": ts,
            "MetricType": "database",
            "DatabaseID": "truth-test",
            "Labels": {},
            "Counters": {"blks_hit": 1000 * (i + 1)},
            "Gauges": {},
            "Deltas": {"cache_hit_ratio": 0.99},
        }
        lines.append(json.dumps(sample))

    filepath = db_dir / "truth-test_database_20260216_120000.jsonl"
    filepath.write_text("\n".join(lines) + "\n")

    reader = JSONLReader(str(tmp_path), "truth-test")
    sample = reader.find_latest_sample("database", max_age_seconds=300)

    # Should read the last line (sample-2 with blks_hit=3000)
    assert sample is not None
    assert sample.sample_id == "sample-2"
    assert sample.counters["blks_hit"] == 3000


def test_collector_sample_handles_missing_fields():
    """Test CollectorSample with minimal fields (Go's Compact strips zeroes)."""
    raw = {
        "SampleID": "minimal",
        "Timestamp": "2026-02-16T12:00:00Z",
        "MetricType": "database",
        "DatabaseID": "test",
    }
    sample = CollectorSample(raw)
    assert sample.counters == {}
    assert sample.gauges == {}
    assert sample.deltas == {}
    assert sample.labels == {}