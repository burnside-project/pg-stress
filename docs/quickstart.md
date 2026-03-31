# Quickstart

Deploy pg-stress on a local test server. This guide was written while deploying to
Ubuntu 24.04 (12 CPU, 62 GB RAM, 100 GB disk) running Docker 29.1.3.

## Prerequisites

| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| Docker | 24.0+ | 29.0+ |
| Docker Compose | v2.20+ | v5.0+ |
| Disk (free) | 20 GB | 50 GB+ |
| Memory (free) | 4 GB | 16 GB+ |
| CPU | 4 cores | 8+ cores |
| Git | 2.x | any |
| Python 3 | 3.10+ | 3.12 (for analyzer) |

> **Native PostgreSQL on the same host?** No conflict -- pg-stress runs its own
> PostgreSQL inside Docker on port 5434 (configurable). Your native PG on 5432 is untouched.

## 1. Clone the Repo

```bash
ssh your-test-server

cd /opt
sudo git clone https://github.com/dataalgebra-engineering/pg-stress.git
sudo chown -R $(whoami):$(whoami) pg-stress
cd pg-stress
```

## 2. Check for Port Conflicts

pg-stress needs these ports. Check if they're free:

```bash
ss -tlnp | grep -E '(5434|8000|9090|9091|8001|8080)'
```

If any are taken, create a `.env` file to remap:

```bash
cp .env.example .env
```

```ini
# .env — adjust ports as needed
PG_PORT=5434              # PostgreSQL
DASHBOARD_PORT=8002       # Dashboard (if 8000 is taken)
# Load generator healthz is internal only (no host port needed)
ORM_HEALTHZ_PORT=9091     # ORM generator health
TRUTH_PORT=8001           # Truth service
COLLECTOR_PORT=8083       # Collector
```

## 3. Clean Up Stale Processes (if any)

```bash
# Check for leftover processes from previous tests
ps aux | grep -E 'soak|stress|mock' | grep -v grep

# Kill if found
kill <pid>
```

## 4. Choose Your Path

### Path A: BYOD — Bring Your Own Data

```bash
# On your production server (or wherever the dump is)
pg_dump --format=custom --jobs=4 mydb > /tmp/mydb.dump
scp /tmp/mydb.dump test-server:/opt/pg-stress/

# On test server
cd /opt/pg-stress

# Start just PostgreSQL
docker compose up -d postgres
docker compose exec -T postgres pg_isready -U postgres  # wait for ready

# Restore your dump
docker compose exec -T postgres pg_restore \
  -U postgres -d testdb --jobs=4 --no-owner --no-acl \
  < mydb.dump

# Run ANALYZE
docker compose exec -T postgres psql -U postgres -d testdb -c "ANALYZE VERBOSE"

# Start the rest of the stack
docker compose up -d
```

### Path B: Seed + Stress — No Production Data

```bash
cd /opt/pg-stress

# Start everything (auto-seeds ~30M rows on first run, ~5-10 min)
docker compose up --build -d

# Watch seeding progress
docker compose logs -f load-generator
# Wait for: "ecommerce-load: data ready (customers=1000000)"
```

## 5. Verify

```bash
# Check all containers are running
docker compose ps

# Check PostgreSQL
docker compose exec postgres psql -U postgres -d testdb -c \
  "SELECT count(*) FROM pg_stat_statements"

# Check dashboard
curl -s http://localhost:8002/health    # or whatever port you set

# Check load generator
docker compose logs --tail=5 load-generator
```

## 6. Run WHAT IF Scenarios (Optional)

```bash
# Inject 5M rows into orders
docker compose exec -T postgres psql -U postgres -d testdb -c "
  INSERT INTO orders (customer_id, status, subtotal, tax, shipping, total, placed_at)
  SELECT (random()*999999+1)::int, 'pending',
         (random()*500)::numeric(10,2),
         (random()*40)::numeric(10,2), 0,
         (random()*540)::numeric(12,2),
         now() - random()*interval '365 days'
  FROM generate_series(1, 5000000);
  ANALYZE orders;
"

# Open 100 concurrent connections via pgbench
docker compose exec -T postgres pgbench -U postgres -d testdb \
  -c 100 -j 4 -T 300 --select-only
```

## 7. Capture and Analyze

```bash
# View top queries
make pg-stat

# View database and table sizes
make db-size

# Collect full report
make report

# AI analysis (requires API key)
export ANTHROPIC_API_KEY=sk-ant-...
pip install anthropic psycopg2-binary rich  # first time only

# Point analyzer at the Docker PG
PG_PORT=5434 make analyze
PG_PORT=5434 make analyze-tuning
PG_PORT=5434 make analyze-queries
PG_PORT=5434 make analyze-capacity

# Reports saved to out/analysis-*/
ls out/
```

## 8. Add ORM + pgbench (Optional)

```bash
# Add SQLAlchemy ORM load generator
docker compose --profile orm up --build -d

# Add pgbench comparison
docker compose --profile pgbench up --build -d

# Or everything at once
docker compose --profile full up --build -d
```

## 9. Teardown

```bash
# Stop and remove everything (including data volumes)
docker compose --profile full down -v

# Or keep volumes for next run
docker compose --profile full down
```

---

## Port Reference

| Service | Default Port | Env Variable |
|---------|-------------|-------------|
| PostgreSQL | 5434 | `PG_PORT` |
| Dashboard | 8000 | `DASHBOARD_PORT` |
| Load Generator (healthz) | 9090 | (internal) |
| ORM Generator (healthz) | 9091 | `ORM_HEALTHZ_PORT` |
| Truth Service | 8001 | `TRUTH_PORT` |
| Collector | 8080 | `COLLECTOR_PORT` |

## Troubleshooting

### Seeding is slow

First run seeds ~30M rows (~10 GB). Takes 5-10 minutes on SSD, longer on HDD.
Watch progress:

```bash
docker compose logs -f postgres 2>&1 | grep -E 'Seeding|Done'
```

### "Port already in use"

```bash
ss -tlnp | grep <port>          # Find what's using it
# Then remap in .env
```

### Out of disk

```bash
df -h /
docker system df               # Docker disk usage
docker system prune -f          # Clean unused images/containers
```

### Load generator won't start

It waits for seeded data. Check postgres logs:

```bash
docker compose logs postgres | tail -20
```

### Analyzer can't connect

The analyzer runs on the host, not in Docker. Point it at the mapped port:

```bash
PG_HOST=localhost PG_PORT=5434 python analyzer/analyze.py
```
