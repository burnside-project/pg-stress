from __future__ import annotations

from pathlib import Path

import yaml
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # PostgreSQL connection.
    pg_host: str = "postgres"
    pg_port: int = 5432
    pg_user: str = "postgres"
    pg_password: str = "postgres"
    pg_database: str = "testdb"

    # Load generator healthz URL.
    loadgen_url: str = "http://load-generator:9090"

    # Scenario config path (YAML).
    scenario_path: str = ""

    # Dashboard server.
    host: str = "0.0.0.0"
    port: int = 8000

    # Polling.
    poll_interval_seconds: int = 10
    retention_hours: int = 24

    # Safety monitor.
    safety_check_interval_seconds: int = 30
    max_database_size_bytes: int = 20_000_000_000  # 20GB
    prune_to_pct: int = 70
    prune_batch_size: int = 50_000

    # Table row limits (append-only tables).
    limit_search_log: int = 5_000_000
    limit_audit_log: int = 5_000_000
    limit_price_history: int = 2_000_000
    limit_cart_items: int = 1_000_000
    limit_reviews: int = 5_000_000

    model_config = {"env_prefix": "STRESS_"}

    @property
    def dsn(self) -> str:
        return f"postgresql://{self.pg_user}:{self.pg_password}@{self.pg_host}:{self.pg_port}/{self.pg_database}"

    @property
    def table_limits(self) -> dict[str, int]:
        return {
            "search_log": self.limit_search_log,
            "audit_log": self.limit_audit_log,
            "price_history": self.limit_price_history,
            "cart_items": self.limit_cart_items,
            "reviews": self.limit_reviews,
        }

    @property
    def max_samples(self) -> int:
        return (self.retention_hours * 3600) // self.poll_interval_seconds

    def load_scenario(self) -> dict:
        if self.scenario_path and Path(self.scenario_path).exists():
            with open(self.scenario_path) as f:
                return yaml.safe_load(f) or {}
        return {}
