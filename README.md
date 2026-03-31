<!-- Logo placeholder -->
<p align="center">
  <strong>pg-stress</strong>
</p>

<p align="center">
  PostgreSQL OLTP stress testing &rarr; ORM fingerprinting &rarr; pgbench comparison. One compose stack.
</p>

<p align="center">
  <a href="https://github.com/dataalgebra-engineering/pg-stress/actions"><img src="https://img.shields.io/github/actions/workflow/status/dataalgebra-engineering/pg-stress/ci.yml?branch=main&label=CI" alt="CI"></a>
  <a href="https://github.com/dataalgebra-engineering/pg-stress/releases"><img src="https://img.shields.io/github/v/release/dataalgebra-engineering/pg-stress" alt="Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="License"></a>
  <a href="https://github.com/dataalgebra-engineering/pg-stress/stargazers"><img src="https://img.shields.io/github/stars/dataalgebra-engineering/pg-stress?style=social" alt="Stars"></a>
</p>

## Why pg-stress?

Validating a PostgreSQL monitoring agent means running realistic workloads -- not just
`pgbench` TPC-B. pg-stress gives you three load generators hitting the same database
simultaneously, so you can verify that your collector correctly fingerprints raw SQL,
ORM-generated queries, and standard benchmarks. Everything runs in Docker Compose --
no cloud, no Kubernetes, no external dependencies.

## What does it solve?

A local-first stress testing platform for validating PostgreSQL observability tools.
Best for teams building or evaluating `pg_stat_statements`-based collectors that need
to differentiate query sources, detect N+1 patterns, and measure accuracy under load.

## How does it work?

pg-stress runs three independent load generators against a shared PostgreSQL 15 instance,
while a monitoring dashboard and optional truth-service observe the results:

| Generator | Language | Query Style | Unique Fingerprints |
|-----------|----------|-------------|---------------------|
| **Raw SQL** | Go + pgx | Hand-written SQL with explicit JOINs | ~30-40 `queryid` |
| **ORM** | Python + SQLAlchemy | N+1, eager load, EXISTS, bulk INSERT | ~50-100+ `queryid` |
| **pgbench** | PostgreSQL built-in | TPC-B + custom e-commerce scripts | ~5-15 `queryid` |

All three share the same 18-table e-commerce schema (~30M rows, ~10 GB seeded data):

```
Load Generator (Go)  ──┐
                        ├──▶  PostgreSQL 15  ◀──  Dashboard (polling pg_stat_*)
ORM Generator (Py)   ──┤         ▲
                        │         │
pgbench Runner       ──┘    pg-collector  ──▶  JSONL  ──▶  Truth Service
```

## Quick comparison

| | pg-stress | pgbench alone | k6 + SQL | Custom scripts |
|---|---|---|---|---|
| ORM query patterns | N+1, eager load, selectin, EXISTS | No | Manual only | Manual only |
| Raw SQL OLTP | 25+ e-commerce operations | TPC-B only | Custom | Custom |
| pgbench baseline | Side-by-side comparison | Yes | No | No |
| Real-time dashboard | Built-in | No | Grafana | No |
| Collector validation | Truth-service verification | No | No | No |
| Chaos injection | Deadlocks, flash sales, bulk updates | No | Limited | Manual |
| Infrastructure | `docker compose up` | CLI | Docker + config | Varies |

## Profiles

pg-stress uses Docker Compose profiles to control which services run:

| Profile | Services | Use Case |
|---------|----------|----------|
| *(none)* | postgres + raw-SQL + dashboard | Core stress testing |
| `orm` | + ORM load generator | ORM fingerprint validation |
| `pgbench` | + pgbench runner | Benchmark comparison |
| `collector` | + pg-collector + truth-service | Metric accuracy verification |
| `full` | Everything | Complete validation suite |

## Quickstart (2 minutes)

**1. Clone and start** -- seeds ~30M rows on first run (~5 minutes):

```console
$ git clone https://github.com/dataalgebra-engineering/pg-stress.git
$ cd pg-stress
$ make up
```

```
  Dashboard:  http://localhost:8000
  Postgres:   localhost:5434
  Load Gen:   http://localhost:9090/healthz
  Scenario:   default
```

**2. Add ORM generator** -- SQLAlchemy queries alongside raw SQL:

```console
$ make up-orm
```

**3. Run pgbench comparison** -- TPC-B + custom e-commerce scripts:

```console
$ make up-bench
```

**4. Start everything** -- all generators + collector + truth-service:

```console
$ make up-full
```

**5. Check health** -- verify all services are running:

```console
$ make healthz
```

**6. View query fingerprints** -- top queries by execution time:

```console
$ make pg-stat
```

## Scenarios

Three pre-configured load profiles control intensity, chaos, and safety limits:

| | Gentle | Default | Heavy |
|---|---|---|---|
| **Burst connections** | 3 / 8 / 15 | 5 / 20 / 50 | 15 / 40 / 80 |
| **Chaos injection** | Disabled | 25% probability | 50% probability |
| **Pause between bursts** | 30-120s | 20-90s | 5-20s |
| **ORM concurrency** | 2 threads | 5 threads | 15 threads |
| **Max database size** | 15 GB | 20 GB | 30 GB |

```console
$ SCENARIO=heavy make up-full
$ SCENARIO=gentle make up-orm
```

## ORM Query Patterns

The ORM load generator exercises 10 distinct SQLAlchemy patterns that produce
different `pg_stat_statements` fingerprints than hand-written SQL:

| Pattern | What pg-collector sees |
|---------|----------------------|
| **N+1 selects** | 1 `SELECT products` + N `SELECT product_variants WHERE product_id = $1` |
| **Eager joinedload** | Single `SELECT` with multiple `LEFT OUTER JOIN` chains |
| **Eager subqueryload** | `SELECT ... WHERE order_id IN (SELECT ...)` correlated subquery |
| **Eager selectinload** | `SELECT ... WHERE product_id IN ($1, $2, ..., $N)` literal IN-list |
| **Bulk INSERT** | `INSERT INTO ... VALUES (...) RETURNING id` (batched) |
| **ORM update** | `SELECT ... WHERE id = $1` then `UPDATE ... SET ... WHERE id = $1` |
| **Pagination** | `SELECT ... LIMIT $1 OFFSET $2` with ORM column lists |
| **Aggregation** | `SELECT count(), sum(), avg()` via `func()` expressions |
| **EXISTS filter** | `WHERE EXISTS (SELECT 1 FROM reviews WHERE ...)` correlated subqueries |
| **Relationship filter** | ORM-generated JOINs via `.join(Relationship)` chains |

## E-Commerce Schema

18 tables seeded with ~30M rows (~10 GB) covering a realistic e-commerce domain:

```
customers (1M) ─── addresses (2M)
    │
    ├── orders (5M) ─── order_items (15M) ─── product_variants (300K)
    │       │                                        │
    │       ├── payments (5M)                   inventory (300K)
    │       └── shipments (4M)                  price_history (700K)
    │
    ├── reviews (2M) ─── products (100K) ─── categories (500)
    │
    └── sessions (100K) ─── cart_items (dynamic)

promotions (1K) ─── coupon_redemptions (500K)
search_log (append-only)    audit_log (append-only)
```

## Deployment Layout

```
pg-stress/
├── docker-compose.yml           # Unified stack with profiles
├── docker-compose.truth.yml     # Standalone truth infrastructure
├── Makefile                     # All targets
├── .env.example                 # Environment template
│
├── load-generator/              # Go + pgx raw SQL generator
│   ├── main.go                  # Burst-based OLTP with chaos injection
│   ├── schema.sql               # 18-table schema + 30M row seed
│   └── Dockerfile
│
├── load-generator-orm/          # Python + SQLAlchemy ORM generator
│   ├── main.py                  # 10 ORM pattern workers
│   ├── models.py                # Full ORM model mapping
│   └── Dockerfile
│
├── pgbench-runner/              # pgbench comparison service
│   ├── entrypoint.sh            # Multi-mode benchmark runner
│   ├── scripts/                 # Custom e-commerce SQL scripts
│   └── Dockerfile
│
├── dashboard/                   # Real-time monitoring UI
│   ├── app/                     # FastAPI + asyncpg poller
│   ├── static/                  # HTML/JS/CSS frontend
│   └── Dockerfile
│
├── truth-service/               # Metric verification engine
│   ├── app/                     # FastAPI + verifier registry
│   │   └── verifiers/           # cache-memory, wal, locks, replication
│   └── Dockerfile
│
├── scenarios/                   # Load profiles
│   ├── gentle.yaml
│   ├── default.yaml
│   └── heavy.yaml
│
├── configs/
│   ├── postgres/                # Tuned postgresql.conf + pg_hba.conf
│   └── collector/               # pg-collector JSONL config
│
├── scripts/
│   ├── deploy-remote.sh         # SSH deployment to remote servers
│   ├── run-benchmark.sh         # pgbench comparison runner
│   └── collect-report.sh        # Gather results into reports
│
├── docs/
│   └── pgbench-comparison.md    # Three-workload comparison strategy
│
└── out/                         # Reports and benchmark results
```

## Commands

| Command | What it does |
|---------|-------------|
| `make up` | Start core stack (postgres + raw-SQL + dashboard) |
| `make up-orm` | Core + ORM load generator |
| `make up-bench` | Core + pgbench comparison |
| `make up-collector` | Core + pg-collector + truth-service |
| `make up-full` | Start everything |
| `make down` | Stop all services, remove volumes |
| `make status` | Show running containers |
| `make logs` | Follow all service logs |
| `make psql` | Interactive PostgreSQL shell |
| `make pg-stat` | Top 20 queries by execution time |
| `make pg-stat-reset` | Reset pg_stat_statements counters |
| `make db-size` | Show database and table sizes |
| `make bench` | Run pgbench benchmark locally |
| `make verify` | Run truth-service verifications |
| `make healthz` | Check health of all services |
| `make report` | Collect comprehensive report |
| `make deploy` | Deploy to remote server (default: ssh 4) |
| `make clean` | Stop everything, remove volumes and output |
| `make help` | Show all available targets |

## Features

**Load Generation**
- [x] 25+ raw SQL e-commerce operations (browse, cart, checkout, orders, reporting)
- [x] 10 SQLAlchemy ORM patterns (N+1, eager load, bulk insert, EXISTS, etc.)
- [x] pgbench TPC-B + custom e-commerce scripts for baseline comparison
- [x] Configurable traffic mix weights per operation category
- [x] Burst-based load with three intensity levels (low / medium / heavy)
- [x] Chaos injection: abandoned checkouts, flash sales, bulk price updates, deadlocks

**Monitoring & Validation**
- [x] Real-time dashboard polling pg_stat_* views every 10 seconds
- [x] Safety monitor with automatic table pruning at configurable limits
- [x] Truth-service comparing collector metrics against PostgreSQL ground truth
- [x] pg_stat_statements fingerprint comparison across all three workload sources
- [x] Structured JSON benchmark output for programmatic analysis

**Operations**
- [x] Docker Compose profiles for modular service composition
- [x] Three scenario profiles (gentle / default / heavy)
- [x] One-command remote deployment via SSH
- [x] Comprehensive report collection (pg_stat_statements, table sizes, connections, locks)
- [x] Environment-variable configuration with .env.example template

**Database**
- [x] 18-table e-commerce schema with realistic seed data (~30M rows)
- [x] Production-tuned PostgreSQL configuration (shared_buffers, WAL, autovacuum)
- [x] pg_stat_statements enabled with 10K max tracked queries
- [x] Full monitoring: track_activities, track_counts, track_io_timing, track_functions

## Documentation

| Doc | Description |
|-----|-------------|
| [pgbench Comparison Strategy](docs/pgbench-comparison.md) | Three-workload fingerprint validation methodology |
| [Environment Reference](.env.example) | All configurable environment variables |
| [Scenarios](scenarios/) | Load profile definitions (gentle / default / heavy) |

## Architecture

pg-stress is designed around a shared-database architecture where multiple independent
load generators exercise different query patterns against a single PostgreSQL instance.
A monitoring layer (dashboard + optional collector) observes `pg_stat_*` views to measure
the impact. The truth-service provides ground-truth verification by comparing collector
output against direct PostgreSQL queries.

The key architectural decision is **workload isolation by source, not by database** --
all generators share the same schema and data, which is exactly how production applications
behave. This forces the monitoring stack to differentiate workloads by query fingerprint
rather than connection metadata.

## Relationship to Burnside Project

pg-stress is part of the [Burnside Project](https://github.com/burnside-project) ecosystem:

| Project | Role |
|---------|------|
| [pg-collector](https://github.com/burnside-project/pg-collector) | PostgreSQL metrics agent (what pg-stress validates) |
| [pg-warehouse](https://github.com/burnside-project/pg-warehouse) | Local-first analytical warehouse (PostgreSQL &rarr; DuckDB) |
| **pg-stress** | OLTP stress testing + collector validation (this repo) |

## Community

- [GitHub Issues](https://github.com/dataalgebra-engineering/pg-stress/issues) -- Bugs and feature requests
- [GitHub Discussions](https://github.com/dataalgebra-engineering/pg-stress/discussions) -- Questions and ideas

## License

[Apache License 2.0](LICENSE) -- Copyright 2025-2026 [Burnside Project](https://burnsideproject.ai)
