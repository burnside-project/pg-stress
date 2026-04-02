from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    SKIP = "SKIP"


class Assertion(BaseModel):
    metric: str
    ground_truth: float | int | str | None
    reported: float | int | str | None
    tolerance: str
    passed: bool
    detail: str


class SnapshotData(BaseModel):
    timestamp: datetime
    counters: dict[str, int | float] = {}
    gauges: dict[str, float] = {}
    deltas: dict[str, float] = {}
    labels: dict[str, str] = {}


class VerificationResult(BaseModel):
    panel: str
    verdict: Verdict
    timestamp: datetime
    duration_ms: float
    ground_truth: SnapshotData
    derived: dict[str, float]
    reported: SnapshotData | None
    assertions: list[Assertion]
    errors: list[str] = []
    metadata: dict = {}