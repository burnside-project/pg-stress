"""Schema graph engine for pg-stress.

Builds a NetworkX directed graph from PostgreSQL schema introspection.
Nodes = tables, edges = FK relationships. Cached in SQLite for instant
startup on subsequent runs.

Used for:
  - Cascading inject (parent → children with ratios)
  - FK chain traversal
  - Topological sort (insert order)
  - Cascade preview in UI

Scales to 5,000+ tables. Graph operations are O(V+E).
Introspection is the bottleneck — that's why we cache.
"""

import hashlib
import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import networkx as nx
import psycopg2
import psycopg2.extras

log = logging.getLogger("schema-graph")

DB_PATH = Path("/data/schema_cache.db")

PG_HOST = os.environ.get("PG_HOST", "postgres")
PG_PORT = int(os.environ.get("PG_PORT", "5432"))
PG_USER = os.environ.get("PG_USER", "postgres")
PG_PASSWORD = os.environ.get("PG_PASSWORD", "postgres")
PG_DATABASE = os.environ.get("PG_DATABASE", "testdb")


# ── SQLite cache ─────────────────────────────────────────────────────────


def _init_cache():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS schema_cache (
            id TEXT PRIMARY KEY,
            database TEXT,
            schema_hash TEXT,
            created_at TEXT,
            table_count INTEGER,
            edge_count INTEGER,
            graph_json TEXT,
            metadata_json TEXT
        );
    """)
    conn.commit()
    return conn


_cache_conn = _init_cache()


# ── PostgreSQL introspection ─────────────────────────────────────────────


def _pg_connect():
    return psycopg2.connect(
        host=PG_HOST, port=PG_PORT, user=PG_USER,
        password=PG_PASSWORD, dbname=PG_DATABASE,
    )


def _query(conn, sql):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]


def _compute_schema_hash(conn) -> str:
    """Hash of table names + column counts for cache invalidation."""
    rows = _query(conn, """
        SELECT table_name, COUNT(*) AS col_count
        FROM information_schema.columns
        WHERE table_schema = 'public'
        GROUP BY table_name
        ORDER BY table_name
    """)
    raw = json.dumps(rows, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _introspect(conn) -> dict:
    """Full schema introspection → dict suitable for NetworkX graph."""
    start = time.time()

    # Tables with row counts and sizes.
    tables = {}
    rows = _query(conn, """
        SELECT c.relname AS name,
               c.reltuples::bigint AS row_count,
               pg_size_pretty(pg_total_relation_size(c.oid)) AS size,
               pg_total_relation_size(c.oid) AS size_bytes
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'r'
        ORDER BY c.reltuples DESC
    """)
    for r in rows:
        tables[r["name"]] = {
            "row_count": r["row_count"],
            "size": r["size"],
            "size_bytes": r["size_bytes"],
        }

    # Columns per table.
    col_rows = _query(conn, """
        SELECT table_name, column_name, data_type, is_nullable,
               column_default, is_identity
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
    """)
    table_columns = {}
    for r in col_rows:
        t = r["table_name"]
        if t not in table_columns:
            table_columns[t] = []
        is_serial = bool(r["column_default"] and "nextval" in str(r["column_default"]))
        is_ident = r["is_identity"] == "YES"
        table_columns[t].append({
            "name": r["column_name"],
            "type": r["data_type"],
            "nullable": r["is_nullable"] == "YES",
            "serial": is_serial or is_ident,
        })

    for t in tables:
        tables[t]["columns"] = table_columns.get(t, [])

    # PKs.
    pk_rows = _query(conn, """
        SELECT tc.table_name, kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
        WHERE tc.constraint_type = 'PRIMARY KEY'
          AND tc.table_schema = 'public'
    """)
    pk_map = {}
    for r in pk_rows:
        pk_map.setdefault(r["table_name"], []).append(r["column_name"])
    for t in tables:
        tables[t]["pk"] = pk_map.get(t, [])

    # Unique constraints.
    unique_rows = _query(conn, """
        SELECT tc.table_name, kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
        WHERE tc.constraint_type = 'UNIQUE'
          AND tc.table_schema = 'public'
    """)
    unique_map = {}
    for r in unique_rows:
        unique_map.setdefault(r["table_name"], set()).add(r["column_name"])
    for t in tables:
        tables[t]["unique_columns"] = list(unique_map.get(t, []))

    # FK relationships.
    fk_rows = _query(conn, """
        SELECT
            tc.table_name AS child_table,
            kcu.column_name AS fk_column,
            ccu.table_name AS parent_table,
            ccu.column_name AS parent_column
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
        JOIN information_schema.constraint_column_usage ccu
          ON tc.constraint_name = ccu.constraint_name
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND tc.table_schema = 'public'
    """)

    edges = []
    for r in fk_rows:
        parent = r["parent_table"]
        child = r["child_table"]
        # Calculate ratio: how many child rows per parent row.
        parent_rows = tables.get(parent, {}).get("row_count", 1)
        child_rows = tables.get(child, {}).get("row_count", 0)
        ratio = round(child_rows / max(parent_rows, 1), 2)
        edges.append({
            "parent": parent,
            "child": child,
            "fk_column": r["fk_column"],
            "parent_column": r["parent_column"],
            "ratio": ratio,
        })

    # Classify tables.
    for t, info in tables.items():
        col_names = [c["name"] for c in info.get("columns", [])]
        has_timestamps = any(c in col_names for c in ["created_at", "updated_at", "placed_at"])
        has_status = any(c in col_names for c in ["status", "state", "type", "kind"])
        children = [e for e in edges if e["parent"] == t]
        parents = [e for e in edges if e["child"] == t]
        self_fk = any(e["parent"] == t and e["child"] == t for e in edges)

        if self_fk:
            info["classification"] = "hierarchical"
        elif children and has_timestamps:
            info["classification"] = "entity"
        elif has_status and has_timestamps:
            info["classification"] = "transactional"
        elif "created_at" in col_names and "updated_at" not in col_names:
            info["classification"] = "append_only"
        elif info["row_count"] < 10000 and not children:
            info["classification"] = "lookup"
        else:
            info["classification"] = "entity"

    elapsed = time.time() - start
    log.info("Introspected %d tables, %d FKs in %.1fs", len(tables), len(edges), elapsed)

    return {
        "database": PG_DATABASE,
        "tables": tables,
        "edges": edges,
        "introspected_at": datetime.now(timezone.utc).isoformat(),
    }


# ── NetworkX graph ───────────────────────────────────────────────────────


class SchemaGraph:
    """NetworkX-backed schema graph with SQLite caching."""

    def __init__(self):
        self.G = nx.DiGraph()
        self.tables = {}
        self.database = ""
        self.loaded = False
        self._schema_hash = ""

    def load(self):
        """Load graph from cache or introspect live database."""
        try:
            conn = _pg_connect()
            current_hash = _compute_schema_hash(conn)

            # Check cache.
            cached = _cache_conn.execute(
                "SELECT graph_json, schema_hash FROM schema_cache WHERE database = ? ORDER BY created_at DESC LIMIT 1",
                (PG_DATABASE,),
            ).fetchone()

            if cached and cached[1] == current_hash:
                log.info("Loading schema graph from cache (hash=%s)", current_hash)
                data = json.loads(cached[0])
                self._build_graph(data)
                conn.close()
                return

            # Introspect.
            log.info("Introspecting schema (hash changed or no cache)")
            data = _introspect(conn)
            self._build_graph(data)
            self._schema_hash = current_hash

            # Save to cache.
            _cache_conn.execute(
                "INSERT OR REPLACE INTO schema_cache (id, database, schema_hash, created_at, table_count, edge_count, graph_json) VALUES (?,?,?,?,?,?,?)",
                (PG_DATABASE, PG_DATABASE, current_hash,
                 datetime.now(timezone.utc).isoformat(),
                 len(data["tables"]), len(data["edges"]),
                 json.dumps(data, default=str)),
            )
            _cache_conn.commit()
            conn.close()

        except Exception as e:
            log.error("Failed to load schema graph: %s", e)

    def _build_graph(self, data: dict):
        self.G = nx.DiGraph()
        self.tables = data.get("tables", {})
        self.database = data.get("database", "")

        for name, info in self.tables.items():
            self.G.add_node(name, **info)

        for edge in data.get("edges", []):
            self.G.add_edge(
                edge["parent"], edge["child"],
                fk_column=edge["fk_column"],
                parent_column=edge["parent_column"],
                ratio=edge["ratio"],
            )

        self.loaded = True
        log.info("Schema graph: %d tables, %d edges", self.G.number_of_nodes(), self.G.number_of_edges())

    def refresh(self):
        """Force re-introspection."""
        try:
            conn = _pg_connect()
            data = _introspect(conn)
            self._build_graph(data)
            current_hash = _compute_schema_hash(conn)
            self._schema_hash = current_hash
            _cache_conn.execute(
                "INSERT OR REPLACE INTO schema_cache (id, database, schema_hash, created_at, table_count, edge_count, graph_json) VALUES (?,?,?,?,?,?,?)",
                (PG_DATABASE, PG_DATABASE, current_hash,
                 datetime.now(timezone.utc).isoformat(),
                 len(data["tables"]), len(data["edges"]),
                 json.dumps(data, default=str)),
            )
            _cache_conn.commit()
            conn.close()
        except Exception as e:
            log.error("Failed to refresh schema graph: %s", e)
        return self.summary()

    # ── Query methods ────────────────────────────────────────────────

    def children(self, table: str) -> list[dict]:
        """Direct child tables via FK."""
        result = []
        for child in self.G.successors(table):
            edge = self.G[table][child]
            result.append({
                "table": child,
                "fk_column": edge.get("fk_column"),
                "ratio": edge.get("ratio", 0),
                "rows": self.tables.get(child, {}).get("row_count", 0),
            })
        return result

    def parents(self, table: str) -> list[dict]:
        """Parent tables this table depends on."""
        result = []
        for parent in self.G.predecessors(table):
            edge = self.G[parent][table]
            result.append({
                "table": parent,
                "fk_column": edge.get("fk_column"),
                "rows": self.tables.get(parent, {}).get("row_count", 0),
            })
        return result

    def cascade_tree(self, table: str) -> dict:
        """Full BFS cascade from a table (all descendants)."""
        tree = nx.bfs_tree(self.G, table)
        result = {}
        for node in tree.nodes():
            result[node] = {
                "classification": self.tables.get(node, {}).get("classification", "?"),
                "rows": self.tables.get(node, {}).get("row_count", 0),
                "depth": nx.shortest_path_length(self.G, table, node) if node != table else 0,
            }
        return result

    def cascade_plan(self, table: str, count: int) -> list[dict]:
        """Plan for cascading inject: parent + all children with proportional counts."""
        plan = [{"table": table, "count": count, "ratio": 1.0, "depth": 0}]

        # BFS through children.
        visited = {table}
        queue = [(table, 0)]

        while queue:
            current, depth = queue.pop(0)
            for child in self.G.successors(current):
                if child in visited:
                    continue
                visited.add(child)
                edge = self.G[current][child]
                ratio = edge.get("ratio", 1.0)
                child_count = max(1, int(count * ratio))
                plan.append({
                    "table": child,
                    "count": child_count,
                    "ratio": ratio,
                    "depth": depth + 1,
                    "fk_column": edge.get("fk_column"),
                    "parent": current,
                })
                queue.append((child, depth + 1))

        return plan

    def insert_order(self) -> list[str]:
        """Topological sort — insert parents before children."""
        try:
            return list(nx.topological_sort(self.G))
        except nx.NetworkXUnfeasible:
            # Cycles (self-referencing FKs) — fall back to node list.
            return list(self.G.nodes())

    def fk_count(self, table: str) -> int:
        """Total FK relationships (in + out) for a table."""
        return self.G.in_degree(table) + self.G.out_degree(table)

    def summary(self) -> dict:
        """Graph summary for API/UI."""
        return {
            "database": self.database,
            "table_count": self.G.number_of_nodes(),
            "edge_count": self.G.number_of_edges(),
            "schema_hash": self._schema_hash,
            "tables": {
                name: {
                    "classification": info.get("classification", "?"),
                    "row_count": info.get("row_count", 0),
                    "size": info.get("size", "?"),
                    "pk": info.get("pk", []),
                    "unique_columns": info.get("unique_columns", []),
                    "fk_in": self.G.in_degree(name),
                    "fk_out": self.G.out_degree(name),
                    "children": [c for c in self.G.successors(name)],
                    "parents": [p for p in self.G.predecessors(name)],
                }
                for name, info in self.tables.items()
            },
        }


# Singleton.
graph = SchemaGraph()
