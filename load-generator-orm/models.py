"""Auto-mapped ORM models for pg-stress.

Instead of 300+ lines of hardcoded model classes, this module uses
SQLAlchemy's automap_base() to reflect ANY PostgreSQL schema at runtime.

All tables, columns, types, and FK relationships are auto-discovered.
The load generator works with any database — not just e-commerce.

Usage:
    from models import reflect_database
    Models, engine = reflect_database("postgresql://user:pass@host/db")

    # Access any table as an ORM class:
    Customers = Models.customers
    Orders = Models.orders

    # Relationships auto-detected from FKs:
    order.customer  # FK: orders.customer_id → customers.id
    customer.orders_collection  # Reverse relationship
"""

import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import MetaData, create_engine
from sqlalchemy.ext.automap import automap_base
from sqlalchemy.orm import sessionmaker

log = logging.getLogger("models")


@dataclass
class DatabaseModels:
    """Container for auto-reflected ORM models and metadata."""
    base: object  # automap Base with .classes
    engine: object
    session_factory: object
    table_names: list[str]
    metadata: MetaData

    def __getattr__(self, name):
        """Access models by table name: Models.customers, Models.orders, etc."""
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self.base.classes[name]
        except KeyError:
            raise AttributeError(f"No table '{name}' found. Available: {self.table_names}")

    def has_table(self, name: str) -> bool:
        return name in self.table_names

    def get_model(self, name: str) -> Optional[object]:
        try:
            return self.base.classes[name]
        except KeyError:
            return None


def reflect_database(
    pg_conn: str,
    pool_size: int = 7,
    max_overflow: int = 5,
) -> DatabaseModels:
    """Connect to a PostgreSQL database and auto-reflect all tables as ORM models.

    Returns a DatabaseModels instance where every table is accessible as
    a mapped class: models.customers, models.orders, etc.

    Relationships are auto-generated from foreign key constraints.
    """
    log.info("Reflecting database: %s", pg_conn.split("@")[-1] if "@" in pg_conn else pg_conn)

    engine = create_engine(
        pg_conn,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,
        echo=False,
    )

    # Reflect all tables from the public schema.
    metadata = MetaData()
    metadata.reflect(engine, schema="public", only=None)

    # Auto-generate ORM classes with relationships from FK constraints.
    Base = automap_base(metadata=metadata)
    Base.prepare(
        engine,
        reflect=True,
    )

    table_names = sorted(metadata.tables.keys())
    # Strip schema prefix if present (e.g., "public.customers" → "customers").
    clean_names = [t.split(".")[-1] for t in table_names]

    session_factory = sessionmaker(bind=engine)

    models = DatabaseModels(
        base=Base,
        engine=engine,
        session_factory=session_factory,
        table_names=clean_names,
        metadata=metadata,
    )

    log.info(
        "Reflected %d tables: %s",
        len(clean_names),
        ", ".join(clean_names[:10]) + ("..." if len(clean_names) > 10 else ""),
    )

    return models
