import json
from pathlib import Path

from app.models import VerificationResult


def write_reports(result: VerificationResult, output_dir: str):
    """Write report.json and report.md to the output directory."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    with open(out / "report.json", "w") as f:
        json.dump(result.model_dump(mode="json"), f, indent=2, default=str)

    md = generate_markdown(result)
    with open(out / "report.md", "w") as f:
        f.write(md)


def generate_markdown(result: VerificationResult) -> str:
    """Generate a human-readable Markdown report."""
    lines = [
        f"# Truth Verification Report: {result.panel}",
        "",
        f"**Verdict:** {result.verdict}",
        f"**Timestamp:** {result.timestamp.isoformat()}",
        f"**Duration:** {result.duration_ms:.1f}ms",
        "",
    ]

    if result.assertions:
        lines.extend([
            "## Assertions",
            "",
            "| Metric | Ground Truth | Reported | Tolerance | Result | Detail |",
            "|--------|-------------|----------|-----------|--------|--------|",
        ])
        for a in result.assertions:
            status = "PASS" if a.passed else "FAIL"
            lines.append(
                f"| {a.metric} | {a.ground_truth} | {a.reported} "
                f"| {a.tolerance} | {status} | {a.detail} |"
            )

    if result.errors:
        lines.extend(["", "## Errors", ""])
        for e in result.errors:
            lines.append(f"- {e}")

    if result.derived:
        lines.extend(["", "## Derived Values", ""])
        for k, v in result.derived.items():
            lines.append(f"- **{k}:** {v}")

    if result.metadata:
        lines.extend(["", "## Metadata", ""])
        for k, v in result.metadata.items():
            lines.append(f"- **{k}:** {v}")

    lines.append("")
    return "\n".join(lines)