#!/bin/bash
# Tear down the test Postgres container.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo ">>> Stopping test Postgres..."
docker compose -f docker-compose.test.yml down -v
echo ">>> Test DB stopped."
