"""ORM-based load generator for pg-collector SQL fingerprint validation.

Exercises SQLAlchemy ORM patterns that produce distinct pg_stat_statements
fingerprints compared to the raw-SQL Go load generator:

  - N+1 selects (lazy relationship loading)
  - Eager loading (joinedload / subqueryload)
  - Subquery-based IN (selectinload prefetch)
  - Bulk INSERT with RETURNING
  - ORM .save() / flush patterns (implicit UPDATE with WHERE pk = ?)
  - Hybrid property / column_property queries
  - Pagination via .limit().offset()
  - Aggregation via ORM func()
  - Exists / has subqueries
  - Relationship-based filtering

All operations target the same 18-table e-commerce schema as the Go load generator.
"""

import json
import logging
import os
import random
import signal
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from http.server import HTTPServer, BaseHTTPRequestHandler

from sqlalchemy import create_engine, func, select, update, delete, and_, exists, text
from sqlalchemy.orm import Session, sessionmaker, joinedload, subqueryload, selectinload

from models import (
    Address, AuditLog, CartItem, Category, CouponRedemption, Customer,
    Inventory, Order, OrderItem, Payment, PriceHistory, Product,
    ProductVariant, Promotion, Review, SearchLog, Session as SessionModel,
    Shipment,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("orm-load")

# ── Table size constants (match Go load generator) ───────────────────────

MAX_CUSTOMERS = 1_000_000
MAX_PRODUCTS = 100_000
MAX_VARIANTS = 300_000
MAX_ORDERS = 5_000_000
MAX_SESSIONS = 100_000
MAX_PROMOS = 1_000
MAX_ADDRESSES = 2_000_000
MAX_CATEGORIES = 500


# ── Configuration ────────────────────────────────────────────────────────


def env_int(key: str, default: int) -> int:
    v = os.environ.get(key)
    return int(v) if v else default


def env_bool(key: str, default: bool) -> bool:
    v = os.environ.get(key, "").lower()
    if v in ("1", "true", "yes"):
        return True
    if v in ("0", "false", "no"):
        return False
    return default


PG_CONN = os.environ.get("PG_CONN", "postgresql://postgres:postgres@localhost:5432/testdb")
CONCURRENCY = env_int("ORM_CONCURRENCY", 5)
DURATION = env_int("ORM_DURATION", 0)  # 0 = run forever
STATS_INTERVAL = env_int("ORM_STATS_INTERVAL", 30)
PAUSE_MIN = env_int("ORM_PAUSE_MIN", 10)
PAUSE_MAX = env_int("ORM_PAUSE_MAX", 50)

# ORM pattern mix weights (should sum to 100).
MIX_N_PLUS_1 = env_int("ORM_MIX_N_PLUS_1", 15)
MIX_EAGER_JOIN = env_int("ORM_MIX_EAGER_JOIN", 15)
MIX_EAGER_SUBQUERY = env_int("ORM_MIX_EAGER_SUBQUERY", 10)
MIX_EAGER_SELECTIN = env_int("ORM_MIX_EAGER_SELECTIN", 10)
MIX_BULK_INSERT = env_int("ORM_MIX_BULK_INSERT", 5)
MIX_ORM_UPDATE = env_int("ORM_MIX_ORM_UPDATE", 10)
MIX_PAGINATION = env_int("ORM_MIX_PAGINATION", 10)
MIX_AGGREGATION = env_int("ORM_MIX_AGGREGATION", 10)
MIX_EXISTS_FILTER = env_int("ORM_MIX_EXISTS_FILTER", 10)
MIX_RELATIONSHIP = env_int("ORM_MIX_RELATIONSHIP", 5)

# ── Stats ────────────────────────────────────────────────────────────────


class Stats:
    def __init__(self):
        self._lock = threading.Lock()
        self.counters = {
            "n_plus_1": 0,
            "eager_join": 0,
            "eager_subquery": 0,
            "eager_selectin": 0,
            "bulk_insert": 0,
            "orm_update": 0,
            "pagination": 0,
            "aggregation": 0,
            "exists_filter": 0,
            "relationship": 0,
            "errors": 0,
        }
        self.start_time = time.time()

    def inc(self, key: str):
        with self._lock:
            self.counters[key] = self.counters.get(key, 0) + 1

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "status": "running",
                "uptime_s": int(time.time() - self.start_time),
                "ops": dict(self.counters),
            }


stats = Stats()

# ── Shutdown signal ──────────────────────────────────────────────────────

shutdown = threading.Event()


def handle_signal(sig, frame):
    log.info("Received signal %s, shutting down...", sig)
    shutdown.set()


signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)


# ── Healthz HTTP server ─────────────────────────────────────────────────


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(stats.snapshot()).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt, *args):
        pass  # Suppress request logging.


def serve_healthz():
    server = HTTPServer(("", 9091), HealthHandler)
    server.serve_forever()


# ── ORM Operations ───────────────────────────────────────────────────────
#
# Each function exercises a distinct ORM pattern that produces different
# pg_stat_statements fingerprints than raw SQL.


def op_n_plus_1(session: Session):
    """N+1 pattern: load products, then lazily access each product's variants.

    ORM produces: 1 SELECT for products + N SELECTs for product_variants.
    This is the classic ORM anti-pattern that pg-collector should identify
    as many similar queries with different parameter values.
    """
    cat_id = random.randint(1, MAX_CATEGORIES)
    products = session.scalars(
        select(Product)
        .where(Product.category_id == cat_id, Product.status == "active")
        .limit(10)
    ).all()

    # Trigger lazy loads — each access issues a separate SELECT.
    for p in products:
        _ = p.variants  # N separate SELECTs for product_variants
        for v in p.variants:
            _ = v.inventory  # N more SELECTs for inventory


def op_eager_joinedload(session: Session):
    """Eager loading via JOIN: single query with LEFT OUTER JOINs.

    ORM produces a single large SELECT with multiple JOINs — very different
    fingerprint from the N+1 pattern above, even for the same data.
    """
    customer_id = random.randint(1, MAX_CUSTOMERS)
    customer = session.scalars(
        select(Customer)
        .options(
            joinedload(Customer.orders).joinedload(Order.items).joinedload(OrderItem.variant),
            joinedload(Customer.addresses),
        )
        .where(Customer.id == customer_id)
    ).unique().first()

    if customer:
        # Data already loaded — no additional queries.
        _ = [(o.status, len(o.items)) for o in customer.orders[:5]]


def op_eager_subqueryload(session: Session):
    """Eager loading via subquery: separate SELECT with IN (subquery).

    ORM produces: 1 SELECT for orders + 1 SELECT for items WHERE order_id IN (SELECT ...).
    This is a distinct fingerprint from joinedload.
    """
    customer_id = random.randint(1, MAX_CUSTOMERS)
    orders = session.scalars(
        select(Order)
        .options(
            subqueryload(Order.items),
            subqueryload(Order.payments),
        )
        .where(Order.customer_id == customer_id)
        .order_by(Order.placed_at.desc())
        .limit(10)
    ).all()

    for o in orders:
        _ = sum(item.line_total for item in o.items)


def op_eager_selectinload(session: Session):
    """Eager loading via SELECT IN: separate SELECT with IN (literal list).

    ORM produces: 1 SELECT for products + 1 SELECT WHERE product_id IN ($1, $2, ..., $N).
    The IN-list size varies, creating multiple pg_stat_statements entries.
    """
    cat_id = random.randint(1, MAX_CATEGORIES)
    products = session.scalars(
        select(Product)
        .options(
            selectinload(Product.variants).selectinload(ProductVariant.inventory),
            selectinload(Product.reviews),
        )
        .where(Product.category_id == cat_id, Product.status == "active")
        .limit(20)
    ).all()

    for p in products:
        _ = len(p.reviews)
        for v in p.variants:
            _ = v.inventory.qty_available if v.inventory else 0


def op_bulk_insert(session: Session):
    """Bulk INSERT with ORM: add_all() + flush().

    ORM produces INSERT ... VALUES (...) RETURNING id — one per object or
    batched depending on dialect. Distinct from raw INSERT ... VALUES.
    """
    session_id = random.randint(1, MAX_SESSIONS)
    variant_ids = [random.randint(1, MAX_VARIANTS) for _ in range(random.randint(3, 10))]

    items = [
        CartItem(
            session_id=session_id,
            variant_id=vid,
            qty=random.randint(1, 5),
        )
        for vid in variant_ids
    ]
    session.add_all(items)
    session.flush()

    # Also test bulk search log inserts.
    queries = ["laptop", "shoes", "headphones", "keyboard", "coffee maker",
               "monitor", "backpack", "phone case", "webcam", "standing desk"]
    logs = [
        SearchLog(
            session_id=session_id,
            query=random.choice(queries),
            results_count=random.randint(0, 200),
        )
        for _ in range(random.randint(5, 15))
    ]
    session.add_all(logs)
    session.flush()


def op_orm_update(session: Session):
    """ORM attribute-set + commit: UPDATE with implicit WHERE pk = ?.

    ORM produces: SELECT ... WHERE id = $1 (to load), then
    UPDATE ... SET col = $1 WHERE id = $2 (on flush).
    This is the classic ORM "load-modify-save" pattern.
    """
    choice = random.randint(0, 2)

    if choice == 0:
        # Update a customer's last_login.
        customer = session.get(Customer, random.randint(1, MAX_CUSTOMERS))
        if customer:
            customer.last_login = datetime.now(timezone.utc)
            session.flush()

    elif choice == 1:
        # Update inventory quantities via ORM (not raw UPDATE).
        inv = session.get(Inventory, random.randint(1, MAX_VARIANTS))
        if inv:
            inv.qty_available = max(0, inv.qty_available + random.randint(-10, 50))
            inv.updated_at = datetime.now(timezone.utc)
            session.flush()

    else:
        # Update order status via ORM.
        order_id = random.randint(1, MAX_ORDERS)
        order = session.get(Order, order_id)
        if order and order.status == "pending":
            order.status = "processing"
            order.updated_at = datetime.now(timezone.utc)
            session.flush()


def op_pagination(session: Session):
    """Paginated queries: LIMIT + OFFSET via ORM.

    ORM produces SELECT ... LIMIT $1 OFFSET $2. Different from raw SQL
    because the column list and JOIN structure come from ORM model introspection.
    """
    choice = random.randint(0, 2)

    if choice == 0:
        # Paginate products in a category.
        cat_id = random.randint(1, MAX_CATEGORIES)
        page = random.randint(0, 10)
        page_size = 24
        products = session.scalars(
            select(Product)
            .where(Product.category_id == cat_id, Product.status == "active")
            .order_by(Product.created_at.desc())
            .limit(page_size)
            .offset(page * page_size)
        ).all()
        _ = len(products)

    elif choice == 1:
        # Paginate customer orders.
        customer_id = random.randint(1, MAX_CUSTOMERS)
        page = random.randint(0, 5)
        orders = session.scalars(
            select(Order)
            .where(Order.customer_id == customer_id)
            .order_by(Order.placed_at.desc())
            .limit(20)
            .offset(page * 20)
        ).all()
        _ = len(orders)

    else:
        # Paginate reviews for a product.
        product_id = random.randint(1, MAX_PRODUCTS)
        reviews = session.scalars(
            select(Review)
            .where(Review.product_id == product_id)
            .order_by(Review.created_at.desc())
            .limit(10)
            .offset(random.randint(0, 5) * 10)
        ).all()
        _ = len(reviews)


def op_aggregation(session: Session):
    """ORM-style aggregation using func().

    Produces SELECT with func.count(), func.sum(), func.avg() —
    similar intent to raw SQL but wrapped in ORM column expressions.
    """
    choice = random.randint(0, 3)

    if choice == 0:
        # Customer order stats via ORM.
        customer_id = random.randint(1, MAX_CUSTOMERS)
        result = session.execute(
            select(
                func.count(Order.id),
                func.coalesce(func.sum(Order.total), 0),
                func.min(Order.placed_at),
                func.max(Order.placed_at),
            ).where(Order.customer_id == customer_id)
        ).one()
        _ = result

    elif choice == 1:
        # Category product counts.
        results = session.execute(
            select(
                Category.id,
                Category.name,
                func.count(Product.id).label("product_count"),
            )
            .join(Product, Product.category_id == Category.id, isouter=True)
            .where(Category.parent_id.is_(None))
            .group_by(Category.id, Category.name)
            .order_by(func.count(Product.id).desc())
            .limit(25)
        ).all()
        _ = len(results)

    elif choice == 2:
        # Average review rating per product (top rated).
        results = session.execute(
            select(
                Product.id,
                Product.name,
                func.avg(Review.rating).label("avg_rating"),
                func.count(Review.id).label("review_count"),
            )
            .join(Review, Review.product_id == Product.id)
            .group_by(Product.id, Product.name)
            .having(func.count(Review.id) >= 5)
            .order_by(func.avg(Review.rating).desc())
            .limit(20)
        ).all()
        _ = len(results)

    else:
        # Revenue by day (last 7 days).
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        results = session.execute(
            select(
                func.date_trunc("day", Order.placed_at).label("day"),
                func.count(Order.id),
                func.sum(Order.total),
            )
            .where(Order.placed_at >= cutoff)
            .group_by(text("1"))
            .order_by(text("1"))
        ).all()
        _ = len(results)


def op_exists_filter(session: Session):
    """EXISTS / has() subquery filters.

    ORM produces correlated subqueries: WHERE EXISTS (SELECT 1 FROM ...).
    These are structurally different from JOINs and produce unique fingerprints.
    """
    choice = random.randint(0, 2)

    if choice == 0:
        # Products that have at least one review with rating >= 4.
        products = session.scalars(
            select(Product)
            .where(
                Product.reviews.any(Review.rating >= 4),
                Product.status == "active",
            )
            .limit(20)
        ).all()
        _ = len(products)

    elif choice == 1:
        # Customers who have placed an order in the last 30 days.
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        customers = session.scalars(
            select(Customer)
            .where(Customer.orders.any(Order.placed_at >= cutoff))
            .limit(20)
        ).all()
        _ = len(customers)

    else:
        # Orders that do NOT have a shipment yet.
        orders = session.scalars(
            select(Order)
            .where(
                ~Order.shipments.any(),
                Order.status == "processing",
            )
            .limit(20)
        ).all()
        _ = len(orders)


def op_relationship_filter(session: Session):
    """Relationship-based filtering and traversal.

    Exercises ORM relationship joins that produce different fingerprints from
    explicit JOIN clauses: session.query().join(Relationship).filter().
    """
    choice = random.randint(0, 2)

    if choice == 0:
        # Find low-stock variants via relationship chain.
        results = session.scalars(
            select(ProductVariant)
            .join(ProductVariant.inventory)
            .join(ProductVariant.product)
            .where(
                Inventory.qty_available < 10,
                Product.status == "active",
            )
            .order_by(Inventory.qty_available.asc())
            .limit(20)
        ).all()
        _ = len(results)

    elif choice == 1:
        # Customer's cart with product details via relationship chain.
        session_id = random.randint(1, MAX_SESSIONS)
        cart = session.scalars(
            select(CartItem)
            .options(
                joinedload(CartItem.variant).joinedload(ProductVariant.product),
                joinedload(CartItem.variant).joinedload(ProductVariant.inventory),
            )
            .where(CartItem.session_id == session_id)
        ).unique().all()
        for ci in cart:
            _ = ci.variant.product.name if ci.variant and ci.variant.product else None

    else:
        # Orders with their full payment + shipment details.
        customer_id = random.randint(1, MAX_CUSTOMERS)
        orders = session.scalars(
            select(Order)
            .options(
                joinedload(Order.payments),
                joinedload(Order.shipments),
                joinedload(Order.customer),
            )
            .where(Order.customer_id == customer_id)
            .order_by(Order.placed_at.desc())
            .limit(5)
        ).unique().all()
        for o in orders:
            _ = (o.customer.name, len(o.payments), len(o.shipments))


# ── Operation dispatcher ────────────────────────────────────────────────

OPERATIONS = [
    ("n_plus_1", MIX_N_PLUS_1, op_n_plus_1),
    ("eager_join", MIX_EAGER_JOIN, op_eager_joinedload),
    ("eager_subquery", MIX_EAGER_SUBQUERY, op_eager_subqueryload),
    ("eager_selectin", MIX_EAGER_SELECTIN, op_eager_selectinload),
    ("bulk_insert", MIX_BULK_INSERT, op_bulk_insert),
    ("orm_update", MIX_ORM_UPDATE, op_orm_update),
    ("pagination", MIX_PAGINATION, op_pagination),
    ("aggregation", MIX_AGGREGATION, op_aggregation),
    ("exists_filter", MIX_EXISTS_FILTER, op_exists_filter),
    ("relationship", MIX_RELATIONSHIP, op_relationship_filter),
]

# Build cumulative thresholds.
_thresholds: list[tuple[int, str, callable]] = []
_cumulative = 0
for name, weight, fn in OPERATIONS:
    _cumulative += weight
    _thresholds.append((_cumulative, name, fn))
_total_weight = _cumulative


def pick_operation() -> tuple[str, callable]:
    r = random.randint(1, _total_weight)
    for threshold, name, fn in _thresholds:
        if r <= threshold:
            return name, fn
    return _thresholds[-1][1], _thresholds[-1][2]


# ── Worker ───────────────────────────────────────────────────────────────


def worker(session_factory: sessionmaker):
    while not shutdown.is_set():
        name, fn = pick_operation()
        try:
            with session_factory() as session:
                fn(session)
                session.commit()
            stats.inc(name)
        except Exception as e:
            stats.inc("errors")
            if not shutdown.is_set():
                log.debug("op %s error: %s", name, e)

        # Small random pause between operations.
        pause = random.uniform(PAUSE_MIN, PAUSE_MAX) / 1000.0  # ms to seconds
        shutdown.wait(pause)


# ── Wait for data ───────────────────────────────────────────────────────


def wait_for_data(engine):
    log.info("Waiting for seeded data...")
    while not shutdown.is_set():
        try:
            with engine.connect() as conn:
                count = conn.execute(text("SELECT count(*) FROM customers")).scalar()
                if count and count > 0:
                    log.info("Data ready (customers=%d)", count)
                    return
        except Exception:
            pass
        log.info("Data not ready, retrying in 5s...")
        shutdown.wait(5)


# ── Main ─────────────────────────────────────────────────────────────────


def main():
    log.info("orm-load: starting SQLAlchemy ORM load generator")
    log.info("config: concurrency=%d pause=%d-%dms", CONCURRENCY, PAUSE_MIN, PAUSE_MAX)
    log.info("mix: n+1=%d join=%d subq=%d selectin=%d bulk=%d update=%d page=%d agg=%d exists=%d rel=%d",
             MIX_N_PLUS_1, MIX_EAGER_JOIN, MIX_EAGER_SUBQUERY, MIX_EAGER_SELECTIN,
             MIX_BULK_INSERT, MIX_ORM_UPDATE, MIX_PAGINATION, MIX_AGGREGATION,
             MIX_EXISTS_FILTER, MIX_RELATIONSHIP)

    engine = create_engine(
        PG_CONN,
        pool_size=CONCURRENCY + 2,
        max_overflow=5,
        pool_pre_ping=True,
        echo=False,
    )

    wait_for_data(engine)

    session_factory = sessionmaker(bind=engine)

    # Start healthz server.
    healthz_thread = threading.Thread(target=serve_healthz, daemon=True)
    healthz_thread.start()
    log.info("healthz: listening on :9091")

    # Start stats reporter.
    def report_stats():
        while not shutdown.is_set():
            shutdown.wait(STATS_INTERVAL)
            s = stats.snapshot()
            ops = s["ops"]
            log.info(
                "stats: n+1=%d join=%d subq=%d selectin=%d bulk=%d update=%d "
                "page=%d agg=%d exists=%d rel=%d errors=%d",
                ops["n_plus_1"], ops["eager_join"], ops["eager_subquery"],
                ops["eager_selectin"], ops["bulk_insert"], ops["orm_update"],
                ops["pagination"], ops["aggregation"], ops["exists_filter"],
                ops["relationship"], ops["errors"],
            )

    stats_thread = threading.Thread(target=report_stats, daemon=True)
    stats_thread.start()

    # Duration limit.
    if DURATION > 0:
        def duration_timer():
            shutdown.wait(DURATION)
            log.info("Duration limit reached (%ds), shutting down...", DURATION)
            shutdown.set()
        threading.Thread(target=duration_timer, daemon=True).start()

    # Launch workers.
    threads = []
    for i in range(CONCURRENCY):
        t = threading.Thread(target=worker, args=(session_factory,), daemon=True, name=f"worker-{i}")
        t.start()
        threads.append(t)

    log.info("orm-load: %d workers running", CONCURRENCY)

    # Wait for shutdown.
    try:
        while not shutdown.is_set():
            shutdown.wait(1)
    except KeyboardInterrupt:
        shutdown.set()

    log.info("orm-load: waiting for workers to finish...")
    for t in threads:
        t.join(timeout=5)

    engine.dispose()
    log.info("orm-load: shutdown complete")
    final = stats.snapshot()
    log.info("final stats: %s", json.dumps(final["ops"]))


if __name__ == "__main__":
    main()
