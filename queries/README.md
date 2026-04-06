# Production Queries

Drop your production SQL queries here for replay during stress tests.

## File formats

### Individual SQL files

One query per file. The filename becomes the query name.

```
queries/
  checkout-flow.sql         → "checkout-flow"
  search-products.sql       → "search-products"
  monthly-report.sql        → "monthly-report"
```

### pg_stat_statements export (JSON)

Export from your production server and save as `queries.json`:

```bash
# On production:
psql -c "SELECT query, calls, mean_exec_time, rows \
         FROM pg_stat_statements \
         ORDER BY total_exec_time DESC \
         LIMIT 50" --format=json > queries/queries.json
```

The `calls` field is used to weight query frequency during replay —
queries called 10,000 times in production will be replayed more often
than queries called 100 times.

## How it works

1. Place files in this directory
2. pg-stress auto-loads them on startup (or click "Reload" in the UI)
3. Start a replay from the Control Panel or API:

```bash
# API
curl -X POST http://<host>:8100/replay/start \
  -d '{"query_set_id":"auto","concurrency":10}'

# Or from the Control Panel UI → Production Query Replay → Start Replay
```

## Tips

- Replace parameter placeholders (`$1`, `$2`) with realistic values
- Include your actual WHERE clauses, JOINs, and subqueries
- Mix read and write queries to simulate real traffic patterns
- Include your slowest queries — those are the ones you need to test
