# Burnside Project Test Suite
# Validates pg-collector metrics against PostgreSQL ground truth

TRUTH_COMPOSE := docker compose -f docker-compose.truth.yml

# === TRUTH SERVICE ===

.PHONY: truth-up
truth-up: ## Start truth infrastructure (postgres + collector + truth API)
	$(TRUTH_COMPOSE) up --build -d
	@echo "Waiting 30s for collector to produce initial samples..."
	@sleep 30
	@echo ""
	@echo "Truth service ready:"
	@echo "  API:    http://localhost:8000"
	@echo "  Verify: curl http://localhost:8000/verify/cache-memory"
	@echo "  Panels: curl http://localhost:8000/panels"
	@echo "  Health: curl http://localhost:8000/health"

.PHONY: truth-verify-cache-memory
truth-verify-cache-memory: ## Run cache-memory verification (CLI mode, exits 0=PASS 1=FAIL)
	$(TRUTH_COMPOSE) --profile verify run --rm truth-verify python -m app.main cache-memory

.PHONY: truth-verify-all
truth-verify-all: ## Run all verifications via API (requires truth-up)
	@echo "=== cache-memory ==="
	@curl -s http://localhost:8000/verify/cache-memory | python3 -m json.tool || echo "FAILED"
	@echo ""
	@echo "=== wal-checkpoints ==="
	@curl -s http://localhost:8000/verify/wal-checkpoints | python3 -m json.tool || echo "FAILED"
	@echo ""
	@echo "=== locks ==="
	@curl -s http://localhost:8000/verify/locks | python3 -m json.tool || echo "FAILED"
	@echo ""
	@echo "=== replication ==="
	@curl -s http://localhost:8000/verify/replication | python3 -m json.tool || echo "FAILED"

.PHONY: truth-down
truth-down: ## Stop truth infrastructure and remove volumes
	$(TRUTH_COMPOSE) down -v

.PHONY: truth-logs
truth-logs: ## Show truth-service and collector logs
	$(TRUTH_COMPOSE) logs -f truth-service collector

.PHONY: truth-status
truth-status: ## Show running truth containers
	$(TRUTH_COMPOSE) ps

# === HELP ===

.PHONY: help
help: ## Show this help
	@echo "Burnside Project Test Suite"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-30s\033[0m %s\n", $$1, $$2}'