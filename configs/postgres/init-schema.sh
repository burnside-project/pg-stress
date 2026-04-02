#!/bin/bash
# Conditionally seed the built-in e-commerce schema.
# Set SEED_SCHEMA=false in .env to skip (e.g. when using BYOD dumps).

if [ "${SEED_SCHEMA:-true}" = "false" ]; then
    echo "SEED_SCHEMA=false — skipping built-in schema seed."
    exit 0
fi

echo "Seeding built-in e-commerce schema..."
psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /docker-entrypoint-initdb.d/seed/schema.sql
