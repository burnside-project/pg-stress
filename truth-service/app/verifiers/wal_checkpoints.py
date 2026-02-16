from datetime import datetime, timezone

from app.models import VerificationResult, Verdict, SnapshotData
from app.verifiers.base import BaseVerifier


class WALCheckpointsVerifier(BaseVerifier):
    """Stub: Verifies WAL and checkpoint metrics from pg_stat_bgwriter/pg_stat_wal."""

    @property
    def panel_name(self) -> str:
        return "wal-checkpoints"

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
                "Not yet implemented. Planned metrics: checkpoints_timed, "
                "checkpoints_req, buffers_checkpoint, checkpoint_write_time_ms, "
                "checkpoint_sync_time_ms, wal_bytes, wal_buffers_full"
            ],
        )