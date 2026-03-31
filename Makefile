# Burnside Project Test Suite
# PostgreSQL OLTP Stress Testing + ORM Validation + pgbench Comparison
#
# Quick start:
#   make up                         Start core stack (pg + raw-SQL + dashboard)
#   make up-orm                     Core + ORM load generator
#   make up-bench                   Core + pgbench comparison
#   make up-full                    Everything
#   make deploy                     Deploy to remote server

COMPOSE := docker compose
SCENARIO ?= default

# ═══════════════════════════════════════════════════════════════════════════
# Core Stack — postgres + raw-SQL load generator + dashboard
# ═══════════════════════════════════════════════════════════════════════════

.PHONY: up
up: ## Start core stack (postgres + load-generator + dashboard)
	SCENARIO=$(SCENARIO) $(COMPOSE) up --build -d
	@echo ""
	@echo "  Dashboard:  http://localhost:8000"
	@echo "  Postgres:   localhost:5434"
	@echo "  Load Gen:   http://localhost:9090/healthz"
	@echo "  Scenario:   $(SCENARIO)"

.PHONY: down
down: ## Stop all services and remove volumes
	$(COMPOSE) --profile full down -v

.PHONY: stop
stop: ## Stop all services (keep volumes)
	$(COMPOSE) --profile full down

.PHONY: restart
restart: stop up ## Restart core stack

.PHONY: status
status: ## Show all running containers
	$(COMPOSE) --profile full ps

.PHONY: logs
logs: ## Follow all logs
	$(COMPOSE) --profile full logs -f

.PHONY: logs-loadgen
logs-loadgen: ## Follow raw-SQL load generator logs
	$(COMPOSE) logs -f load-generator

# ═══════════════════════════════════════════════════════════════════════════
# ORM Load Generator — profile: orm
# ═══════════════════════════════════════════════════════════════════════════

.PHONY: up-orm
up-orm: ## Start core + ORM load generator (raw SQL + SQLAlchemy side by side)
	SCENARIO=$(SCENARIO) $(COMPOSE) --profile orm up --build -d
	@echo ""
	@echo "  Dashboard:  http://localhost:8000"
	@echo "  Raw SQL:    http://localhost:9090/healthz"
	@echo "  ORM:        http://localhost:9091/healthz"
	@echo "  Postgres:   localhost:5434"
	@echo "  Scenario:   $(SCENARIO)"
	@echo ""
	@echo "  Both generators running — compare pg_stat_statements fingerprints."

.PHONY: logs-orm
logs-orm: ## Follow ORM load generator logs
	$(COMPOSE) --profile orm logs -f load-generator-orm

# ═══════════════════════════════════════════════════════════════════════════
# pgbench Comparison — profile: pgbench
# ═══════════════════════════════════════════════════════════════════════════

.PHONY: up-bench
up-bench: ## Start core + pgbench runner
	SCENARIO=$(SCENARIO) $(COMPOSE) --profile pgbench up --build -d
	@echo ""
	@echo "  Dashboard:  http://localhost:8000"
	@echo "  Postgres:   localhost:5434"
	@echo "  pgbench:    running (check logs with: make logs-bench)"

.PHONY: logs-bench
logs-bench: ## Follow pgbench runner logs
	$(COMPOSE) --profile pgbench logs -f pgbench-runner

.PHONY: bench
bench: ## Run standalone pgbench benchmark (requires running postgres)
	./scripts/run-benchmark.sh

.PHONY: bench-remote
bench-remote: ## Run pgbench benchmark on remote server
	./scripts/run-benchmark.sh --remote $(DEPLOY_HOST)

# ═══════════════════════════════════════════════════════════════════════════
# Collector + Truth Service — profile: collector
# ═══════════════════════════════════════════════════════════════════════════

.PHONY: up-collector
up-collector: ## Start core + pg-collector + truth-service
	SCENARIO=$(SCENARIO) $(COMPOSE) --profile collector up --build -d
	@echo ""
	@echo "  Dashboard:      http://localhost:8000"
	@echo "  Truth Service:  http://localhost:8001"
	@echo "  Collector:      http://localhost:8080"
	@echo "  Postgres:       localhost:5434"

.PHONY: logs-collector
logs-collector: ## Follow collector and truth-service logs
	$(COMPOSE) --profile collector logs -f collector truth-service

.PHONY: verify
verify: ## Run all truth-service verifications
	@echo "=== cache-memory ==="
	@curl -s http://localhost:8001/verify/cache-memory | python3 -m json.tool || echo "FAILED"
	@echo ""
	@echo "=== wal-checkpoints ==="
	@curl -s http://localhost:8001/verify/wal-checkpoints | python3 -m json.tool || echo "FAILED"
	@echo ""
	@echo "=== locks ==="
	@curl -s http://localhost:8001/verify/locks | python3 -m json.tool || echo "FAILED"
	@echo ""
	@echo "=== replication ==="
	@curl -s http://localhost:8001/verify/replication | python3 -m json.tool || echo "FAILED"

# ═══════════════════════════════════════════════════════════════════════════
# AI Analyzer — Claude-powered analysis — profile: analyze
# ═══════════════════════════════════════════════════════════════════════════

.PHONY: analyze
analyze: ## AI analysis of running stack (requires ANTHROPIC_API_KEY)
	@pip install -q anthropic psycopg2-binary rich 2>/dev/null
	python analyzer/analyze.py --save

.PHONY: analyze-tuning
analyze-tuning: ## AI analysis focused on PostgreSQL parameter tuning
	@pip install -q anthropic psycopg2-binary rich 2>/dev/null
	python analyzer/analyze.py --focus tuning --save

.PHONY: analyze-queries
analyze-queries: ## AI analysis focused on query optimization
	@pip install -q anthropic psycopg2-binary rich 2>/dev/null
	python analyzer/analyze.py --focus queries --save

.PHONY: analyze-capacity
analyze-capacity: ## AI analysis focused on capacity predictions
	@pip install -q anthropic psycopg2-binary rich 2>/dev/null
	python analyzer/analyze.py --focus capacity --save

.PHONY: analyze-collect
analyze-collect: ## Collect diagnostic data only (no AI, no API key needed)
	@pip install -q psycopg2-binary 2>/dev/null
	python analyzer/collect.py | python3 -m json.tool

# ═══════════════════════════════════════════════════════════════════════════
# Full Stack — all profiles
# ═══════════════════════════════════════════════════════════════════════════

.PHONY: up-full
up-full: ## Start everything: core + ORM + pgbench + collector + truth
	SCENARIO=$(SCENARIO) $(COMPOSE) --profile full up --build -d
	@echo ""
	@echo "  Dashboard:      http://localhost:8000"
	@echo "  Raw SQL:        http://localhost:9090/healthz"
	@echo "  ORM:            http://localhost:9091/healthz"
	@echo "  Truth Service:  http://localhost:8001"
	@echo "  Collector:      http://localhost:8080"
	@echo "  Postgres:       localhost:5434"
	@echo "  pgbench:        running"

# ═══════════════════════════════════════════════════════════════════════════
# Database Operations
# ═══════════════════════════════════════════════════════════════════════════

.PHONY: psql
psql: ## Connect to PostgreSQL via psql
	$(COMPOSE) exec postgres psql -U postgres -d testdb

.PHONY: seed
seed: ## Re-seed database schema and data
	$(COMPOSE) exec -T postgres psql -U postgres -d testdb -f /docker-entrypoint-initdb.d/01-schema.sql

.PHONY: pg-stat
pg-stat: ## Show top 20 queries by total execution time
	@$(COMPOSE) exec -T postgres psql -U postgres -d testdb -c " \
		SELECT queryid, calls, \
		       round(total_exec_time::numeric, 0) AS total_ms, \
		       round(mean_exec_time::numeric, 2) AS mean_ms, \
		       rows, \
		       left(query, 80) AS query \
		FROM pg_stat_statements \
		WHERE dbid = (SELECT oid FROM pg_database WHERE datname = 'testdb') \
		ORDER BY total_exec_time DESC \
		LIMIT 20;"

.PHONY: pg-stat-reset
pg-stat-reset: ## Reset pg_stat_statements counters
	$(COMPOSE) exec -T postgres psql -U postgres -d testdb -c "SELECT pg_stat_statements_reset();"
	@echo "pg_stat_statements reset."

.PHONY: db-size
db-size: ## Show database and table sizes
	@$(COMPOSE) exec -T postgres psql -U postgres -d testdb -c " \
		SELECT relname AS table, \
		       pg_size_pretty(pg_total_relation_size(relid)) AS size, \
		       n_live_tup AS rows, \
		       n_dead_tup AS dead \
		FROM pg_stat_user_tables \
		ORDER BY pg_total_relation_size(relid) DESC;"
	@echo ""
	@$(COMPOSE) exec -T postgres psql -U postgres -d testdb -c " \
		SELECT pg_size_pretty(pg_database_size('testdb')) AS database_size;"

# ═══════════════════════════════════════════════════════════════════════════
# Reports & Monitoring
# ═══════════════════════════════════════════════════════════════════════════

.PHONY: report
report: ## Collect comprehensive report from running stack
	./scripts/collect-report.sh

.PHONY: report-remote
report-remote: ## Collect report from remote server
	./scripts/collect-report.sh --remote $(DEPLOY_HOST)

.PHONY: healthz
healthz: ## Check health of all services
	@echo "Load Generator (raw):"
	@curl -s http://localhost:9090/healthz | python3 -m json.tool 2>/dev/null || echo "  NOT RUNNING"
	@echo ""
	@echo "Load Generator (ORM):"
	@curl -s http://localhost:9091/healthz | python3 -m json.tool 2>/dev/null || echo "  NOT RUNNING"
	@echo ""
	@echo "Dashboard:"
	@curl -so /dev/null -w "  HTTP %{http_code}\n" http://localhost:8000/ 2>/dev/null || echo "  NOT RUNNING"
	@echo ""
	@echo "Truth Service:"
	@curl -s http://localhost:8001/health | python3 -m json.tool 2>/dev/null || echo "  NOT RUNNING"
	@echo ""
	@echo "Collector:"
	@curl -so /dev/null -w "  HTTP %{http_code}\n" http://localhost:8080/health 2>/dev/null || echo "  NOT RUNNING"

# ═══════════════════════════════════════════════════════════════════════════
# Deployment
# ═══════════════════════════════════════════════════════════════════════════

DEPLOY_HOST ?= 4

.PHONY: deploy
deploy: ## Deploy stack to remote server (default: ssh 4)
	./scripts/deploy-remote.sh $(DEPLOY_HOST)

.PHONY: deploy-full
deploy-full: ## Deploy full stack to remote server
	DEPLOY_PROFILE=full ./scripts/deploy-remote.sh $(DEPLOY_HOST)

# ═══════════════════════════════════════════════════════════════════════════
# Legacy Truth Service (standalone compose)
# ═══════════════════════════════════════════════════════════════════════════

TRUTH_COMPOSE := docker compose -f docker-compose.truth.yml

.PHONY: truth-up
truth-up: ## Start standalone truth infrastructure
	$(TRUTH_COMPOSE) up --build -d
	@echo "Waiting 30s for collector to produce initial samples..."
	@sleep 30
	@echo ""
	@echo "  Truth API:  http://localhost:8000"
	@echo "  Verify:     curl http://localhost:8000/verify/cache-memory"

.PHONY: truth-down
truth-down: ## Stop standalone truth infrastructure
	$(TRUTH_COMPOSE) down -v

.PHONY: truth-logs
truth-logs: ## Follow standalone truth logs
	$(TRUTH_COMPOSE) logs -f truth-service collector

# ═══════════════════════════════════════════════════════════════════════════
# Cleanup
# ═══════════════════════════════════════════════════════════════════════════

.PHONY: clean
clean: ## Stop everything, remove volumes and output files
	$(COMPOSE) --profile full down -v
	$(TRUTH_COMPOSE) down -v 2>/dev/null || true
	rm -rf out/benchmark-* out/report-*
	@echo "Cleaned."

.PHONY: clean-images
clean-images: clean ## Clean + remove built images
	docker image rm -f $$(docker images --filter "reference=*burnside*" -q) 2>/dev/null || true
	docker image rm -f $$(docker images --filter "reference=*stress*" -q) 2>/dev/null || true
	docker image rm -f $$(docker images --filter "reference=*load-generator*" -q) 2>/dev/null || true
	docker image rm -f $$(docker images --filter "reference=*pgbench*" -q) 2>/dev/null || true
	@echo "Images removed."

# ═══════════════════════════════════════════════════════════════════════════
# Help
# ═══════════════════════════════════════════════════════════════════════════

.PHONY: help
help: ## Show this help
	@echo "Burnside Project Test Suite"
	@echo "PostgreSQL OLTP Stress Testing + ORM Validation + pgbench Comparison"
	@echo ""
	@echo "Profiles:  (none)=core  orm  pgbench  collector  full"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
