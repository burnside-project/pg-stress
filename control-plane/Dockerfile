FROM postgres:15-bookworm AS pgtools

FROM python:3.12-slim

WORKDIR /app

# Copy pgbench + psql + pg_restore from the postgres image.
COPY --from=pgtools /usr/lib/postgresql/15/bin/pgbench /usr/local/bin/pgbench
COPY --from=pgtools /usr/lib/postgresql/15/bin/psql /usr/local/bin/psql
COPY --from=pgtools /usr/lib/postgresql/15/bin/pg_restore /usr/local/bin/pg_restore
COPY --from=pgtools /usr/lib/postgresql/15/bin/pg_dump /usr/local/bin/pg_dump

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 docker.io \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py query_replay.py schema_graph.py ./

EXPOSE 8100

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8100"]
