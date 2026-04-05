"""Templatized ORM load generator for pg-stress.

Works with ANY PostgreSQL schema — not hardcoded to e-commerce.
At startup:
  1. Introspects the database (tables, FKs, indexes, row counts)
  2. Auto-generates ORM models via SQLAlchemy automap
  3. Builds operation templates from the FK graph
  4. Runs weighted random operations against discovered schema

Each operation is a generic pattern (N+1, eager load, pagination, etc.)
applied to real FK chains found in your schema.
"""

import json
import logging
import os
import random
import signal
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

from introspect import SchemaProfile, introspect_schema
from models import reflect_database
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, joinedload, selectinload, subqueryload

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("orm-load")


# ── Configuration ────────────────────────────────────────────────────────

def env_int(key: str, default: int) -> int:
    v = os.environ.get(key)
    return int(v) if v else default

PG_CONN = os.environ.get("PG_CONN", "postgresql://postgres:postgres@localhost:5432/testdb")
CONCURRENCY = env_int("ORM_CONCURRENCY", 5)
DURATION = env_int("ORM_DURATION", 0)
STATS_INTERVAL = env_int("ORM_STATS_INTERVAL", 30)
PAUSE_MIN = env_int("ORM_PAUSE_MIN", 10)
PAUSE_MAX = env_int("ORM_PAUSE_MAX", 50)

# Pattern mix weights.
MIX = {
    "n_plus_1":       env_int("ORM_MIX_N_PLUS_1", 15),
    "eager_join":     env_int("ORM_MIX_EAGER_JOIN", 15),
    "eager_subquery": env_int("ORM_MIX_EAGER_SUBQUERY", 10),
    "eager_selectin": env_int("ORM_MIX_EAGER_SELECTIN", 10),
    "bulk_insert":    env_int("ORM_MIX_BULK_INSERT", 5),
    "orm_update":     env_int("ORM_MIX_ORM_UPDATE", 10),
    "pagination":     env_int("ORM_MIX_PAGINATION", 10),
    "aggregation":    env_int("ORM_MIX_AGGREGATION", 10),
    "exists_filter":  env_int("ORM_MIX_EXISTS_FILTER", 10),
    "relationship":   env_int("ORM_MIX_RELATIONSHIP", 5),
}


# ── Stats ────────────────────────────────────────────────────────────────

class Stats:
    def __init__(self):
        self._lock = threading.Lock()
        self.counters = {k: 0 for k in MIX}
        self.counters["errors"] = 0
        self.start_time = time.time()

    def inc(self, key: str):
        with self._lock:
            self.counters[key] = self.counters.get(key, 0) + 1

    def snapshot(self) -> dict:
        with self._lock:
            return {"status": "running", "uptime_s": int(time.time() - self.start_time), "ops": dict(self.counters)}

stats = Stats()

# Populated after introspection — exposed via /schema endpoint.
_schema_info: dict = {}


# ── Shutdown ─────────────────────────────────────────────────────────────

shutdown = threading.Event()

def handle_signal(sig, frame):
    log.info("Received signal %s, shutting down...", sig)
    shutdown.set()

signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)


# ── Healthz ──────────────────────────────────────────────────────────────

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(stats.snapshot()).encode())
        elif self.path == "/schema":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(_schema_info).encode())
        else:
            self.send_response(404)
            self.end_headers()
    def log_message(self, fmt, *args):
        pass


# ── Templatized Operations ───────────────────────────────────────────────
#
# Each operation is a generic pattern applied to discovered FK chains.
# They receive the schema profile and models, not hardcoded table names.


class OperationContext:
    """Holds everything an operation needs: models, profile, FK chains."""

    def __init__(self, models, profile: SchemaProfile):
        self.models = models
        self.profile = profile

        # Pre-compute useful structures.
        self.children_of = defaultdict(list)  # parent → [child tables]
        self.parent_of = defaultdict(list)    # child → [parent tables]
        self.fk_map = {}                      # (child, parent) → fk_column

        for rel in profile.relationships:
            self.children_of[rel.parent_table].append(rel.child_table)
            self.parent_of[rel.child_table].append(rel.parent_table)
            self.fk_map[(rel.child_table, rel.parent_table)] = rel.fk_column

        # Tables with enough rows to query.
        self.queryable = [
            t for t, tp in profile.tables.items()
            if tp.row_count >= 100 and models.has_table(t)
        ]

        # FK chains of depth 2+ (for N+1 and eager load).
        self.chains_2 = [c for c in profile.fk_chains if c.depth >= 2 and all(models.has_table(t) for t in c.tables)]
        self.chains_3 = [c for c in profile.fk_chains if c.depth >= 3 and all(models.has_table(t) for t in c.tables)]

        # Tables suitable for specific operations.
        self.insertable = [
            t for t in (profile.append_only_tables + profile.transactional_tables)
            if models.has_table(t) and profile.tables[t].row_count > 0
        ]
        self.updatable = [
            t for t, tp in profile.tables.items()
            if tp.timestamp_columns and models.has_table(t) and tp.row_count >= 100
            and tp.role in ("transactional", "entity")
        ]
        self.paginable = [
            t for t, tp in profile.tables.items()
            if tp.row_count >= 1000 and tp.timestamp_columns and models.has_table(t)
        ]
        self.aggregable = [
            t for t, tp in profile.tables.items()
            if tp.numeric_columns and tp.foreign_keys and tp.row_count >= 1000 and models.has_table(t)
        ]
        self.has_rels = [
            t for t in profile.tables
            if self.children_of.get(t) and models.has_table(t)
            and profile.tables[t].row_count >= 100
        ]

    def max_id(self, table: str) -> int:
        return self.profile.max_ids.get(table, 1000)

    def get_model(self, table: str):
        return self.models.get_model(table)

    def get_relationship_attr(self, model, child_table: str):
        """Find the automap relationship attribute name for a child table."""
        for attr_name in dir(model):
            if attr_name.startswith("_"):
                continue
            attr = getattr(model, attr_name, None)
            if hasattr(attr, "property") and hasattr(attr.property, "mapper"):
                if attr.property.mapper.mapped_table.name == child_table:
                    return attr_name
        return None


def op_n_plus_1(session: Session, ctx: OperationContext):
    """N+1 pattern on any FK chain depth >= 2."""
    if not ctx.chains_2:
        return
    chain = random.choice(ctx.chains_2)
    ParentModel = ctx.get_model(chain.tables[0])
    if not ParentModel:
        return

    parents = session.scalars(
        select(ParentModel).limit(10)
    ).all()

    # Trigger lazy loads down the chain.
    for p in parents:
        for child_table in chain.tables[1:]:
            rel_attr = ctx.get_relationship_attr(ParentModel, child_table)
            if rel_attr:
                _ = getattr(p, rel_attr, None)


def op_eager_join(session: Session, ctx: OperationContext):
    """Eager joinedload on any FK chain."""
    if not ctx.chains_2:
        return
    chain = random.choice(ctx.chains_2)
    RootModel = ctx.get_model(chain.tables[0])
    if not RootModel:
        return

    # Build joinedload chain.
    root_rel = ctx.get_relationship_attr(RootModel, chain.tables[1])
    if not root_rel:
        return

    query = select(RootModel).options(
        joinedload(getattr(RootModel, root_rel))
    ).limit(5)

    results = session.scalars(query).unique().all()
    _ = len(results)


def op_eager_subquery(session: Session, ctx: OperationContext):
    """Eager subqueryload on any FK chain."""
    if not ctx.chains_2:
        return
    chain = random.choice(ctx.chains_2)
    RootModel = ctx.get_model(chain.tables[0])
    if not RootModel:
        return

    root_rel = ctx.get_relationship_attr(RootModel, chain.tables[1])
    if not root_rel:
        return

    results = session.scalars(
        select(RootModel).options(
            subqueryload(getattr(RootModel, root_rel))
        ).limit(10)
    ).all()
    _ = len(results)


def op_eager_selectin(session: Session, ctx: OperationContext):
    """Eager selectinload on any FK chain."""
    if not ctx.chains_2:
        return
    chain = random.choice(ctx.chains_2)
    RootModel = ctx.get_model(chain.tables[0])
    if not RootModel:
        return

    root_rel = ctx.get_relationship_attr(RootModel, chain.tables[1])
    if not root_rel:
        return

    results = session.scalars(
        select(RootModel).options(
            selectinload(getattr(RootModel, root_rel))
        ).limit(20)
    ).all()
    _ = len(results)


def op_bulk_insert(session: Session, ctx: OperationContext):
    """Bulk INSERT via add_all() on any append-only or transactional table."""
    if not ctx.insertable:
        return
    table_name = random.choice(ctx.insertable)
    Model = ctx.get_model(table_name)
    if not Model:
        return

    tp = ctx.profile.tables[table_name]

    # Clone existing rows (SELECT random subset → re-insert without PK).
    source_rows = session.scalars(
        select(Model).order_by(func.random()).limit(random.randint(3, 15))
    ).all()

    if not source_rows:
        return

    pk_cols = set(tp.pk_columns)
    serial_cols = {c.name for c in tp.columns if c.is_serial}
    skip_cols = pk_cols | serial_cols

    new_objects = []
    for row in source_rows:
        obj = Model()
        for col in tp.columns:
            if col.name not in skip_cols:
                val = getattr(row, col.name, None)
                if val is not None:
                    setattr(obj, col.name, val)
        # Update timestamp if present.
        for ts_col in ["created_at", "logged_at", "recorded_at"]:
            if ts_col in [c.name for c in tp.columns]:
                setattr(obj, ts_col, datetime.now(timezone.utc))
        new_objects.append(obj)

    session.add_all(new_objects)
    session.flush()


def op_orm_update(session: Session, ctx: OperationContext):
    """ORM load-modify-save on any updatable table."""
    if not ctx.updatable:
        return
    table_name = random.choice(ctx.updatable)
    Model = ctx.get_model(table_name)
    if not Model:
        return

    tp = ctx.profile.tables[table_name]
    max_id = ctx.max_id(table_name)

    # Load a random row by PK.
    pk_col = tp.pk_columns[0] if tp.pk_columns else None
    if not pk_col:
        return

    row = session.get(Model, random.randint(1, max_id))
    if not row:
        return

    # Update a timestamp column.
    for ts_col in ["updated_at", "modified_at", "last_active", "last_login", "changed_at"]:
        if hasattr(row, ts_col):
            setattr(row, ts_col, datetime.now(timezone.utc))
            break

    # Update a status column if present.
    if tp.status_columns:
        col_name = tp.status_columns[0]
        current = getattr(row, col_name, None)
        if current and isinstance(current, str):
            # Don't change the value — just touch it to generate an UPDATE.
            setattr(row, col_name, current)

    session.flush()


def op_pagination(session: Session, ctx: OperationContext):
    """LIMIT/OFFSET pagination on any table with timestamps."""
    if not ctx.paginable:
        return
    table_name = random.choice(ctx.paginable)
    Model = ctx.get_model(table_name)
    if not Model:
        return

    tp = ctx.profile.tables[table_name]
    order_col = None
    for ts in ["created_at", "placed_at", "logged_at", "recorded_at"]:
        if hasattr(Model, ts):
            order_col = getattr(Model, ts)
            break

    if order_col is None:
        pk = tp.pk_columns[0] if tp.pk_columns else None
        if pk and hasattr(Model, pk):
            order_col = getattr(Model, pk)

    if order_col is None:
        return

    page = random.randint(0, 10)
    page_size = random.choice([10, 20, 25, 50])
    results = session.scalars(
        select(Model).order_by(order_col.desc()).limit(page_size).offset(page * page_size)
    ).all()
    _ = len(results)


def op_aggregation(session: Session, ctx: OperationContext):
    """Aggregation (count/sum/avg) on any table with numeric columns + FK grouping."""
    if not ctx.aggregable:
        return
    table_name = random.choice(ctx.aggregable)
    Model = ctx.get_model(table_name)
    if not Model:
        return

    tp = ctx.profile.tables[table_name]

    # Find a numeric column to aggregate.
    num_col_name = random.choice(tp.numeric_columns)
    if not hasattr(Model, num_col_name):
        return
    num_col = getattr(Model, num_col_name)

    # Find a FK column to group by.
    fk_col_name = None
    for fk in tp.foreign_keys:
        if hasattr(Model, fk.column):
            fk_col_name = fk.column
            break

    if fk_col_name and hasattr(Model, fk_col_name):
        fk_col = getattr(Model, fk_col_name)
        results = session.execute(
            select(fk_col, func.count(), func.sum(num_col), func.avg(num_col))
            .group_by(fk_col)
            .order_by(func.sum(num_col).desc())
            .limit(20)
        ).all()
    else:
        results = session.execute(
            select(func.count(), func.sum(num_col), func.avg(num_col))
        ).all()

    _ = len(results)


def op_exists_filter(session: Session, ctx: OperationContext):
    """EXISTS subquery on any parent table that has FK children."""
    if not ctx.has_rels:
        return
    parent_table = random.choice(ctx.has_rels)
    ParentModel = ctx.get_model(parent_table)
    if not ParentModel:
        return

    children = ctx.children_of[parent_table]
    child_table = random.choice(children)

    # Build: SELECT parent WHERE EXISTS (SELECT 1 FROM child WHERE child.fk = parent.pk)
    fk_col_name = ctx.fk_map.get((child_table, parent_table))
    if not fk_col_name:
        return

    rel_attr = ctx.get_relationship_attr(ParentModel, child_table)
    if not rel_attr:
        return

    rel = getattr(ParentModel, rel_attr)
    results = session.scalars(
        select(ParentModel).where(rel.any()).limit(20)
    ).all()
    _ = len(results)


def op_relationship_filter(session: Session, ctx: OperationContext):
    """Relationship-based JOIN filtering on any FK chain."""
    if not ctx.chains_2:
        return
    chain = random.choice(ctx.chains_2[:10])
    RootModel = ctx.get_model(chain.tables[0])
    ChildModel = ctx.get_model(chain.tables[1])
    if not RootModel or not ChildModel:
        return

    root_rel = ctx.get_relationship_attr(RootModel, chain.tables[1])
    if not root_rel:
        return

    results = session.scalars(
        select(RootModel)
        .join(getattr(RootModel, root_rel))
        .limit(20)
    ).unique().all()
    _ = len(results)


# ── Operation dispatcher ────────────────────────────────────────────────

OPERATIONS = {
    "n_plus_1":       op_n_plus_1,
    "eager_join":     op_eager_join,
    "eager_subquery": op_eager_subquery,
    "eager_selectin": op_eager_selectin,
    "bulk_insert":    op_bulk_insert,
    "orm_update":     op_orm_update,
    "pagination":     op_pagination,
    "aggregation":    op_aggregation,
    "exists_filter":  op_exists_filter,
    "relationship":   op_relationship_filter,
}

# Build cumulative thresholds.
_thresholds: list[tuple[int, str]] = []
_cumulative = 0
for name, weight in MIX.items():
    _cumulative += weight
    _thresholds.append((_cumulative, name))
_total_weight = _cumulative


def pick_operation() -> str:
    r = random.randint(1, _total_weight)
    for threshold, name in _thresholds:
        if r <= threshold:
            return name
    return _thresholds[-1][1]


# ── Worker ───────────────────────────────────────────────────────────────

def worker(ctx: OperationContext):
    while not shutdown.is_set():
        name = pick_operation()
        fn = OPERATIONS[name]
        try:
            with ctx.models.session_factory() as session:
                fn(session, ctx)
                session.commit()
            stats.inc(name)
        except Exception as e:
            stats.inc("errors")
            if not shutdown.is_set():
                log.debug("op %s error: %s", name, e)

        pause = random.uniform(PAUSE_MIN, PAUSE_MAX) / 1000.0
        shutdown.wait(pause)


# ── Wait for data ───────────────────────────────────────────────────────

def wait_for_data(engine):
    log.info("Waiting for database to have data...")
    while not shutdown.is_set():
        try:
            with engine.connect() as conn:
                count = conn.execute(
                    text("SELECT sum(n_live_tup) FROM pg_stat_user_tables")
                ).scalar()
                if count and count > 0:
                    log.info("Data ready (%d total rows across all tables)", count)
                    return
        except Exception:
            pass
        log.info("No data yet, retrying in 5s...")
        shutdown.wait(5)


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    log.info("orm-load: starting templatized ORM load generator")
    log.info("config: concurrency=%d pause=%d-%dms", CONCURRENCY, PAUSE_MIN, PAUSE_MAX)

    engine = create_engine(PG_CONN, pool_size=CONCURRENCY + 2, max_overflow=5, pool_pre_ping=True)

    wait_for_data(engine)

    # Phase 1: Introspect schema.
    log.info("Introspecting database schema...")
    profile = introspect_schema(engine)

    # Phase 2: Reflect ORM models.
    log.info("Reflecting ORM models...")
    models = reflect_database(PG_CONN, pool_size=CONCURRENCY + 2)

    # Phase 3: Build operation context.
    ctx = OperationContext(models, profile)

    log.info("Schema: %d tables, %d relationships, %d FK chains",
             profile.total_tables, len(profile.relationships), len(ctx.chains_2))
    log.info("Queryable: %d tables, insertable: %d, updatable: %d, paginable: %d",
             len(ctx.queryable), len(ctx.insertable), len(ctx.updatable), len(ctx.paginable))
    log.info("Classification: entity=%s transactional=%s append_only=%s lookup=%s hierarchical=%s",
             profile.entity_tables, profile.transactional_tables,
             profile.append_only_tables, profile.lookup_tables, profile.hierarchical_tables)

    # Build schema info for /schema endpoint.
    global _schema_info
    orm_classes = {}
    for tname in sorted(models.table_names):
        cls = models.get_model(tname)
        if cls is None:
            continue
        cols = [c.name for c in cls.__table__.columns]
        rels = []
        try:
            for rname, rel in cls.__mapper__.relationships.items():
                rels.append({"name": rname, "target": rel.mapper.class_.__name__, "direction": str(rel.direction.name)})
        except Exception:
            pass
        orm_classes[tname] = {"columns": cols, "relationships": rels}

    _schema_info = {
        "database": profile.database,
        "total_tables": profile.total_tables,
        "total_rows": profile.total_rows,
        "total_size": profile.total_size_pretty,
        "classification": {
            "entity": profile.entity_tables,
            "transactional": profile.transactional_tables,
            "append_only": profile.append_only_tables,
            "lookup": profile.lookup_tables,
            "hierarchical": profile.hierarchical_tables,
        },
        "relationships": [
            {"parent": r.parent_table, "child": r.child_table, "via": r.fk_column}
            for r in profile.relationships
        ],
        "fk_chains": [
            {"tables": c.tables, "depth": c.depth}
            for c in profile.fk_chains
        ],
        "tables": {
            tname: {
                "role": t.role,
                "row_count": t.row_count,
                "size": t.size_pretty,
                "pk": t.pk_columns,
                "columns": [c.name for c in t.columns],
                "foreign_keys": [{"column": fk.column, "target": f"{fk.target_table}.{fk.target_column}"} for fk in t.foreign_keys],
                "indexes": [{"name": i.name, "columns": i.columns, "unique": i.unique, "type": i.type} for i in t.indexes],
                "timestamp_columns": t.timestamp_columns,
                "numeric_columns": t.numeric_columns,
                "status_columns": t.status_columns,
            }
            for tname, t in profile.tables.items()
        },
        "orm_classes": orm_classes,
        "operations": {
            "queryable": ctx.queryable,
            "insertable": ctx.insertable,
            "updatable": ctx.updatable,
            "paginable": ctx.paginable,
        },
        "mix_weights": MIX,
    }

    # Start healthz.
    healthz = threading.Thread(target=lambda: HTTPServer(("", 9091), HealthHandler).serve_forever(), daemon=True)
    healthz.start()
    log.info("healthz: listening on :9091")

    # Start stats reporter.
    def report_stats():
        while not shutdown.is_set():
            shutdown.wait(STATS_INTERVAL)
            s = stats.snapshot()
            ops = s["ops"]
            parts = " ".join(f"{k}={v}" for k, v in ops.items() if k != "errors")
            log.info("stats: %s errors=%d", parts, ops["errors"])
    threading.Thread(target=report_stats, daemon=True).start()

    # Duration limit.
    if DURATION > 0:
        def timer():
            shutdown.wait(DURATION)
            log.info("Duration limit reached (%ds)", DURATION)
            shutdown.set()
        threading.Thread(target=timer, daemon=True).start()

    # Launch workers.
    threads = []
    for i in range(CONCURRENCY):
        t = threading.Thread(target=worker, args=(ctx,), daemon=True, name=f"worker-{i}")
        t.start()
        threads.append(t)

    log.info("orm-load: %d workers running against %d tables", CONCURRENCY, profile.total_tables)

    try:
        while not shutdown.is_set():
            shutdown.wait(1)
    except KeyboardInterrupt:
        shutdown.set()

    log.info("orm-load: shutting down...")
    for t in threads:
        t.join(timeout=5)

    engine.dispose()
    log.info("orm-load: done. Final stats: %s", json.dumps(stats.snapshot()["ops"]))


if __name__ == "__main__":
    main()
