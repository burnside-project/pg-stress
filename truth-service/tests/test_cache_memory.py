from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.config import Settings
from app.jsonl_reader import CollectorSample, JSONLReader
from app.models import Verdict
from app.pg_client import PGClient
from app.verifiers.cache_memory import CacheMemoryVerifier


def _make_pg_snapshot(blks_hit=500000, blks_read=1000, **overrides):
    """Create a mock pg_stat_database snapshot."""
    base = {
        "timestamp": datetime.now(timezone.utc),
        "datname": "testdb",
        "numbackends": 2,
        "xact_commit": 10000,
        "xact_rollback": 5,
        "blks_read": blks_read,
        "blks_hit": blks_hit,
        "tup_returned": 200000,
        "tup_fetched": 50000,
        "tup_inserted": 1000,
        "tup_updated": 500,
        "tup_deleted": 100,
        "conflicts": 0,
        "temp_files": 0,
        "temp_bytes": 0,
        "deadlocks": 0,
        "stats_reset": None,
        "database_size_bytes": 172054207,
    }
    base.update(overrides)
    return base


def _make_collector_sample(
    cache_hit_ratio=0.998004,
    blks_hit=500000,
    blks_read=1000,
    db_size=172054207.0,
    numbackends=2.0,
):
    """Create a mock CollectorSample."""
    sample = CollectorSample({
        "SampleID": "test-sample",
        "Timestamp": datetime.now(timezone.utc).isoformat(),
        "MetricType": "database",
        "DatabaseID": "truth-test",
        "Labels": {"datname": "testdb"},
        "Counters": {
            "blks_hit": blks_hit,
            "blks_read": blks_read,
            "xact_commit": 10000,
        },
        "Gauges": {
            "database_size_bytes": db_size,
            "numbackends": numbackends,
        },
        "Deltas": {
            "cache_hit_ratio": cache_hit_ratio,
        },
    })
    return sample


@pytest.fixture
def settings():
    return Settings(
        snapshot_delay_seconds=0,  # No delay in tests
        max_sample_age_seconds=300,
    )


@pytest.mark.asyncio
async def test_verify_pass(settings):
    """Test that matching metrics produce PASS verdict."""
    pg_client = MagicMock(spec=PGClient)
    pg_client.snapshot_database = AsyncMock(side_effect=[
        _make_pg_snapshot(),
        _make_pg_snapshot(),
    ])

    jsonl_reader = MagicMock(spec=JSONLReader)
    jsonl_reader.find_latest_sample.return_value = _make_collector_sample()
    jsonl_reader._base_path = "/data/collector-output"

    verifier = CacheMemoryVerifier(pg_client, jsonl_reader, settings)
    result = await verifier.verify()

    assert result.verdict == Verdict.PASS
    assert len(result.assertions) == 5
    assert all(a.passed for a in result.assertions)
    assert result.errors == []


@pytest.mark.asyncio
async def test_verify_fail_cache_ratio(settings):
    """Test that mismatched cache_hit_ratio produces FAIL."""
    pg_client = MagicMock(spec=PGClient)
    pg_client.snapshot_database = AsyncMock(side_effect=[
        _make_pg_snapshot(blks_hit=500000, blks_read=1000),
        _make_pg_snapshot(blks_hit=500000, blks_read=1000),
    ])

    # Report a significantly different cache_hit_ratio
    jsonl_reader = MagicMock(spec=JSONLReader)
    jsonl_reader.find_latest_sample.return_value = _make_collector_sample(
        cache_hit_ratio=0.5,
    )
    jsonl_reader._base_path = "/data/collector-output"

    verifier = CacheMemoryVerifier(pg_client, jsonl_reader, settings)
    result = await verifier.verify()

    assert result.verdict == Verdict.FAIL
    chr_assertion = next(a for a in result.assertions if a.metric == "cache_hit_ratio")
    assert not chr_assertion.passed


@pytest.mark.asyncio
async def test_verify_fail_no_collector_sample(settings):
    """Test FAIL when no collector sample is found."""
    pg_client = MagicMock(spec=PGClient)
    pg_client.snapshot_database = AsyncMock(side_effect=[
        _make_pg_snapshot(),
        _make_pg_snapshot(),
    ])

    jsonl_reader = MagicMock(spec=JSONLReader)
    jsonl_reader.find_latest_sample.return_value = None
    jsonl_reader._base_path = "/data/collector-output"

    verifier = CacheMemoryVerifier(pg_client, jsonl_reader, settings)
    result = await verifier.verify()

    assert result.verdict == Verdict.FAIL
    assert len(result.errors) > 0
    assert "No recent collector" in result.errors[0]


@pytest.mark.asyncio
async def test_verify_cache_hit_ratio_formula(settings):
    """Verify the cache_hit_ratio formula matches database.go:146-150."""
    blks_hit = 619786
    blks_read = 1583
    expected_ratio = blks_hit / (blks_read + blks_hit)  # 0.99745...

    pg_client = MagicMock(spec=PGClient)
    pg_client.snapshot_database = AsyncMock(side_effect=[
        _make_pg_snapshot(blks_hit=blks_hit, blks_read=blks_read),
        _make_pg_snapshot(blks_hit=blks_hit, blks_read=blks_read),
    ])

    jsonl_reader = MagicMock(spec=JSONLReader)
    jsonl_reader.find_latest_sample.return_value = _make_collector_sample(
        cache_hit_ratio=expected_ratio,
        blks_hit=blks_hit,
        blks_read=blks_read,
    )
    jsonl_reader._base_path = "/data/collector-output"

    verifier = CacheMemoryVerifier(pg_client, jsonl_reader, settings)
    result = await verifier.verify()

    assert result.verdict == Verdict.PASS
    assert result.derived["cache_hit_ratio"] == pytest.approx(expected_ratio, abs=1e-10)


@pytest.mark.asyncio
async def test_verify_zero_blocks(settings):
    """Test edge case where no blocks have been read/hit."""
    pg_client = MagicMock(spec=PGClient)
    pg_client.snapshot_database = AsyncMock(side_effect=[
        _make_pg_snapshot(blks_hit=0, blks_read=0),
        _make_pg_snapshot(blks_hit=0, blks_read=0),
    ])

    jsonl_reader = MagicMock(spec=JSONLReader)
    # Collector won't emit cache_hit_ratio when total_blocks=0
    sample = CollectorSample({
        "SampleID": "zero-blocks",
        "Timestamp": datetime.now(timezone.utc).isoformat(),
        "MetricType": "database",
        "DatabaseID": "truth-test",
        "Labels": {"datname": "testdb"},
        "Counters": {"blks_hit": 0, "blks_read": 0},
        "Gauges": {"database_size_bytes": 172054207.0, "numbackends": 2.0},
        "Deltas": {},  # No cache_hit_ratio when total_blocks=0
    })
    jsonl_reader.find_latest_sample.return_value = sample
    jsonl_reader._base_path = "/data/collector-output"

    verifier = CacheMemoryVerifier(pg_client, jsonl_reader, settings)
    result = await verifier.verify()

    # cache_hit_ratio assertion should FAIL (missing from Deltas)
    chr_assertion = next(
        (a for a in result.assertions if a.metric == "cache_hit_ratio"), None
    )
    if chr_assertion:
        assert not chr_assertion.passed