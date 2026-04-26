.PHONY: help dev test test-unit test-integration test-all test-db-up test-db-down release deploy

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

dev: ## Run bot locally in polling mode
	USE_POLLING=true uv run python bot.py

test: test-unit ## Alias for test-unit (default test runner)

test-unit: ## Run unit tests (no DB, fast)
	uv run python -m pytest tests/ -m "not integration" --tb=short

test-integration: ## Run integration tests (requires Postgres via test-db-up)
	uv run python -m pytest tests/integration -m integration --tb=short --override-ini="addopts="

test-all: test-unit test-integration ## Run unit + integration tests

test-db-up: ## Bring up test Postgres + apply migrations
	./scripts/test-db-up.sh

test-db-down: ## Tear down test Postgres
	./scripts/test-db-down.sh

release: ## Create a release: bump version, tag, push → triggers deployment
	@echo "Current version:"
	@cat release-manifest.json | python3 -c "import sys,json; print(json.load(sys.stdin).get('version','0.0.0'))" 2>/dev/null || echo "0.0.0"
	@read -p "New version (e.g. 1.0.0): " VERSION; \
	if [ -z "$$VERSION" ]; then echo "Version required"; exit 1; fi; \
	echo "{\"version\": \"$$VERSION\", \"name\": \"murmur-bot\"}" > release-manifest.json; \
	git add -A; \
	git commit -m "release: v$$VERSION"; \
	git tag -a "v$$VERSION" -m "Release v$$VERSION"; \
	git push origin main --tags; \
	echo "✅ Release v$$VERSION pushed. GitHub Actions will deploy to Cloud Run."

deploy: ## Deploy directly to Cloud Run (without release)
	./scripts/deploy_cloud_run.sh
