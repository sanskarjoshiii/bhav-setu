PY ?= python
VENV := .venv
ifeq ($(OS),Windows_NT)
	BIN := $(VENV)/Scripts
else
	BIN := $(VENV)/bin
endif

.PHONY: up down install initdb backfill train backtest api web seed test \
        check-phase0 check-phase1 check-phase2 check-phase3 check-phase4 \
        check-phase5 check-phase6 check-phase7 check-phase8 check-phase9 \
        check-phase10 check-phase11 check-phase12

# ── infrastructure ─────────────────────────────────────────────────────────
up:
	docker compose up -d
	docker compose ps

down:
	docker compose down

install:
	$(PY) -m venv $(VENV)
	$(BIN)/python -m pip install --upgrade pip
	$(BIN)/python -m pip install -r backend/requirements.txt

# ── pipeline ───────────────────────────────────────────────────────────────
initdb:
	$(BIN)/python scripts/init_db.py --force

backfill:
	$(BIN)/python scripts/backfill.py

train:
	$(BIN)/python scripts/train.py --from 2022-01-01 --promote

backtest:
	$(BIN)/python scripts/backtest.py

seed:
	$(BIN)/python scripts/seed_demo_data.py

# ── servers ────────────────────────────────────────────────────────────────
api:
	cd backend && ../$(BIN)/python -m uvicorn api.main:app --reload --port 8000

web:
	cd frontend && npm run dev

# ── tests ──────────────────────────────────────────────────────────────────
test:
	cd backend && ../$(BIN)/python -m pytest

check-phase0:
	cd backend && ../$(BIN)/python -m pytest tests/test_phase0_scaffold.py -v

check-phase1:
	cd backend && ../$(BIN)/python -m pytest tests/test_phase1_schema.py -v

check-phase2:
	cd backend && ../$(BIN)/python -m pytest tests/test_phase2_ingestion.py -v

check-phase3:
	cd backend && ../$(BIN)/python -m pytest tests/test_phase3_features.py -v

check-phase4:
	cd backend && ../$(BIN)/python -m pytest tests/test_phase4_model.py -v

check-phase5:
	cd backend && ../$(BIN)/python -m pytest tests/test_phase5_economics.py -v

check-phase6:
	cd backend && ../$(BIN)/python -m pytest tests/test_phase6_decision.py -v

check-phase7:
	cd backend && ../$(BIN)/python -m pytest tests/test_phase7_backtest.py -v

check-phase8:
	cd backend && ../$(BIN)/python -m pytest tests/test_phase8_api.py -v

check-phase9:
	cd backend && ../$(BIN)/python -m pytest tests/test_phase9_bot.py -v

check-phase10:
	cd frontend && npm run build

check-phase11:
	cd backend && ../$(BIN)/python -m pytest tests/test_phase11_whatsapp.py -v

check-phase12:
	cd backend && ../$(BIN)/python -m pytest tests/test_phase12_demo.py -v
