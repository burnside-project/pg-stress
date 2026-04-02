import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class CollectorSample:
    """Parsed collector JSONL sample.

    Field names are PascalCase because Go's json.Marshal uses struct field
    names when no json tags are present (see internal/sample/types.go).
    """

    def __init__(self, raw: dict):
        self.sample_id = raw.get("SampleID", "")
        self.timestamp = datetime.fromisoformat(
            raw.get("Timestamp", "").replace("Z", "+00:00")
        )
        self.metric_type = raw.get("MetricType", "")
        self.database_id = raw.get("DatabaseID", "")
        self.labels = raw.get("Labels", {})
        self.counters = raw.get("Counters", {})
        self.gauges = raw.get("Gauges", {})
        self.deltas = raw.get("Deltas", {})


class JSONLReader:
    """Reads collector JSONL output files.

    File layout (with split_by_metric_type: true):
        <base_path>/<metric_type>/<db_id>_<metric_type>_<YYYYMMDD_HHMMSS>.jsonl

    See internal/output/local/producer.go lines 182-198.
    """

    def __init__(self, base_path: str, database_id: str):
        self._base_path = Path(base_path)
        self._database_id = database_id

    def find_latest_sample(
        self,
        metric_type: str,
        max_age_seconds: int = 120,
    ) -> Optional[CollectorSample]:
        """Find the most recent sample for the given metric type."""
        metric_dir = self._base_path / metric_type
        if not metric_dir.exists():
            return None

        # Find all JSONL files, sorted by modification time (newest first)
        files = sorted(
            metric_dir.glob(f"{self._database_id}_{metric_type}_*.jsonl"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )

        now = datetime.now(timezone.utc)
        for filepath in files:
            last_line = self._read_last_line(filepath)
            if not last_line:
                continue

            try:
                raw = json.loads(last_line)
                sample = CollectorSample(raw)
                age = (now - sample.timestamp).total_seconds()
                if age <= max_age_seconds:
                    return sample
            except (json.JSONDecodeError, KeyError):
                continue

        return None

    def _read_last_line(self, filepath: Path) -> Optional[str]:
        """Read the last non-empty line from a file."""
        try:
            with open(filepath, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                if size == 0:
                    return None
                pos = size - 1
                while pos > 0:
                    f.seek(pos)
                    char = f.read(1)
                    if char == b"\n" and pos < size - 1:
                        return f.readline().decode("utf-8").strip()
                    pos -= 1
                f.seek(0)
                return f.readline().decode("utf-8").strip()
        except IOError:
            return None

    def read_all_samples(
        self,
        metric_type: str,
        max_age_seconds: int = 120,
    ) -> list[CollectorSample]:
        """Read all recent samples of a given metric type."""
        metric_dir = self._base_path / metric_type
        if not metric_dir.exists():
            return []

        now = datetime.now(timezone.utc)
        samples = []

        files = sorted(
            metric_dir.glob(f"{self._database_id}_{metric_type}_*.jsonl"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )

        for filepath in files[:5]:
            try:
                with open(filepath) as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        raw = json.loads(line)
                        s = CollectorSample(raw)
                        age = (now - s.timestamp).total_seconds()
                        if age <= max_age_seconds:
                            samples.append(s)
            except (IOError, json.JSONDecodeError):
                continue

        samples.sort(key=lambda s: s.timestamp, reverse=True)
        return samples