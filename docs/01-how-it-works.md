# How It Works

pg-stress is a one-off local stress test that produces LLM-optimized PostgreSQL context.
Run it on a disposable test server. Get a Claude-powered advisory report. Tear it down.

## Three Use Cases

```
USE CASE 1: BYOD (most common)
  You have production data. Dump it, restore it, stress it.

  pg_dump production → pg_restore on test server
  Bring your own queries (or let pg-stress introspect)
  Run stress → capture → ask Claude for advice

USE CASE 2: WHAT IF (on top of BYOD)
  You have production data AND a hypothesis.

  "What if orders table grows 10M rows?"
  "What if we get 100+ concurrent connections?"
  "What if we bulk-update 20M records?"

  pg-stress injects synthetic stress on top of real data
  and measures what breaks.

USE CASE 3: SEED + STRESS (no production data)
  You don't have production-scale data yet.

  Pick a workload profile (e-commerce, CRM, SaaS, etc.)
  pg-stress seeds realistic data at target volume
  Then runs stress scenarios against it.
```

## Workflow

```
PRODUCTION                    TEST SERVER                   CLAUDE
──────────                    ───────────                   ──────

1. IMPORT
pg_dump ────────────────────▶ pg_restore
                              ANALYZE
                              Snapshot baseline

                           2. WHAT IF (optional)
                              Inject 10M rows into orders
                              Open 100 concurrent connections
                              Bulk-update 20M records
                              Run for 10-30 minutes

                           3. CAPTURE
                              pg_stat_statements (full)
                              Before/after deltas
                              Anomalies flagged

                           4. ADVISE ──────────────────▶  Tuning recommendations
                              Send context bundle           Query fixes
                              to Claude                     Capacity predictions
                                                            Breaking point analysis
                           5. TEARDOWN
                              Drop database
```

## pg-stress vs pg-collector

| | pg-stress | pg-collector |
|---|---|---|
| **When** | One-off, before a change or event | Always running |
| **Where** | Test server (disposable) | Production |
| **Data** | Your production dump | Live queries |
| **Purpose** | "What will happen?" | "What is happening?" |
| **Output** | LLM context → advisory report | Metric time-series → dashboards |

## Key Design Rules

1. **Your data first** — production dump is the default, synthetic seed is the fallback
2. **Test server is disposable** — push past safe limits, find breaking points
3. **Output is for LLMs** — structured context bundles, not dashboards
4. **Scenarios are hypothetical** — "what if 3x traffic?", not "replay yesterday"
5. **One-off** — run, report, tear down
