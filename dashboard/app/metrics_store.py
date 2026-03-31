from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Optional

from app.models import MetricsSample, SafetyEvent


class MetricsStore:
    """In-memory ring buffer for time-series metrics samples."""

    def __init__(self, max_samples: int = 8640):
        self.samples: deque[MetricsSample] = deque(maxlen=max_samples)
        self.safety_events: deque[SafetyEvent] = deque(maxlen=1000)

    def add(self, sample: MetricsSample) -> None:
        self.samples.append(sample)

    def add_safety_event(self, event: SafetyEvent) -> None:
        self.safety_events.append(event)

    def query(
        self,
        from_ts: Optional[datetime] = None,
        to_ts: Optional[datetime] = None,
    ) -> list[MetricsSample]:
        result = []
        for s in self.samples:
            if from_ts and s.timestamp < from_ts:
                continue
            if to_ts and s.timestamp > to_ts:
                continue
            result.append(s)
        return result

    def latest(self) -> Optional[MetricsSample]:
        return self.samples[-1] if self.samples else None

    def recent_safety_events(self, limit: int = 50) -> list[SafetyEvent]:
        events = list(self.safety_events)
        events.reverse()
        return events[:limit]
