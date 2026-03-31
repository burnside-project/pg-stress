// Package main implements an e-commerce OLTP load generator for PostgreSQL stress testing.
//
// It simulates realistic medium-sized e-commerce traffic against a PostgreSQL database:
//   - Browse: category listings, product views, search, session touches
//   - Cart: add/update/remove items, view cart (high churn -> vacuum pressure)
//   - Checkout: multi-statement transactions with inventory locks (contention)
//   - Order management: status updates, payments, shipments
//   - Background: cart/session expiry, search/audit logging, reviews
//   - Reporting: sales aggregates, top products, customer LTV
//
// Chaos patterns exercise edge cases: abandoned checkouts (idle-in-transaction),
// flash sales (deadlock potential), bulk price updates, cart cleanup storms.
//
// All parameters are configurable via environment variables (see Config struct).
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"math/rand/v2"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Config holds all configurable parameters, loaded from environment variables.
type Config struct {
	ConnStr  string
	Duration time.Duration

	// Traffic mix weights (should sum to 100).
	MixBrowse     int
	MixCart        int
	MixCheckout   int
	MixOrder      int
	MixBackground int
	MixReporting  int

	// Burst intensity.
	Intensities []Intensity

	// Chaos.
	ChaosEnabled     bool
	ChaosProbability int // 0-100

	// Pause between bursts (seconds).
	PauseMin int
	PauseMax int

	// Pool.
	MaxPool int32

	// Stats reporting interval.
	StatsInterval time.Duration
}

// Intensity levels for load bursts.
type Intensity struct {
	Name        string
	Connections int
	Duration    time.Duration
	Weight      int
}

// Stats tracks operation counts by category.
type Stats struct {
	browse     atomic.Int64
	cart       atomic.Int64
	checkout   atomic.Int64
	orderMgmt  atomic.Int64
	background atomic.Int64
	reporting  atomic.Int64
	chaos      atomic.Int64
	errors     atomic.Int64
	bursts     atomic.Int64
	startTime  time.Time
}

// Table size limits for random ID generation.
// Configurable via environment variables for BYOD databases with different row counts.
var (
	maxCustomers  = int64(envInt("LOADGEN_MAX_CUSTOMERS", 1_000_000))
	maxProducts   = int64(envInt("LOADGEN_MAX_PRODUCTS", 100_000))
	maxVariants   = int64(envInt("LOADGEN_MAX_VARIANTS", 300_000))
	maxOrders     = int64(envInt("LOADGEN_MAX_ORDERS", 5_000_000))
	maxSessions   = int64(envInt("LOADGEN_MAX_SESSIONS", 100_000))
	maxPromos     = int64(envInt("LOADGEN_MAX_PROMOS", 1_000))
	maxAddresses  = int64(envInt("LOADGEN_MAX_ADDRESSES", 2_000_000))
	maxCategories = int64(envInt("LOADGEN_MAX_CATEGORIES", 500))
)

func loadConfig() Config {
	cfg := Config{
		ConnStr:          os.Getenv("PG_CONN"),
		MixBrowse:        envInt("LOADGEN_MIX_BROWSE", 50),
		MixCart:          envInt("LOADGEN_MIX_CART", 20),
		MixCheckout:      envInt("LOADGEN_MIX_CHECKOUT", 5),
		MixOrder:         envInt("LOADGEN_MIX_ORDER", 10),
		MixBackground:    envInt("LOADGEN_MIX_BACKGROUND", 10),
		MixReporting:     envInt("LOADGEN_MIX_REPORTING", 5),
		ChaosEnabled:     envBool("LOADGEN_CHAOS_ENABLED", true),
		ChaosProbability: envInt("LOADGEN_CHAOS_PROBABILITY", 25),
		PauseMin:         envInt("LOADGEN_PAUSE_MIN", 20),
		PauseMax:         envInt("LOADGEN_PAUSE_MAX", 90),
		MaxPool:          int32(envInt("LOADGEN_MAX_POOL", 60)),
		StatsInterval:    envDuration("LOADGEN_STATS_INTERVAL", 30*time.Second),
		Intensities: []Intensity{
			{"low", envInt("LOADGEN_BURST_LOW_CONNS", 5), envDuration("LOADGEN_BURST_LOW_DURATION", 10*time.Second), envInt("LOADGEN_BURST_LOW_WEIGHT", 50)},
			{"medium", envInt("LOADGEN_BURST_MED_CONNS", 20), envDuration("LOADGEN_BURST_MED_DURATION", 30*time.Second), envInt("LOADGEN_BURST_MED_WEIGHT", 35)},
			{"heavy", envInt("LOADGEN_BURST_HEAVY_CONNS", 50), envDuration("LOADGEN_BURST_HEAVY_DURATION", 60*time.Second), envInt("LOADGEN_BURST_HEAVY_WEIGHT", 15)},
		},
	}

	if d := os.Getenv("LOADGEN_DURATION"); d != "" {
		dur, err := time.ParseDuration(d)
		if err != nil {
			log.Fatalf("invalid LOADGEN_DURATION %q: %v", d, err)
		}
		cfg.Duration = dur
	}

	if cfg.ConnStr == "" {
		log.Fatal("PG_CONN environment variable is required")
	}

	return cfg
}

func envInt(key string, def int) int {
	if v := os.Getenv(key); v != "" {
		n, err := strconv.Atoi(v)
		if err != nil {
			log.Fatalf("invalid %s=%q: %v", key, v, err)
		}
		return n
	}
	return def
}

func envBool(key string, def bool) bool {
	if v := os.Getenv(key); v != "" {
		b, err := strconv.ParseBool(v)
		if err != nil {
			log.Fatalf("invalid %s=%q: %v", key, v, err)
		}
		return b
	}
	return def
}

func envDuration(key string, def time.Duration) time.Duration {
	if v := os.Getenv(key); v != "" {
		d, err := time.ParseDuration(v)
		if err != nil {
			log.Fatalf("invalid %s=%q: %v", key, v, err)
		}
		return d
	}
	return def
}

func main() {
	cfg := loadConfig()

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	// Apply duration limit.
	if cfg.Duration > 0 {
		ctx, cancel = context.WithTimeout(ctx, cfg.Duration)
		defer cancel()
		log.Printf("ecommerce-load: will run for %s", cfg.Duration)
	}

	poolCfg, err := pgxpool.ParseConfig(cfg.ConnStr)
	if err != nil {
		log.Fatalf("parse connection string: %v", err)
	}
	poolCfg.MaxConns = cfg.MaxPool
	poolCfg.MinConns = 2

	pool, err := pgxpool.NewWithConfig(ctx, poolCfg)
	if err != nil {
		log.Fatalf("create connection pool: %v", err)
	}
	defer pool.Close()

	// Wait for seeded data before starting load.
	waitForData(ctx, pool)

	log.Println("ecommerce-load: starting e-commerce OLTP load generator")
	log.Printf("config: mix=browse:%d/cart:%d/checkout:%d/order:%d/bg:%d/report:%d chaos=%v(%d%%) pause=%d-%ds",
		cfg.MixBrowse, cfg.MixCart, cfg.MixCheckout, cfg.MixOrder, cfg.MixBackground, cfg.MixReporting,
		cfg.ChaosEnabled, cfg.ChaosProbability, cfg.PauseMin, cfg.PauseMax)

	stats := &Stats{startTime: time.Now()}

	// Build cumulative mix thresholds.
	mixThresholds := buildMixThresholds(cfg)

	// Start /healthz HTTP server.
	go serveHealthz(stats, &cfg)

	// Stats reporter.
	go func() {
		ticker := time.NewTicker(cfg.StatsInterval)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				log.Printf("stats: browse=%d cart=%d checkout=%d order=%d bg=%d report=%d chaos=%d errors=%d bursts=%d",
					stats.browse.Load(), stats.cart.Load(), stats.checkout.Load(),
					stats.orderMgmt.Load(), stats.background.Load(), stats.reporting.Load(),
					stats.chaos.Load(), stats.errors.Load(), stats.bursts.Load())
			}
		}
	}()

	// Main burst loop.
	for {
		select {
		case <-ctx.Done():
			log.Println("ecommerce-load: shutting down gracefully")
			return
		default:
		}

		intensity := pickIntensity(cfg.Intensities)
		stats.bursts.Add(1)
		log.Printf("burst: intensity=%s connections=%d duration=%s",
			intensity.Name, intensity.Connections, intensity.Duration)

		runBurst(ctx, pool, intensity, stats, mixThresholds)

		// Chaos pattern between bursts.
		if cfg.ChaosEnabled && cfg.ChaosProbability > 0 && rand.IntN(100) < cfg.ChaosProbability {
			runChaos(ctx, pool, stats)
		}

		// Random pause.
		pauseRange := cfg.PauseMax - cfg.PauseMin
		if pauseRange < 1 {
			pauseRange = 1
		}
		pause := time.Duration(cfg.PauseMin+rand.IntN(pauseRange+1)) * time.Second
		log.Printf("pause: %s until next burst", pause)
		select {
		case <-ctx.Done():
			return
		case <-time.After(pause):
		}
	}
}

func waitForData(ctx context.Context, pool *pgxpool.Pool) {
	log.Println("ecommerce-load: waiting for seeded data...")
	for {
		select {
		case <-ctx.Done():
			log.Fatal("ecommerce-load: context cancelled while waiting for data")
		default:
		}

		var count int64
		err := pool.QueryRow(ctx, `SELECT count(*) FROM customers LIMIT 1`).Scan(&count)
		if err == nil && count > 0 {
			log.Printf("ecommerce-load: data ready (customers=%d)", count)
			return
		}

		log.Println("ecommerce-load: data not ready, retrying in 5s...")
		select {
		case <-ctx.Done():
			log.Fatal("ecommerce-load: context cancelled while waiting for data")
		case <-time.After(5 * time.Second):
		}
	}
}

// MixThresholds holds cumulative thresholds for traffic mix selection.
type MixThresholds struct {
	browse     int
	cart       int
	checkout   int
	order      int
	background int
	total      int
}

func buildMixThresholds(cfg Config) MixThresholds {
	total := cfg.MixBrowse + cfg.MixCart + cfg.MixCheckout + cfg.MixOrder + cfg.MixBackground + cfg.MixReporting
	if total == 0 {
		total = 100
	}
	return MixThresholds{
		browse:     cfg.MixBrowse,
		cart:       cfg.MixBrowse + cfg.MixCart,
		checkout:   cfg.MixBrowse + cfg.MixCart + cfg.MixCheckout,
		order:      cfg.MixBrowse + cfg.MixCart + cfg.MixCheckout + cfg.MixOrder,
		background: cfg.MixBrowse + cfg.MixCart + cfg.MixCheckout + cfg.MixOrder + cfg.MixBackground,
		total:      total,
	}
}

func pickIntensity(intensities []Intensity) Intensity {
	total := 0
	for _, i := range intensities {
		total += i.Weight
	}
	r := rand.IntN(total)
	for _, i := range intensities {
		r -= i.Weight
		if r < 0 {
			return i
		}
	}
	return intensities[0]
}

func runBurst(ctx context.Context, pool *pgxpool.Pool, intensity Intensity, stats *Stats, mix MixThresholds) {
	burstCtx, cancel := context.WithTimeout(ctx, intensity.Duration)
	defer cancel()

	var wg sync.WaitGroup
	for range intensity.Connections {
		wg.Add(1)
		go func() {
			defer wg.Done()
			worker(burstCtx, pool, stats, mix)
		}()
	}
	wg.Wait()
}

func worker(ctx context.Context, pool *pgxpool.Pool, stats *Stats, mix MixThresholds) {
	for {
		select {
		case <-ctx.Done():
			return
		default:
		}

		r := rand.IntN(mix.total)
		var err error
		switch {
		case r < mix.browse:
			err = doBrowse(ctx, pool)
			if err == nil {
				stats.browse.Add(1)
			}
		case r < mix.cart:
			err = doCart(ctx, pool)
			if err == nil {
				stats.cart.Add(1)
			}
		case r < mix.checkout:
			err = doCheckout(ctx, pool)
			if err == nil {
				stats.checkout.Add(1)
			}
		case r < mix.order:
			err = doOrderMgmt(ctx, pool)
			if err == nil {
				stats.orderMgmt.Add(1)
			}
		case r < mix.background:
			err = doBackground(ctx, pool)
			if err == nil {
				stats.background.Add(1)
			}
		default:
			err = doReporting(ctx, pool)
			if err == nil {
				stats.reporting.Add(1)
			}
		}
		if err != nil && ctx.Err() == nil {
			stats.errors.Add(1)
		}

		time.Sleep(time.Duration(5+rand.IntN(20)) * time.Millisecond)
	}
}

// ─── Healthz HTTP Endpoint ────────────────────────────────────────────────

func serveHealthz(stats *Stats, cfg *Config) {
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Access-Control-Allow-Origin", "*")
		resp := map[string]any{
			"status":    "running",
			"uptime_s":  int(time.Since(stats.startTime).Seconds()),
			"start_time": stats.startTime.Format(time.RFC3339),
			"ops": map[string]int64{
				"browse":     stats.browse.Load(),
				"cart":       stats.cart.Load(),
				"checkout":   stats.checkout.Load(),
				"order_mgmt": stats.orderMgmt.Load(),
				"background": stats.background.Load(),
				"reporting":  stats.reporting.Load(),
				"chaos":      stats.chaos.Load(),
			},
			"errors": stats.errors.Load(),
			"bursts": stats.bursts.Load(),
			"config": map[string]any{
				"chaos_enabled": cfg.ChaosEnabled,
				"max_pool":      cfg.MaxPool,
				"duration":      cfg.Duration.String(),
			},
		}
		json.NewEncoder(w).Encode(resp)
	})

	log.Println("healthz: listening on :9090")
	if err := http.ListenAndServe(":9090", mux); err != nil {
		log.Printf("healthz server error: %v", err)
	}
}

// ─── Browse Operations ────────────────────────────────────────────────────

func doBrowse(ctx context.Context, pool *pgxpool.Pool) error {
	switch rand.IntN(4) {
	case 0:
		return browseCategory(ctx, pool)
	case 1:
		return viewProduct(ctx, pool)
	case 2:
		return searchProducts(ctx, pool)
	default:
		return touchSession(ctx, pool)
	}
}

func browseCategory(ctx context.Context, pool *pgxpool.Pool) error {
	catID := rand.Int64N(maxCategories) + 1
	offset := rand.IntN(20) * 48
	rows, err := pool.Query(ctx,
		`SELECT p.id, p.name, p.base_price, p.status,
		        coalesce(avg(r.rating), 0) AS avg_rating,
		        count(r.id) AS review_count
		 FROM products p
		 LEFT JOIN reviews r ON r.product_id = p.id
		 WHERE p.category_id = $1 AND p.status = 'active'
		 GROUP BY p.id
		 ORDER BY p.created_at DESC
		 LIMIT 48 OFFSET $2`,
		catID, offset)
	if err != nil {
		return err
	}
	rows.Close()
	return rows.Err()
}

func viewProduct(ctx context.Context, pool *pgxpool.Pool) error {
	productID := rand.Int64N(maxProducts) + 1
	rows, err := pool.Query(ctx,
		`SELECT p.id, p.name, p.base_price, p.description,
		        v.id AS variant_id, v.sku, v.name AS variant_name,
		        coalesce(v.price_override, p.base_price) AS price,
		        i.qty_available,
		        (SELECT coalesce(avg(rating)::numeric(3,2), 0) FROM reviews WHERE product_id = p.id) AS avg_rating,
		        (SELECT count(*) FROM reviews WHERE product_id = p.id) AS review_count
		 FROM products p
		 JOIN product_variants v ON v.product_id = p.id
		 JOIN inventory i ON i.variant_id = v.id
		 WHERE p.id = $1`,
		productID)
	if err != nil {
		return err
	}
	rows.Close()
	return rows.Err()
}

func searchProducts(ctx context.Context, pool *pgxpool.Pool) error {
	terms := []string{"widget", "gadget", "pro", "elite", "kit", "tool", "set", "device", "pack", "bundle"}
	term := terms[rand.IntN(len(terms))]
	rows, err := pool.Query(ctx,
		`SELECT p.id, p.name, p.base_price, p.slug,
		        similarity(p.name, $1) AS relevance
		 FROM products p
		 WHERE p.name % $1 AND p.status = 'active'
		 ORDER BY relevance DESC
		 LIMIT 20`,
		term)
	if err != nil {
		return err
	}
	rows.Close()
	return rows.Err()
}

func touchSession(ctx context.Context, pool *pgxpool.Pool) error {
	sessionID := rand.Int64N(maxSessions) + 1
	_, err := pool.Exec(ctx,
		`UPDATE sessions SET last_active = now() WHERE id = $1`,
		sessionID)
	return err
}

// ─── Cart Operations ──────────────────────────────────────────────────────

func doCart(ctx context.Context, pool *pgxpool.Pool) error {
	switch rand.IntN(4) {
	case 0:
		return addToCart(ctx, pool)
	case 1:
		return updateCartQty(ctx, pool)
	case 2:
		return removeFromCart(ctx, pool)
	default:
		return viewCart(ctx, pool)
	}
}

func addToCart(ctx context.Context, pool *pgxpool.Pool) error {
	sessionID := rand.Int64N(maxSessions) + 1
	variantID := rand.Int64N(maxVariants) + 1
	qty := rand.IntN(3) + 1
	_, err := pool.Exec(ctx,
		`INSERT INTO cart_items (session_id, variant_id, qty)
		 VALUES ($1, $2, $3)
		 ON CONFLICT DO NOTHING`,
		sessionID, variantID, qty)
	return err
}

func updateCartQty(ctx context.Context, pool *pgxpool.Pool) error {
	sessionID := rand.Int64N(maxSessions) + 1
	newQty := rand.IntN(5) + 1
	_, err := pool.Exec(ctx,
		`UPDATE cart_items SET qty = $1, updated_at = now()
		 WHERE id = (SELECT id FROM cart_items WHERE session_id = $2 LIMIT 1)`,
		newQty, sessionID)
	return err
}

func removeFromCart(ctx context.Context, pool *pgxpool.Pool) error {
	sessionID := rand.Int64N(maxSessions) + 1
	_, err := pool.Exec(ctx,
		`DELETE FROM cart_items
		 WHERE id = (SELECT id FROM cart_items WHERE session_id = $1 LIMIT 1)`,
		sessionID)
	return err
}

func viewCart(ctx context.Context, pool *pgxpool.Pool) error {
	sessionID := rand.Int64N(maxSessions) + 1
	rows, err := pool.Query(ctx,
		`SELECT ci.id, ci.qty, pv.name, pv.sku,
		        coalesce(pv.price_override, p.base_price) AS price,
		        (ci.qty * coalesce(pv.price_override, p.base_price)) AS line_total,
		        i.qty_available
		 FROM cart_items ci
		 JOIN product_variants pv ON pv.id = ci.variant_id
		 JOIN products p ON p.id = pv.product_id
		 JOIN inventory i ON i.variant_id = pv.id
		 WHERE ci.session_id = $1
		 ORDER BY ci.added_at`,
		sessionID)
	if err != nil {
		return err
	}
	rows.Close()
	return rows.Err()
}

// ─── Checkout ─────────────────────────────────────────────────────────────

func doCheckout(ctx context.Context, pool *pgxpool.Pool) error {
	customerID := rand.Int64N(maxCustomers) + 1
	addressID := rand.Int64N(maxAddresses) + 1
	variantID := rand.Int64N(maxVariants) + 1
	qty := rand.IntN(3) + 1

	tx, err := pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)

	var available int
	err = tx.QueryRow(ctx,
		`SELECT qty_available FROM inventory WHERE variant_id = $1 FOR UPDATE`,
		variantID).Scan(&available)
	if err != nil {
		return err
	}
	if available < qty {
		return nil
	}

	_, err = tx.Exec(ctx,
		`UPDATE inventory SET qty_available = qty_available - $1, qty_reserved = qty_reserved + $1, updated_at = now()
		 WHERE variant_id = $2`,
		qty, variantID)
	if err != nil {
		return err
	}

	var unitPrice float64
	err = tx.QueryRow(ctx,
		`SELECT coalesce(pv.price_override, p.base_price)
		 FROM product_variants pv
		 JOIN products p ON p.id = pv.product_id
		 WHERE pv.id = $1`,
		variantID).Scan(&unitPrice)
	if err != nil {
		return err
	}

	lineTotal := unitPrice * float64(qty)
	tax := lineTotal * 0.08
	shipping := 0.0
	if lineTotal < 50 {
		shipping = 7.99
	}
	total := lineTotal + tax + shipping

	var orderID int64
	err = tx.QueryRow(ctx,
		`INSERT INTO orders (customer_id, address_id, status, subtotal, tax, shipping, total)
		 VALUES ($1, $2, 'pending', $3, $4, $5, $6)
		 RETURNING id`,
		customerID, addressID, lineTotal, tax, shipping, total).Scan(&orderID)
	if err != nil {
		return err
	}

	_, err = tx.Exec(ctx,
		`INSERT INTO order_items (order_id, variant_id, qty, unit_price, line_total)
		 VALUES ($1, $2, $3, $4, $5)`,
		orderID, variantID, qty, unitPrice, lineTotal)
	if err != nil {
		return err
	}

	_, err = tx.Exec(ctx,
		`INSERT INTO payments (order_id, method, status, amount, gateway_txn_id)
		 VALUES ($1, $2, 'captured', $3, $4)`,
		orderID,
		[]string{"credit_card", "debit_card", "paypal", "apple_pay"}[rand.IntN(4)],
		total,
		fmt.Sprintf("txn_%d_%d", time.Now().UnixMicro(), rand.IntN(10000)))
	if err != nil {
		return err
	}

	return tx.Commit(ctx)
}

// ─── Order Management ─────────────────────────────────────────────────────

func doOrderMgmt(ctx context.Context, pool *pgxpool.Pool) error {
	switch rand.IntN(4) {
	case 0:
		return updateOrderStatus(ctx, pool)
	case 1:
		return updatePaymentStatus(ctx, pool)
	case 2:
		return createShipment(ctx, pool)
	default:
		return updateShipmentTracking(ctx, pool)
	}
}

func updateOrderStatus(ctx context.Context, pool *pgxpool.Pool) error {
	transitions := [][2]string{
		{"pending", "processing"},
		{"processing", "shipped"},
		{"shipped", "delivered"},
	}
	t := transitions[rand.IntN(len(transitions))]
	_, err := pool.Exec(ctx,
		`UPDATE orders SET status = $1, updated_at = now()
		 WHERE id = (SELECT id FROM orders WHERE status = $2 LIMIT 1)`,
		t[1], t[0])
	return err
}

func updatePaymentStatus(ctx context.Context, pool *pgxpool.Pool) error {
	_, err := pool.Exec(ctx,
		`UPDATE payments SET status = 'settled', settled_at = now()
		 WHERE id = (SELECT id FROM payments WHERE status = 'captured' LIMIT 1)`)
	return err
}

func createShipment(ctx context.Context, pool *pgxpool.Pool) error {
	orderID := rand.Int64N(maxOrders) + 1
	_, err := pool.Exec(ctx,
		`INSERT INTO shipments (order_id, carrier, tracking_number, status, shipped_at)
		 SELECT $1, $2, $3, 'in_transit', now()
		 WHERE EXISTS (SELECT 1 FROM orders WHERE id = $1 AND status IN ('processing', 'shipped'))`,
		orderID,
		[]string{"ups", "fedex", "usps", "dhl"}[rand.IntN(4)],
		fmt.Sprintf("TRK%d%d", time.Now().UnixMicro(), rand.IntN(1000)))
	return err
}

func updateShipmentTracking(ctx context.Context, pool *pgxpool.Pool) error {
	transitions := [][2]string{
		{"label_created", "in_transit"},
		{"in_transit", "out_for_delivery"},
		{"out_for_delivery", "delivered"},
	}
	t := transitions[rand.IntN(len(transitions))]
	_, err := pool.Exec(ctx,
		`UPDATE shipments SET status = $1,
		        delivered_at = CASE WHEN $1 = 'delivered' THEN now() ELSE delivered_at END
		 WHERE id = (SELECT id FROM shipments WHERE status = $2 LIMIT 1)`,
		t[1], t[0])
	return err
}

// ─── Background Operations ────────────────────────────────────────────────

func doBackground(ctx context.Context, pool *pgxpool.Pool) error {
	switch rand.IntN(5) {
	case 0:
		return expireCarts(ctx, pool)
	case 1:
		return expireSessions(ctx, pool)
	case 2:
		return logSearch(ctx, pool)
	case 3:
		return logAudit(ctx, pool)
	default:
		return writeReview(ctx, pool)
	}
}

func expireCarts(ctx context.Context, pool *pgxpool.Pool) error {
	_, err := pool.Exec(ctx,
		`DELETE FROM cart_items
		 WHERE id IN (SELECT id FROM cart_items WHERE updated_at < now() - interval '24 hours' LIMIT 100)`)
	return err
}

func expireSessions(ctx context.Context, pool *pgxpool.Pool) error {
	_, err := pool.Exec(ctx,
		`DELETE FROM sessions
		 WHERE id IN (SELECT id FROM sessions WHERE expires_at < now() LIMIT 50)`)
	return err
}

func logSearch(ctx context.Context, pool *pgxpool.Pool) error {
	queries := []string{"laptop", "headphones", "shoes", "coffee maker", "keyboard", "monitor", "backpack",
		"water bottle", "desk lamp", "phone case", "bluetooth speaker", "usb cable", "mouse pad",
		"webcam", "standing desk", "chair", "plant pot", "notebook", "pen set", "wall art"}
	sessionID := rand.Int64N(maxSessions) + 1
	_, err := pool.Exec(ctx,
		`INSERT INTO search_log (session_id, query, results_count)
		 VALUES ($1, $2, $3)`,
		sessionID, queries[rand.IntN(len(queries))], rand.IntN(200))
	return err
}

func logAudit(ctx context.Context, pool *pgxpool.Pool) error {
	entities := []string{"order", "payment", "shipment", "customer", "product", "inventory"}
	actions := []string{"create", "update", "delete", "view", "export"}
	_, err := pool.Exec(ctx,
		`INSERT INTO audit_log (entity_type, entity_id, action, actor_id, metadata)
		 VALUES ($1, $2, $3, $4, $5::jsonb)`,
		entities[rand.IntN(len(entities))],
		rand.Int64N(maxOrders)+1,
		actions[rand.IntN(len(actions))],
		rand.Int64N(maxCustomers)+1,
		fmt.Sprintf(`{"ip":"10.%d.%d.%d","source":"web"}`, rand.IntN(256), rand.IntN(256), rand.IntN(256)))
	return err
}

func writeReview(ctx context.Context, pool *pgxpool.Pool) error {
	_, err := pool.Exec(ctx,
		`INSERT INTO reviews (product_id, customer_id, rating, title, body)
		 VALUES ($1, $2, $3, $4, $5)`,
		rand.Int64N(maxProducts)+1,
		rand.Int64N(maxCustomers)+1,
		rand.IntN(5)+1,
		fmt.Sprintf("Review at %s", time.Now().Format(time.RFC3339)),
		[]string{
			"Great product, exactly what I needed. Fast shipping too.",
			"Decent quality for the price. Would consider buying again.",
			"Not what I expected based on the description. Returning it.",
			"Excellent build quality. My third purchase from this brand.",
			"Works as advertised. Good value for money.",
		}[rand.IntN(5)])
	return err
}

// ─── Reporting Queries ────────────────────────────────────────────────────

func doReporting(ctx context.Context, pool *pgxpool.Pool) error {
	switch rand.IntN(4) {
	case 0:
		return salesReport(ctx, pool)
	case 1:
		return topProducts(ctx, pool)
	case 2:
		return customerLTV(ctx, pool)
	default:
		return inventoryReport(ctx, pool)
	}
}

func salesReport(ctx context.Context, pool *pgxpool.Pool) error {
	rows, err := pool.Query(ctx,
		`SELECT date_trunc('hour', placed_at) AS hour,
		        count(*) AS order_count,
		        sum(total) AS revenue,
		        avg(total) AS avg_order_value
		 FROM orders
		 WHERE placed_at > now() - interval '7 days'
		 GROUP BY 1
		 ORDER BY 1 DESC
		 LIMIT 168`)
	if err != nil {
		return err
	}
	rows.Close()
	return rows.Err()
}

func topProducts(ctx context.Context, pool *pgxpool.Pool) error {
	rows, err := pool.Query(ctx,
		`SELECT p.id, p.name, count(oi.id) AS units_sold, sum(oi.line_total) AS revenue
		 FROM order_items oi
		 JOIN product_variants pv ON pv.id = oi.variant_id
		 JOIN products p ON p.id = pv.product_id
		 JOIN orders o ON o.id = oi.order_id
		 WHERE o.placed_at > now() - interval '30 days'
		 GROUP BY p.id, p.name
		 ORDER BY revenue DESC
		 LIMIT 25`)
	if err != nil {
		return err
	}
	rows.Close()
	return rows.Err()
}

func customerLTV(ctx context.Context, pool *pgxpool.Pool) error {
	customerID := rand.Int64N(maxCustomers) + 1
	rows, err := pool.Query(ctx,
		`SELECT c.id, c.name, c.email,
		        count(o.id) AS total_orders,
		        coalesce(sum(o.total), 0) AS lifetime_value,
		        min(o.placed_at) AS first_order,
		        max(o.placed_at) AS last_order
		 FROM customers c
		 LEFT JOIN orders o ON o.customer_id = c.id
		 WHERE c.id = $1
		 GROUP BY c.id`,
		customerID)
	if err != nil {
		return err
	}
	rows.Close()
	return rows.Err()
}

func inventoryReport(ctx context.Context, pool *pgxpool.Pool) error {
	rows, err := pool.Query(ctx,
		`SELECT pv.sku, p.name, pv.name AS variant,
		        i.qty_available, i.qty_reserved,
		        coalesce(pv.price_override, p.base_price) AS price,
		        (i.qty_available * coalesce(pv.price_override, p.base_price)) AS stock_value
		 FROM inventory i
		 JOIN product_variants pv ON pv.id = i.variant_id
		 JOIN products p ON p.id = pv.product_id
		 WHERE i.qty_available < 10
		 ORDER BY i.qty_available ASC
		 LIMIT 50`)
	if err != nil {
		return err
	}
	rows.Close()
	return rows.Err()
}

// ─── Chaos Patterns ───────────────────────────────────────────────────────

func runChaos(ctx context.Context, pool *pgxpool.Pool, stats *Stats) {
	patterns := []struct {
		name string
		fn   func(context.Context, *pgxpool.Pool) error
	}{
		{"abandoned-checkout", chaosAbandonedCheckout},
		{"flash-sale", chaosFlashSale},
		{"bulk-price-update", chaosBulkPriceUpdate},
		{"cart-cleanup-storm", chaosCartCleanupStorm},
		{"inventory-restock", chaosInventoryRestock},
		{"index-rebuild", chaosIndexRebuild},
	}

	p := patterns[rand.IntN(len(patterns))]
	log.Printf("chaos: running %s", p.name)
	stats.chaos.Add(1)

	if err := p.fn(ctx, pool); err != nil && ctx.Err() == nil {
		log.Printf("chaos %s error: %v", p.name, err)
		stats.errors.Add(1)
	}
}

func chaosAbandonedCheckout(ctx context.Context, pool *pgxpool.Pool) error {
	tx, err := pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)

	variantID := rand.Int64N(maxVariants) + 1
	_, err = tx.Exec(ctx,
		`SELECT qty_available FROM inventory WHERE variant_id = $1 FOR UPDATE`, variantID)
	if err != nil {
		return err
	}

	holdDuration := time.Duration(20+rand.IntN(20)) * time.Second
	log.Printf("chaos: holding inventory lock for %s (variant=%d)", holdDuration, variantID)
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-time.After(holdDuration):
	}

	return tx.Rollback(ctx)
}

func chaosFlashSale(ctx context.Context, pool *pgxpool.Pool) error {
	variantID := rand.Int64N(maxVariants) + 1
	log.Printf("chaos: flash sale on variant=%d (20 concurrent buyers)", variantID)

	chaosCtx, cancel := context.WithTimeout(ctx, 20*time.Second)
	defer cancel()

	var wg sync.WaitGroup
	for range 20 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			tx, err := pool.BeginTx(chaosCtx, pgx.TxOptions{IsoLevel: pgx.ReadCommitted})
			if err != nil {
				return
			}
			defer tx.Rollback(chaosCtx)

			var avail int
			err = tx.QueryRow(chaosCtx,
				`SELECT qty_available FROM inventory WHERE variant_id = $1 FOR UPDATE`,
				variantID).Scan(&avail)
			if err != nil || avail < 1 {
				return
			}

			_, _ = tx.Exec(chaosCtx,
				`UPDATE inventory SET qty_available = qty_available - 1, updated_at = now()
				 WHERE variant_id = $1`, variantID)

			time.Sleep(time.Duration(100+rand.IntN(500)) * time.Millisecond)
			_ = tx.Commit(chaosCtx)
		}()
	}
	wg.Wait()
	return nil
}

func chaosBulkPriceUpdate(ctx context.Context, pool *pgxpool.Pool) error {
	log.Println("chaos: bulk price update (10K variants)")

	tx, err := pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)

	multiplier := 0.9 + rand.Float64()*0.2
	startID := rand.Int64N(maxVariants-10000) + 1

	_, err = tx.Exec(ctx,
		`INSERT INTO price_history (variant_id, old_price, new_price, changed_at)
		 SELECT pv.id,
		        coalesce(pv.price_override, p.base_price),
		        (coalesce(pv.price_override, p.base_price) * $1)::numeric(10,2),
		        now()
		 FROM product_variants pv
		 JOIN products p ON p.id = pv.product_id
		 WHERE pv.id BETWEEN $2 AND $3`,
		multiplier, startID, startID+10000)
	if err != nil {
		return err
	}

	_, err = tx.Exec(ctx,
		`UPDATE product_variants
		 SET price_override = CASE
		     WHEN price_override IS NOT NULL THEN (price_override * $1)::numeric(10,2)
		     ELSE NULL
		 END
		 WHERE id BETWEEN $2 AND $3`,
		multiplier, startID, startID+10000)
	if err != nil {
		return err
	}

	return tx.Commit(ctx)
}

func chaosCartCleanupStorm(ctx context.Context, pool *pgxpool.Pool) error {
	log.Println("chaos: cart cleanup storm (purging old cart items)")

	result, err := pool.Exec(ctx,
		`DELETE FROM cart_items
		 WHERE id IN (
		     SELECT id FROM cart_items
		     WHERE updated_at < now() - interval '1 hour'
		     LIMIT 50000
		 )`)
	if err != nil {
		return err
	}
	log.Printf("chaos: deleted %d expired cart items", result.RowsAffected())
	return nil
}

func chaosInventoryRestock(ctx context.Context, pool *pgxpool.Pool) error {
	startID := rand.Int64N(maxVariants-5000) + 1
	log.Printf("chaos: restocking inventory (variants %d-%d)", startID, startID+5000)

	_, err := pool.Exec(ctx,
		`UPDATE inventory
		 SET qty_available = qty_available + 50 + (random() * 200)::int,
		     qty_reserved = GREATEST(qty_reserved - 5, 0),
		     updated_at = now()
		 WHERE variant_id BETWEEN $1 AND $2`,
		startID, startID+5000)
	return err
}

func chaosIndexRebuild(ctx context.Context, pool *pgxpool.Pool) error {
	idxName := fmt.Sprintf("idx_chaos_orders_%d", time.Now().UnixMilli())
	log.Printf("chaos: CREATE INDEX %s", idxName)

	_, err := pool.Exec(ctx,
		fmt.Sprintf(`CREATE INDEX CONCURRENTLY IF NOT EXISTS %s ON orders(total, placed_at)`, idxName))
	if err != nil {
		return err
	}

	time.Sleep(time.Duration(5+rand.IntN(10)) * time.Second)

	log.Printf("chaos: DROP INDEX %s", idxName)
	_, err = pool.Exec(ctx, fmt.Sprintf(`DROP INDEX CONCURRENTLY IF EXISTS %s`, idxName))
	return err
}
