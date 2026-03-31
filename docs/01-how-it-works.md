# How It Works

pg-stress is a one-off prediction engine. Dump production data onto a disposable test server,
run hypothetical growth scenarios, capture everything, ask Claude for tuning advice.

## Five Phases

```
PRODUCTION                 TEST SERVER                    CLAUDE
──────────                 ───────────                    ──────

pg_dump ─────────────────▶ 1. IMPORT
                              pg_restore + ANALYZE
                              Snapshot baseline

                           2. STRESS
                              Run scenario (10-30 min)
                              Traffic multiplier: 1x → 5x
                              Inject rows, chaos, ORM load

                           3. CAPTURE
                              pg_stat_statements (full)
                              Table stats, index usage
                              Before/after deltas
                              Anomalies (deadlocks, spills)

                           4. ADVISE ─────────────────▶ Query fixes
                              Send context bundle         Knob tuning
                                                          Index changes
                                                          Capacity predictions
                           5. TEARDOWN
                              Drop database, reclaim
```

## pg-stress vs pg-collector

| | pg-stress | pg-collector |
|---|---|---|
| **When** | One-off, before a change or event | Always running |
| **Where** | Test server (disposable) | Production |
| **Data** | Production dump + synthetic load | Live queries |
| **Purpose** | "What will happen?" | "What is happening?" |
| **Output** | LLM context bundle → advisory | Metric time-series → dashboards |
| **Risk** | Zero | None (read-only) |

## What the LLM Receives

Not raw numbers. A curated context bundle with before/after deltas, anomaly flags,
per-phase snapshots, and pre-formulated questions:

```
context_bundle
├── test_metadata         scenario, duration, multiplier, hardware
├── before_snapshot       baseline pg_stat_*, table sizes, indexes
├── after_snapshot        post-stress pg_stat_*, table sizes
├── deltas                size growth, cache drop, new deadlocks, degraded queries
├── per_phase_snapshots   TPS, cache ratio, p99 at each traffic level
├── anomalies             cache cliff, temp spills, lock storms (timestamped)
├── postgresql_config     current settings (30+ tuning-relevant params)
└── questions_for_llm     auto-generated from anomalies
```

## Key Design Rules

1. **Production data, not synthetic** -- real distributions, real skew, real index bloat
2. **Test server is disposable** -- push past safe limits, run destructive experiments
3. **Output is for LLMs, not dashboards** -- maximize signal per token
4. **Scenarios are hypothetical** -- "what if 3x traffic?", not "replay yesterday"
5. **One-off, not continuous** -- run, report, tear down
