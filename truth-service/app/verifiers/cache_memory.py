import asyncio
import time
from datetime import datetime, timezone

from app.config import Settings
from app.models import VerificationResult, Verdict, Assertion, SnapshotData
from app.pg_client import PGClient
from app.jsonl_reader import JSONLReader
from app.verifiers.base import BaseVerifier


class CacheMemoryVerifier(BaseVerifier):
    """Verifies cache-memory panel metrics against PostgreSQL ground truth.

    Metrics verified:
        - cache_hit_ratio (Deltas) — blks_hit / (blks_read + blks_hit)
        - blks_hit (Counters)
        - blks_read (Counters)
        - database_size_bytes (Gauges)
        - numbackends (Gauges)

    The cache_hit_ratio formula matches internal/sampler/database.go:146-150.
    """

    def __init__(
        self,
        pg_client: PGClient,
        jsonl_reader: JSONLReader,
        settings: Settings,
    ):
        self._pg = pg_client
        self._reader = jsonl_reader
        self._settings = settings

    @property
    def panel_name(self) -> str:
        return "cache-memory"

    async def verify(self) -> VerificationResult:
        start_time = time.monotonic()
        errors: list[str] = []
        assertions: list[Assertion] = []

        # Step 1: Take snapshot 1
        snap1 = await self._pg.snapshot_database()

        # Step 2: Wait for inter-sample interval
        await asyncio.sleep(self._settings.snapshot_delay_seconds)

        # Step 3: Take snapshot 2
        snap2 = await self._pg.snapshot_database()

        # Step 4: Compute ground truth from snapshot 2 cumulative counters
        blks_read = snap2["blks_read"]
        blks_hit = snap2["blks_hit"]
        total_blocks = blks_read + blks_hit

        gt_cache_hit_ratio = 0.0
        if total_blocks > 0:
            gt_cache_hit_ratio = blks_hit / total_blocks

        # Compute inter-snapshot deltas for rate metrics
        elapsed = (snap2["timestamp"] - snap1["timestamp"]).total_seconds()
        gt_derived: dict[str, float] = {
            "cache_hit_ratio": gt_cache_hit_ratio,
            "elapsed_seconds": elapsed,
        }
        if elapsed > 0:
            for counter in [
                "xact_commit", "xact_rollback", "blks_read", "blks_hit",
                "tup_returned", "tup_fetched", "tup_inserted",
                "tup_updated", "tup_deleted",
            ]:
                delta = snap2[counter] - snap1[counter]
                gt_derived[f"{counter}_per_sec"] = delta / elapsed

        ground_truth = SnapshotData(
            timestamp=snap2["timestamp"],
            counters={
                "blks_read": blks_read,
                "blks_hit": blks_hit,
                "xact_commit": snap2["xact_commit"],
                "xact_rollback": snap2["xact_rollback"],
                "tup_returned": snap2["tup_returned"],
                "tup_fetched": snap2["tup_fetched"],
                "tup_inserted": snap2["tup_inserted"],
                "tup_updated": snap2["tup_updated"],
                "tup_deleted": snap2["tup_deleted"],
                "deadlocks": snap2["deadlocks"],
            },
            gauges={
                "database_size_bytes": float(snap2["database_size_bytes"]),
                "numbackends": float(snap2["numbackends"]),
            },
            deltas={"cache_hit_ratio": gt_cache_hit_ratio},
            labels={"datname": snap2["datname"]},
        )

        # Step 5: Read latest collector sample
        collector_sample = self._reader.find_latest_sample(
            "database",
            max_age_seconds=self._settings.max_sample_age_seconds,
        )

        reported = None
        if collector_sample is None:
            errors.append(
                "No recent collector database sample found in JSONL output. "
                f"Searched: {self._reader._base_path}/database/"
            )
        else:
            reported = SnapshotData(
                timestamp=collector_sample.timestamp,
                counters={k: int(v) for k, v in collector_sample.counters.items()},
                gauges=collector_sample.gauges,
                deltas=collector_sample.deltas,
                labels=collector_sample.labels,
            )

        # Step 6: Build assertions
        tol = self._settings

        # A) cache_hit_ratio
        if collector_sample and "cache_hit_ratio" in collector_sample.deltas:
            rep_chr = collector_sample.deltas["cache_hit_ratio"]
            diff = abs(gt_cache_hit_ratio - rep_chr)
            passed = diff <= tol.cache_hit_ratio_tolerance
            assertions.append(Assertion(
                metric="cache_hit_ratio",
                ground_truth=round(gt_cache_hit_ratio, 8),
                reported=round(rep_chr, 8),
                tolerance=f"abs <= {tol.cache_hit_ratio_tolerance}",
                passed=passed,
                detail=(
                    f"Ground truth {gt_cache_hit_ratio:.6f} vs "
                    f"reported {rep_chr:.6f}, diff={diff:.8f}"
                ),
            ))
        elif collector_sample:
            assertions.append(Assertion(
                metric="cache_hit_ratio",
                ground_truth=round(gt_cache_hit_ratio, 8),
                reported=None,
                tolerance=f"abs <= {tol.cache_hit_ratio_tolerance}",
                passed=False,
                detail="cache_hit_ratio not found in collector Deltas",
            ))

        # B) blks_hit counter
        if collector_sample and "blks_hit" in collector_sample.counters:
            rep_val = collector_sample.counters["blks_hit"]
            gt_val = blks_hit
            if gt_val > 0:
                pct_diff = abs(gt_val - rep_val) / gt_val
                passed = pct_diff <= tol.counter_tolerance_pct
                detail = f"GT={gt_val}, reported={rep_val}, diff={pct_diff:.4%}"
            else:
                passed = rep_val == 0
                detail = f"GT=0, reported={rep_val}"
            assertions.append(Assertion(
                metric="blks_hit",
                ground_truth=gt_val,
                reported=rep_val,
                tolerance=f"rel <= {tol.counter_tolerance_pct:.0%}",
                passed=passed,
                detail=detail,
            ))

        # C) blks_read counter
        if collector_sample and "blks_read" in collector_sample.counters:
            rep_val = collector_sample.counters["blks_read"]
            gt_val = blks_read
            if gt_val > 0:
                pct_diff = abs(gt_val - rep_val) / gt_val
                passed = pct_diff <= tol.counter_tolerance_pct
                detail = f"GT={gt_val}, reported={rep_val}, diff={pct_diff:.4%}"
            else:
                passed = rep_val == 0
                detail = f"GT=0, reported={rep_val}"
            assertions.append(Assertion(
                metric="blks_read",
                ground_truth=gt_val,
                reported=rep_val,
                tolerance=f"rel <= {tol.counter_tolerance_pct:.0%}",
                passed=passed,
                detail=detail,
            ))

        # D) database_size_bytes gauge
        if collector_sample and "database_size_bytes" in collector_sample.gauges:
            rep_val = collector_sample.gauges["database_size_bytes"]
            gt_val = float(snap2["database_size_bytes"])
            diff = abs(gt_val - rep_val)
            passed = diff <= tol.size_tolerance_bytes
            assertions.append(Assertion(
                metric="database_size_bytes",
                ground_truth=gt_val,
                reported=rep_val,
                tolerance=f"abs <= {tol.size_tolerance_bytes} bytes",
                passed=passed,
                detail=f"GT={gt_val:.0f}, reported={rep_val:.0f}, diff={diff:.0f}",
            ))

        # E) numbackends gauge (fluctuates, allow +/-2)
        if collector_sample and "numbackends" in collector_sample.gauges:
            rep_val = collector_sample.gauges["numbackends"]
            gt_val = float(snap2["numbackends"])
            diff = abs(gt_val - rep_val)
            passed = diff <= 2
            assertions.append(Assertion(
                metric="numbackends",
                ground_truth=gt_val,
                reported=rep_val,
                tolerance="abs <= 2",
                passed=passed,
                detail=f"GT={gt_val:.0f}, reported={rep_val:.0f}, diff={diff:.0f}",
            ))

        # Determine verdict
        if errors:
            verdict = Verdict.FAIL
        elif not assertions:
            verdict = Verdict.SKIP
        elif all(a.passed for a in assertions):
            verdict = Verdict.PASS
        else:
            verdict = Verdict.FAIL

        elapsed_ms = (time.monotonic() - start_time) * 1000

        return VerificationResult(
            panel="cache-memory",
            verdict=verdict,
            timestamp=datetime.now(timezone.utc),
            duration_ms=round(elapsed_ms, 2),
            ground_truth=ground_truth,
            derived=gt_derived,
            reported=reported,
            assertions=assertions,
            errors=errors,
            metadata={
                "snapshot1_ts": snap1["timestamp"].isoformat(),
                "snapshot2_ts": snap2["timestamp"].isoformat(),
                "snapshot_delay_seconds": self._settings.snapshot_delay_seconds,
                "collector_sample_path": f"{self._reader._base_path}/database",
                "collector_sample_age_limit": self._settings.max_sample_age_seconds,
            },
        )