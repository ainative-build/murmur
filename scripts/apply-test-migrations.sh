#!/bin/bash
# Apply Supabase migrations in numeric order to the test Postgres.
# Filenames are sorted lexically (001_..., 002_..., ..., 008_...) so a glob
# is the migration order.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${MURMUR_TEST_DB_PORT:-5433}"
DSN="postgresql://murmur:murmur@localhost:${PORT}/murmur_test"

cd "$REPO_ROOT"

# psql via the running container — keeps host clean of psql client requirement.
PSQL=(docker compose -f docker-compose.test.yml exec -T test-db psql -U murmur -d murmur_test -v ON_ERROR_STOP=1)

# Reset DB cleanly — drop public schema and recreate so migrations re-run idempotent.
echo ">>> Resetting public schema..."
"${PSQL[@]}" -c "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;" >/dev/null

for migration in supabase/migrations/*.sql; do
    name="$(basename "$migration")"
    echo ">>> Applying ${name}..."
    "${PSQL[@]}" < "$migration" >/dev/null
done

echo ">>> All migrations applied to ${DSN}"
