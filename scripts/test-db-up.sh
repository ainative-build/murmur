#!/bin/bash
# Bring up test Postgres container and apply all Supabase migrations.
# Idempotent: safe to run multiple times. Existing container is reused.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

PORT="${MURMUR_TEST_DB_PORT:-5433}"
DSN="postgresql://murmur:murmur@localhost:${PORT}/murmur_test"

echo ">>> Starting test Postgres on port ${PORT}..."
docker compose -f docker-compose.test.yml up -d test-db

echo ">>> Waiting for Postgres to be healthy..."
for _ in $(seq 1 60); do
    if docker compose -f docker-compose.test.yml exec -T test-db pg_isready -U murmur -d murmur_test >/dev/null 2>&1; then
        echo "  Postgres is ready."
        break
    fi
    sleep 1
done

echo ">>> Applying migrations..."
"${REPO_ROOT}/scripts/apply-test-migrations.sh"

echo ">>> Test DB ready: ${DSN}"
echo "Export with: export MURMUR_TEST_DB_DSN='${DSN}'"
