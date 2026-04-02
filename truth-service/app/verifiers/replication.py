from datetime import datetime, timezone

from app.models import SnapshotData, Verdict, VerificationResult
from app.verifiers.base import BaseVerifier


class ReplicationVerifier(BaseVerifier):
    """Stub: Verifies replication metrics from pg_stat_replication."""

    @property
    def panel_name(self) -> str:
        return "replication"

    async def verify(self) -> VerificationResult:
        return VerificationResult(
            panel=self.panel_name,
            verdict=Verdict.SKIP,
            timestamp=datetime.now(timezone.utc),
            duration_ms=0,
            ground_truth=SnapshotData(timestamp=datetime.now(timezone.utc)),
            derived={},
            reported=None,
            assertions=[],
            errors=[
                "Not yet implemented. Planned metrics: write_lag_seconds, "
                "flush_lag_seconds, replay_lag_seconds, replay_lag_bytes. "
                "Requires a replica in the Docker setup."
            ],
        )