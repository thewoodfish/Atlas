.PHONY: install run-demo run-live test dashboard frontend wdk-service clean devnet fund-wallet

# ── Setup ─────────────────────────────────────────────────────────────────────
install:
	pip install -r requirements.txt
	cd atlas/dashboard/frontend && npm install --legacy-peer-deps
	cd wdk_service && npm install

# ── Run modes ─────────────────────────────────────────────────────────────────
run-demo:
	python main.py --demo

run-live:
	python main.py

run-no-dashboard:
	python main.py --no-dashboard

# ── WDK microservice ──────────────────────────────────────────────────────────
wdk-service:
	cd wdk_service && node server.js

# ── Dashboard ─────────────────────────────────────────────────────────────────
dashboard:
	cd atlas/dashboard/frontend && npm run dev

dashboard-build:
	cd atlas/dashboard/frontend && npm run build

# ── Tests ─────────────────────────────────────────────────────────────────────
test:
	python -m pytest tests/ -v --tb=short

test-coverage:
	python -m pytest tests/ -v --tb=short --cov=atlas --cov-report=term-missing

# ── Docker ────────────────────────────────────────────────────────────────────
docker-up:
	docker compose up --build

docker-down:
	docker compose down

# ── Devnet (Anvil mainnet fork) ───────────────────────────────────────────────
devnet:
	anvil --fork-url https://eth.drpc.org

fund-wallet:
	bash scripts/fund_wallet.sh

# ── Utilities ─────────────────────────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -f atlas.db logs/*.log

lint:
	python -m py_compile $$(find atlas -name "*.py" | tr '\n' ' ') && echo "Syntax OK"
