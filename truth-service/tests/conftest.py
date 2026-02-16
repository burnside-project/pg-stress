import pytest
import json
import os
from pathlib import Path
from datetime import datetime, timezone


@pytest.fixture
def sample_jsonl_dir(tmp_path):
    """Create a temporary directory with sample collector JSONL output."""
    db_dir = tmp_path / "database"
    db_dir.mkdir()

    sample = {
        "SampleID": "abc123",
        "ScheduledAt": 1770237152419,
        "CollectedAt": 1770237152432,
        "IntervalMs": 10000,
        "CollectionLagMs": 13,
        "IsStale": False,
        "SchemaVersion": 2,
        "AgentVersion": "v1.1.0",
        "PostgresVersion": "PostgreSQL 15.0",
        "Capabilities": 36859,
        "IsPrimary": True,
        "Timestamp": datetime.now(timezone.utc).isoformat(),
        "MetricType": "database",
        "OrgID": "test-customer",
        "CustomerID": "test-customer",
        "DatabaseID": "truth-test",
        "DatabaseName": "Test DB",
        "TenantTier": "demo",
        "Labels": {"datname": "testdb"},
        "Counters": {
            "blks_hit": 500000,
            "blks_read": 1000,
            "xact_commit": 10000,
            "xact_rollback": 5,
            "tup_returned": 200000,
            "tup_fetched": 50000,
            "tup_inserted": 1000,
            "tup_updated": 500,
            "tup_deleted": 100,
            "conflicts": 0,
            "temp_files": 0,
            "temp_bytes": 0,
            "deadlocks": 0,
        },
        "Gauges": {
            "database_size_bytes": 172054207.0,
            "database_size_mb": 164.08,
            "database_size_gb": 0.16,
            "numbackends": 2.0,
        },
        "Deltas": {
            "cache_hit_ratio": 0.998004,
        },
    }

    filename = "truth-test_database_20260216_120000.jsonl"
    filepath = db_dir / filename
    filepath.write_text(json.dumps(sample) + "\n")

    return tmp_path


@pytest.fixture
def empty_jsonl_dir(tmp_path):
    """Create an empty directory structure (no JSONL files)."""
    db_dir = tmp_path / "database"
    db_dir.mkdir()
    return tmp_path