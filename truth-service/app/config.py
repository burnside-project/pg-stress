from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # PostgreSQL connection (ground truth queries)
    pg_host: str = "postgres"
    pg_port: int = 5432
    pg_user: str = "postgres"
    pg_password: str = "postgres"
    pg_database: str = "testdb"

    # Collector JSONL output path (shared volume mount)
    collector_output_path: str = "/data/collector-output"

    # Collector database_id (used in JSONL filenames)
    collector_database_id: str = "truth-test"

    # Verification tolerances
    cache_hit_ratio_tolerance: float = 0.01  # absolute diff
    counter_tolerance_pct: float = 0.05  # 5% relative diff
    gauge_tolerance_pct: float = 0.10  # 10% relative diff
    size_tolerance_bytes: int = 10_485_760  # 10MB for database_size

    # Snapshot delay (seconds between two PG snapshots)
    snapshot_delay_seconds: int = 5

    # Max JSONL file age to consider (seconds)
    max_sample_age_seconds: int = 120

    # Service mode
    cli_mode: bool = False
    report_output_path: str = "/out"

    # FastAPI
    host: str = "0.0.0.0"
    port: int = 8000

    model_config = {"env_prefix": "TRUTH_"}