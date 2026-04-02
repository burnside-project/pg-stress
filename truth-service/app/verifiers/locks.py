from datetime import datetime, timezone

from app.models import SnapshotData, Verdict, VerificationResult
from app.verifiers.base import BaseVerifier


class LocksVerifier(BaseVerifier):
    """Stub: Verifies lock metrics from pg_locks."""

    @property
    def panel_name(self) -> str:
        return "locks"

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
                "Not yet implemented. Planned metrics: lock_count, "
                "lock_wait_count, blocking_pids"
            ],
        )