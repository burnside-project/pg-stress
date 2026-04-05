# How It Works

pg-stress is a **100% local, one-off** stress testing platform. It connects to
any PostgreSQL database, introspects the schema, and generates stress tests
automatically. No configuration files to write. No models to map. No queries
to define. No data leaves your machine.

Unlike [pg-collector](https://github.com/burnside-project/pg-collector) which runs
in production and ships telemetry, pg-stress is designed for **disposable test servers**.
Import a production dump, stress it, get AI recommendations, throw it away.

## Key Concepts

- **Named Test Runs** — Every test starts from a known baseline (production dump).
  Before/after snapshots are saved so you can compare runs.
- **Live Activity** — Watch real queries from `pg_stat_activity` in real-time,
  color-coded by type (SELECT, INSERT, JOIN, EXISTS).
- **Schema Introspection** — Auto-discovers tables, FKs, indexes, classifies each table,
  generates ORM classes and query patterns automatically.
- **AI Analysis** — Claude reads 11 PostgreSQL diagnostic datasets and returns
  actionable tuning advice, query fixes, capacity predictions.

## Three Phases at Startup

```
YOUR DATABASE
     │
     ▼
1. INTROSPECT
   Connect to PostgreSQL, discover:
   ├── Tables, columns, types, PKs
   ├── Foreign keys → relationship graph
   ├── FK chains (depth 2-4) for query patterns
   ├── Row counts → max IDs per table
   ├── Indexes (btree, gin, gist)
   └── Classify each table:
       entity | transactional | append_only | lookup | hierarchical
     │
     ▼
2. REFLECT
   SQLAlchemy automap_base():
   ├── ORM classes generated for every table
   ├── Relationships auto-detected from FK constraints
   └── Works with 5 tables or 500 tables
     │
     ▼
3. GENERATE LOAD
   10 ORM patterns applied to discovered schema:
   ├── N+1 selects on any FK chain
   ├── Eager JOIN/subquery/selectin on any relationship
   ├── Bulk INSERT on any append-only table
   ├── Load-modify-save on any table with timestamps
   ├── Pagination on any table with ordering columns
   ├── Aggregation on any numeric column grouped by FK
   ├── EXISTS subqueries on any parent-child relationship
   └── Relationship JOINs on any FK path
```

## What Gets Classified

| Signal | Classification | Load Pattern |
|---|---|---|
| Has FK children + timestamps | **entity** | Read-heavy, relationship traversal |
| Has status column + updated_at | **transactional** | CRUD + status transitions |
| Only created_at, no updates | **append_only** | Bulk insert + time-range queries |
| Small row count, no FK children | **lookup** | Read-only cache-friendly |
| Self-referencing FK (parent_id) | **hierarchical** | Tree traversal |

## Two Ways to Use It

> pg-stress always runs its own PostgreSQL container. It does **not** connect
> to a remote database. To test production data, export a dump and import it.

**Path A — BYOD (primary):** Export a dump from production, import it into the
local container, then pg-stress auto-discovers everything.

```bash
# 1. On your production server:
pg_dump -Fc -h prod-host -U prod_user -d my_production_db > production.dump

# 2. In pg-stress — configure .env:
PG_DATABASE=my_production_db    # match the DB name in your dump
SEED_SCHEMA=false               # skip built-in schema

# 3. Import and start:
make import DUMP=production.dump
make up INTENSITY=medium
```

**Path B — Seed (demo):** Use the built-in e-commerce schema to test pg-stress itself.

```bash
make up    # SEED_SCHEMA=true by default, seeds 30M rows on first run
```

Both paths produce the same result: pg-stress introspects whatever it finds
and generates load automatically.
