"""AI-powered PostgreSQL test analysis using Claude.

Collects diagnostic data from a running pg-stress instance, sends it to
Claude for expert analysis, and outputs actionable recommendations for
query optimization and PostgreSQL parameter tuning.

Usage:
    # Requires ANTHROPIC_API_KEY environment variable
    python analyzer/analyze.py                     # Analyze local stack
    python analyzer/analyze.py --save              # Save report to out/
    python analyzer/analyze.py --json              # Machine-readable output
    python analyzer/analyze.py --focus tuning      # Focus on PG knob tuning
    python analyzer/analyze.py --focus queries     # Focus on query optimization
    python analyzer/analyze.py --focus capacity    # Focus on capacity prediction
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from collect import collect_all

console = Console()

SYSTEM_PROMPT = """You are a senior PostgreSQL DBA and performance engineer analyzing
stress test results from pg-stress, a multi-workload PostgreSQL testing platform.

The data you receive comes from a running PostgreSQL 15 instance under load from three
concurrent sources:
1. Raw SQL load generator (Go + pgx) — hand-written OLTP queries
2. ORM load generator (Python + SQLAlchemy 2.0) — ORM-generated queries
3. pgbench runner — standard TPC-B and custom e-commerce benchmarks

Your analysis should be actionable, specific, and backed by the data provided.
Reference specific queryid values, table names, and settings when making recommendations.
Quantify impact where possible (e.g., "increasing work_mem from 16MB to 64MB would
eliminate the 847 temp files from query 0x1234...").

Format your response in well-structured Markdown with clear sections and tables."""

ANALYSIS_PROMPT = """Analyze this PostgreSQL stress test data and provide a comprehensive report.

## Data Collected

```json
{data}
```

## Required Analysis Sections

### 1. Executive Summary
- Overall database health score (1-10) with justification
- Top 3 most impactful findings
- Estimated performance improvement potential

### 2. Query Performance Analysis
For the top problematic queries:
- Identify N+1 patterns (high call count, low rows per call, simple WHERE id = $1)
- Flag queries with poor cache hit ratios (< 0.95)
- Identify queries spilling to temp files
- Compare ORM-generated vs raw SQL query efficiency
- Estimate which queries are from SQLAlchemy vs raw pgx based on query structure
- Recommend specific index additions or query rewrites

### 3. PostgreSQL Parameter Tuning
Based on the workload characteristics observed, recommend specific changes to:
- **Memory**: shared_buffers, effective_cache_size, work_mem, maintenance_work_mem, temp_buffers
- **WAL**: max_wal_size, wal_buffers, checkpoint_completion_target
- **Planner**: random_page_cost, effective_io_concurrency, default_statistics_target
- **Parallelism**: max_parallel_workers_per_gather, max_parallel_workers
- **Autovacuum**: scale_factor, naptime, max_workers (based on dead tuple ratios)
- **Connections**: max_connections vs actual usage

For each recommendation:
- Current value → Recommended value
- Why (what data supports this change)
- Expected impact

### 4. Workload Characterization
- Read/write ratio
- Transaction commit/rollback ratio
- Cache efficiency analysis
- Lock contention assessment
- Connection utilization analysis
- Identify the heaviest workload source (raw SQL vs ORM vs pgbench)

### 5. Capacity Predictions
Based on current growth patterns:
- Database size growth rate and when it will hit limits
- Table-specific growth concerns (especially append-only tables)
- Connection headroom
- When current tuning will become insufficient

### 6. Index Recommendations
- Unused indexes that can be dropped (with size savings)
- Missing indexes suggested by seq_scan patterns
- Tables with high seq_scan / low idx_scan ratios

### 7. Action Items
Prioritized list of changes ordered by impact/effort ratio:
1. Quick wins (change a setting, drop an unused index)
2. Medium effort (add indexes, adjust autovacuum)
3. Larger changes (query rewrites, schema changes)

Include the exact PostgreSQL commands or config changes for each item."""

TUNING_FOCUS_PROMPT = """Focus specifically on PostgreSQL parameter tuning.

## Data Collected

```json
{data}
```

## Analysis Required

Provide a detailed PostgreSQL knob-tuning report:

### Current Configuration Assessment
Rate each current setting (optimal / acceptable / suboptimal / critical) based on the
observed workload.

### Recommended postgresql.conf Changes
For EVERY tuning-relevant parameter, provide:

| Parameter | Current | Recommended | Rationale |
|-----------|---------|-------------|-----------|

Group by category: Memory, WAL, Planner, Parallelism, Autovacuum, Connections, Monitoring.

### Workload-Specific Tuning
- For the OLTP burst pattern (raw SQL): what settings matter most?
- For the ORM N+1 pattern: what settings mitigate the overhead?
- For the reporting aggregation queries: what settings help?
- For chaos patterns (bulk deletes, flash sales): what settings absorb the spikes?

### Before/After Prediction
Estimate the TPS and latency improvement for each recommended change.

### Implementation Script
Provide the exact ALTER SYSTEM commands or postgresql.conf entries to apply all changes,
with a recommended restart/reload sequence."""

QUERY_FOCUS_PROMPT = """Focus specifically on query performance and optimization.

## Data Collected

```json
{data}
```

## Analysis Required

### N+1 Detection Report
From the n_plus_1_candidates data, identify confirmed N+1 patterns:
- Which queries are the repeated SELECT in an N+1 loop?
- Estimated total time wasted on N+1 patterns
- Recommended eager loading strategy for each

### Query Fingerprint Attribution
For each of the top 20 queries, determine the likely source:
- Raw SQL (Go/pgx): explicit JOINs, hand-written column lists
- ORM (SQLAlchemy): LEFT OUTER JOIN, all-column SELECT, EXISTS subqueries
- pgbench: pgbench_accounts/branches/tellers/history tables

### Slow Query Analysis
For queries with mean_exec_time > 100ms:
- Root cause (missing index, seq scan, temp spill, lock wait)
- Specific fix with example SQL

### Index Coverage
- Which queries would benefit from new indexes?
- Provide exact CREATE INDEX statements
- Estimate the improvement per query

### Cache Efficiency by Query Source
- Compare cache_hit_ratio between ORM and raw SQL queries
- Which query patterns cause the most cache misses?
- Recommendations to improve cache utilization"""

CAPACITY_FOCUS_PROMPT = """Focus specifically on capacity planning and growth predictions.

## Data Collected

```json
{data}
```

## Analysis Required

### Current State
- Total database size and breakdown by table
- Row counts and growth characteristics
- Dead tuple accumulation rate
- Temp file usage trends

### Growth Projections
For each append-only table (search_log, audit_log, price_history, cart_items, reviews):
- Current row count and size
- Estimated rows/hour based on insert patterns
- Time to hit safety limits
- Recommended retention policy

### Resource Headroom
- Connection pool utilization vs max_connections
- shared_buffers adequacy for current dataset size
- work_mem adequacy for concurrent query load
- WAL generation rate vs max_wal_size

### Scaling Recommendations
- At what TPS level will current config become the bottleneck?
- What is the first resource to exhaust?
- Recommended config for 2x, 5x, 10x current load

### Cost of Doing Nothing
What breaks first if we don't tune? Timeline and impact."""


def run_analysis(data: dict, focus: str | None = None, model: str = "claude-sonnet-4-20250514") -> str:
    """Send collected data to Claude for analysis."""
    client = anthropic.Anthropic()

    # Select prompt based on focus area.
    if focus == "tuning":
        user_prompt = TUNING_FOCUS_PROMPT.format(data=json.dumps(data, indent=2, default=str))
    elif focus == "queries":
        user_prompt = QUERY_FOCUS_PROMPT.format(data=json.dumps(data, indent=2, default=str))
    elif focus == "capacity":
        user_prompt = CAPACITY_FOCUS_PROMPT.format(data=json.dumps(data, indent=2, default=str))
    else:
        user_prompt = ANALYSIS_PROMPT.format(data=json.dumps(data, indent=2, default=str))

    console.print("[bold cyan]Sending data to Claude for analysis...[/]")
    start = time.time()

    message = client.messages.create(
        model=model,
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    elapsed = time.time() - start
    console.print(f"[dim]Analysis completed in {elapsed:.1f}s ({message.usage.input_tokens} input, {message.usage.output_tokens} output tokens)[/]")

    return message.content[0].text


def main():
    parser = argparse.ArgumentParser(description="AI-powered PostgreSQL stress test analyzer")
    parser.add_argument("--save", action="store_true", help="Save report to out/ directory")
    parser.add_argument("--json", action="store_true", help="Output raw JSON (data + analysis)")
    parser.add_argument("--focus", choices=["tuning", "queries", "capacity"],
                        help="Focus analysis on a specific area")
    parser.add_argument("--model", default="claude-sonnet-4-20250514",
                        help="Claude model to use (default: claude-sonnet-4-20250514)")
    parser.add_argument("--collect-only", action="store_true",
                        help="Only collect data, don't analyze")
    args = parser.parse_args()

    # Check API key.
    if not args.collect_only and not os.environ.get("ANTHROPIC_API_KEY"):
        console.print("[bold red]Error:[/] ANTHROPIC_API_KEY environment variable is required.")
        console.print("  export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    # Collect data.
    console.print(Panel("[bold]pg-stress AI Analyzer[/]\nCollecting PostgreSQL diagnostics...", style="cyan"))

    try:
        data = collect_all()
    except Exception as e:
        console.print(f"[bold red]Failed to connect to PostgreSQL:[/] {e}")
        console.print("  Ensure the stack is running: make up")
        sys.exit(1)

    # Summarize what we collected.
    n_queries = len(data.get("top_queries", []))
    n_tables = len(data.get("table_stats", []))
    db_size = data.get("database_stats", [{}])[0].get("db_size", "unknown")
    console.print(f"  Collected: {n_queries} queries, {n_tables} tables, DB size: {db_size}")

    if args.collect_only:
        print(json.dumps(data, indent=2, default=str))
        return

    # Run AI analysis.
    analysis = run_analysis(data, focus=args.focus, model=args.model)

    if args.json:
        output = {
            "collected_at": data["collected_at"],
            "pg_version": data["pg_version"],
            "focus": args.focus or "full",
            "model": args.model,
            "analysis": analysis,
            "data": data,
        }
        print(json.dumps(output, indent=2, default=str))
    else:
        console.print()
        console.print(Markdown(analysis))

    # Save report.
    if args.save:
        out_dir = Path("out") / f"analysis-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        out_dir.mkdir(parents=True, exist_ok=True)

        # Save raw data.
        (out_dir / "data.json").write_text(json.dumps(data, indent=2, default=str))

        # Save analysis as Markdown.
        focus_label = args.focus or "full"
        (out_dir / f"analysis-{focus_label}.md").write_text(
            f"# pg-stress AI Analysis ({focus_label})\n\n"
            f"**Generated:** {datetime.now().isoformat()}\n"
            f"**Model:** {args.model}\n"
            f"**Database:** {db_size}\n\n"
            f"---\n\n{analysis}\n"
        )

        console.print(f"\n[bold green]Report saved to {out_dir}/[/]")


if __name__ == "__main__":
    main()
