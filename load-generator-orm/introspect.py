"""Schema introspection engine for pg-stress.

Connects to any PostgreSQL database, discovers the full schema,
builds a relationship graph, classifies tables, and outputs a
schema profile that drives the templatized load generator.

Usage:
    # As module (called by main.py at startup)
    from introspect import introspect_schema
    profile = introspect_schema(engine)

    # As CLI (dump profile to stdout/file)
    python introspect.py                          # Uses PG_CONN env var
    python introspect.py --output profile.yaml
"""

import json
import logging
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import create_engine, inspect, text

log = logging.getLogger("introspect")


# ── Data structures ──────────────────────────────────────────────────────


@dataclass
class ColumnInfo:
    name: str
    type: str
    nullable: bool
    is_pk: bool = False
    is_fk: bool = False
    fk_target: Optional[str] = None  # "table.column"
    has_default: bool = False
    is_serial: bool = False  # nextval sequence


@dataclass
class IndexInfo:
    name: str
    columns: list[str]
    unique: bool
    type: str = "btree"  # btree, gin, gist, hash


@dataclass
class ForeignKey:
    column: str
    target_table: str
    target_column: str


@dataclass
class TableProfile:
    name: str
    row_count: int = 0
    size_bytes: int = 0
    size_pretty: str = ""
    columns: list[ColumnInfo] = field(default_factory=list)
    pk_columns: list[str] = field(default_factory=list)
    foreign_keys: list[ForeignKey] = field(default_factory=list)
    indexes: list[IndexInfo] = field(default_factory=list)
    timestamp_columns: list[str] = field(default_factory=list)
    numeric_columns: list[str] = field(default_factory=list)
    text_columns: list[str] = field(default_factory=list)
    jsonb_columns: list[str] = field(default_factory=list)
    status_columns: list[str] = field(default_factory=list)
    role: str = "unknown"  # entity, transactional, append_only, lookup, hierarchical
    dead_tuples: int = 0
    has_self_fk: bool = False


@dataclass
class Relationship:
    parent_table: str
    child_table: str
    fk_column: str
    parent_column: str = "id"


@dataclass
class FKChain:
    """A chain of FK relationships for N+1 / eager load patterns."""
    tables: list[str]
    depth: int = 0


@dataclass
class SchemaProfile:
    database: str = ""
    total_tables: int = 0
    total_rows: int = 0
    total_size_pretty: str = ""
    tables: dict[str, TableProfile] = field(default_factory=dict)
    relationships: list[Relationship] = field(default_factory=list)
    fk_chains: list[FKChain] = field(default_factory=list)

    # Classified table groups
    entity_tables: list[str] = field(default_factory=list)
    transactional_tables: list[str] = field(default_factory=list)
    append_only_tables: list[str] = field(default_factory=list)
    lookup_tables: list[str] = field(default_factory=list)
    hierarchical_tables: list[str] = field(default_factory=list)

    # For load generator config
    max_ids: dict[str, int] = field(default_factory=dict)


# ── Introspection engine ─────────────────────────────────────────────────


def introspect_schema(engine) -> SchemaProfile:
    """Introspect a live PostgreSQL database and build a complete profile."""
    insp = inspect(engine)
    profile = SchemaProfile()

    with engine.connect() as conn:
        # Database name.
        profile.database = conn.execute(text("SELECT current_database()")).scalar()
        log.info("Introspecting database: %s", profile.database)

        # Total size.
        profile.total_size_pretty = conn.execute(
            text("SELECT pg_size_pretty(pg_database_size(current_database()))")
        ).scalar()

        # ── Discover tables ──────────────────────────────────────
        table_names = insp.get_table_names(schema="public")
        profile.total_tables = len(table_names)
        log.info("Found %d tables", len(table_names))

        # Row counts + sizes (from pg_stat_user_tables for speed).
        stats = {}
        for row in conn.execute(text("""
            SELECT relname, n_live_tup, n_dead_tup,
                   pg_total_relation_size(relid) AS size_bytes,
                   pg_size_pretty(pg_total_relation_size(relid)) AS size_pretty
            FROM pg_stat_user_tables
            WHERE schemaname = 'public'
        """)).mappings():
            stats[row["relname"]] = dict(row)

        # ── Per-table introspection ──────────────────────────────
        for tname in table_names:
            s = stats.get(tname, {})
            tp = TableProfile(
                name=tname,
                row_count=s.get("n_live_tup", 0),
                dead_tuples=s.get("n_dead_tup", 0),
                size_bytes=s.get("size_bytes", 0),
                size_pretty=s.get("size_pretty", "0 bytes"),
            )

            # Columns.
            pk_cols = set()
            pk_constraint = insp.get_pk_constraint(tname, schema="public")
            if pk_constraint:
                pk_cols = set(pk_constraint.get("constrained_columns", []))
            tp.pk_columns = list(pk_cols)

            for col in insp.get_columns(tname, schema="public"):
                col_type = str(col["type"]).lower()
                is_serial = False
                if col.get("default") and "nextval" in str(col.get("default", "")):
                    is_serial = True

                ci = ColumnInfo(
                    name=col["name"],
                    type=col_type,
                    nullable=col.get("nullable", True),
                    is_pk=col["name"] in pk_cols,
                    has_default=col.get("default") is not None,
                    is_serial=is_serial,
                )
                tp.columns.append(ci)

                # Classify column types.
                if "timestamp" in col_type or "date" in col_type:
                    tp.timestamp_columns.append(col["name"])
                if any(t in col_type for t in ["int", "numeric", "decimal", "float", "double", "real"]):
                    tp.numeric_columns.append(col["name"])
                if any(t in col_type for t in ["text", "varchar", "char"]):
                    tp.text_columns.append(col["name"])
                if "jsonb" in col_type or "json" in col_type:
                    tp.jsonb_columns.append(col["name"])
                if col["name"] in ("status", "state", "type", "kind", "role"):
                    tp.status_columns.append(col["name"])

            # Foreign keys.
            for fk in insp.get_foreign_keys(tname, schema="public"):
                for i, col in enumerate(fk["constrained_columns"]):
                    target_col = fk["referred_columns"][i] if i < len(fk["referred_columns"]) else "id"
                    fk_obj = ForeignKey(
                        column=col,
                        target_table=fk["referred_table"],
                        target_column=target_col,
                    )
                    tp.foreign_keys.append(fk_obj)

                    # Mark column as FK.
                    for ci in tp.columns:
                        if ci.name == col:
                            ci.is_fk = True
                            ci.fk_target = f"{fk['referred_table']}.{target_col}"

                    # Self-referencing FK.
                    if fk["referred_table"] == tname:
                        tp.has_self_fk = True

            # Indexes.
            for idx in insp.get_indexes(tname, schema="public"):
                ii = IndexInfo(
                    name=idx["name"],
                    columns=idx.get("column_names", []),
                    unique=idx.get("unique", False),
                )
                # Detect index type from name hints.
                if "_gin" in idx["name"] or "_trgm" in idx["name"]:
                    ii.type = "gin"
                elif "_gist" in idx["name"]:
                    ii.type = "gist"
                tp.indexes.append(ii)

            profile.tables[tname] = tp

        # ── Build relationships ──────────────────────────────────
        for tname, tp in profile.tables.items():
            for fk in tp.foreign_keys:
                if fk.target_table != tname:  # Skip self-refs for relationship list.
                    rel = Relationship(
                        parent_table=fk.target_table,
                        child_table=tname,
                        fk_column=fk.column,
                        parent_column=fk.target_column,
                    )
                    profile.relationships.append(rel)

        # ── Build FK chains (for N+1 / eager load) ──────────────
        # Find all chains of depth 2+ by walking the FK graph.
        children_of = defaultdict(list)
        for rel in profile.relationships:
            children_of[rel.parent_table].append(rel.child_table)

        def walk_chains(table, chain, depth, max_depth=4):
            if depth >= max_depth:
                return
            for child in children_of.get(table, []):
                if child not in chain:  # Avoid cycles.
                    new_chain = chain + [child]
                    if len(new_chain) >= 2:
                        profile.fk_chains.append(FKChain(
                            tables=new_chain,
                            depth=len(new_chain),
                        ))
                    walk_chains(child, new_chain, depth + 1, max_depth)

        for root in profile.tables:
            walk_chains(root, [root], 0)

        # Deduplicate chains and sort by depth.
        seen = set()
        unique_chains = []
        for chain in profile.fk_chains:
            key = tuple(chain.tables)
            if key not in seen:
                seen.add(key)
                unique_chains.append(chain)
        profile.fk_chains = sorted(unique_chains, key=lambda c: -c.depth)

        # ── Classify tables ──────────────────────────────────────
        for tname, tp in profile.tables.items():
            tp.role = _classify_table(tp, children_of)

            if tp.role == "entity":
                profile.entity_tables.append(tname)
            elif tp.role == "transactional":
                profile.transactional_tables.append(tname)
            elif tp.role == "append_only":
                profile.append_only_tables.append(tname)
            elif tp.role == "lookup":
                profile.lookup_tables.append(tname)
            elif tp.role == "hierarchical":
                profile.hierarchical_tables.append(tname)

        # ── Set max IDs for random ID generation ─────────────────
        profile.total_rows = 0
        for tname, tp in profile.tables.items():
            profile.max_ids[tname] = max(tp.row_count, 1)
            profile.total_rows += tp.row_count

        log.info(
            "Introspection complete: %d tables, %d relationships, %d FK chains, %d total rows",
            profile.total_tables, len(profile.relationships),
            len(profile.fk_chains), profile.total_rows,
        )
        log.info(
            "Classification: %d entity, %d transactional, %d append_only, %d lookup, %d hierarchical",
            len(profile.entity_tables), len(profile.transactional_tables),
            len(profile.append_only_tables), len(profile.lookup_tables),
            len(profile.hierarchical_tables),
        )

    return profile


def _classify_table(tp: TableProfile, children_of: dict) -> str:
    """Classify a table's role based on its structure."""
    has_children = len(children_of.get(tp.name, [])) > 0
    has_fks = len(tp.foreign_keys) > 0
    has_timestamps = len(tp.timestamp_columns) > 0
    has_status = len(tp.status_columns) > 0
    has_updated_at = any(c in tp.timestamp_columns for c in ["updated_at", "modified_at", "changed_at"])
    is_small = tp.row_count < 10000
    has_only_created = (
        has_timestamps
        and not has_updated_at
        and any(c in tp.timestamp_columns for c in ["created_at", "logged_at", "recorded_at", "redeemed_at"])
    )

    # Self-referencing = hierarchical.
    if tp.has_self_fk:
        return "hierarchical"

    # Small tables with no FKs to other tables = lookup.
    if is_small and has_children and not has_fks:
        return "lookup"

    # Has only created_at (no updated_at), looks like a log table.
    if has_only_created and not has_status and not has_children:
        return "append_only"

    # Has status + updated_at + FKs = transactional.
    if has_status and has_updated_at:
        return "transactional"

    # Has children, timestamps, no status = entity.
    if has_children and has_timestamps:
        return "entity"

    # Has FKs but no children = junction/detail.
    if has_fks and not has_children:
        if has_updated_at:
            return "transactional"
        return "append_only"

    # Fallback.
    if has_children:
        return "entity"
    if has_timestamps:
        return "transactional"

    return "lookup"


# ── YAML / JSON output ───────────────────────────────────────────────────


def profile_to_dict(profile: SchemaProfile) -> dict:
    """Convert profile to a serializable dict."""
    return {
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
        "tables": {
            name: {
                "rows": tp.row_count,
                "size": tp.size_pretty,
                "role": tp.role,
                "pk": tp.pk_columns,
                "columns": len(tp.columns),
                "foreign_keys": [
                    {"column": fk.column, "references": f"{fk.target_table}.{fk.target_column}"}
                    for fk in tp.foreign_keys
                ],
                "timestamps": tp.timestamp_columns,
                "numeric": tp.numeric_columns,
                "status": tp.status_columns,
                "jsonb": tp.jsonb_columns,
                "indexes": len(tp.indexes),
                "dead_tuples": tp.dead_tuples,
            }
            for name, tp in sorted(profile.tables.items(), key=lambda x: -x[1].row_count)
        },
        "relationships": [
            {"parent": r.parent_table, "child": r.child_table, "via": r.fk_column}
            for r in profile.relationships
        ],
        "fk_chains": [
            {"tables": c.tables, "depth": c.depth}
            for c in profile.fk_chains[:30]  # Top 30 by depth.
        ],
        "max_ids": profile.max_ids,
    }


# ── CLI ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    pg_conn = os.environ.get("PG_CONN", "postgresql://postgres:postgres@localhost:5434/testdb")
    engine = create_engine(pg_conn)

    profile = introspect_schema(engine)
    output = profile_to_dict(profile)

    if "--output" in sys.argv:
        idx = sys.argv.index("--output") + 1
        path = sys.argv[idx]
        with open(path, "w") as f:
            json.dump(output, f, indent=2, default=str)
        print(f"Profile written to {path}")
    else:
        print(json.dumps(output, indent=2, default=str))
