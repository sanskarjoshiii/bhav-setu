# PLAN.md — Bhav Setu, Round 1 Prototype

> **This document is the single source of truth for the Round 1 hackathon prototype.**
> It is written to be executed by Claude Code, phase by phase, in order.
> A human teammate performs the steps marked **MANUAL** — those are collected per phase and again in one master checklist at the top.

---

## Table of contents

- [0. Read this first — instructions for Claude Code](#0-read-this-first--instructions-for-claude-code)
- [1. What we are building in Round 1](#1-what-we-are-building-in-round-1)
- [2. Scope: in and out](#2-scope-in-and-out)
- [3. Technology stack](#3-technology-stack)
- [4. MASTER MANUAL CHECKLIST (do these before/while coding)](#4-master-manual-checklist)
- [5. Repository structure](#5-repository-structure)
- [Phase 0 — Environment and scaffold](#phase-0--environment-and-scaffold)
- [Phase 1 — Database schema and seed reference data](#phase-1--database-schema-and-seed-reference-data)
- [Phase 2 — Data ingestion, cleaning and audit](#phase-2--data-ingestion-cleaning-and-audit)
- [Phase 3 — Feature builder](#phase-3--feature-builder)
- [Phase 4 — Baselines and the forecasting model](#phase-4--baselines-and-the-forecasting-model)
- [Phase 5 — Net In-Hand economics engine](#phase-5--net-in-hand-economics-engine)
- [Phase 6 — Decision engine and explainer](#phase-6--decision-engine-and-explainer)
- [Phase 7 — Backtest and the ₹-uplift number](#phase-7--backtest-and-the--uplift-number)
- [Phase 8 — FastAPI backend](#phase-8--fastapi-backend)
- [Phase 9 — Bot engine and web chat simulator](#phase-9--bot-engine-and-web-chat-simulator)
- [Phase 10 — Next.js website](#phase-10--nextjs-website)
- [Phase 11 — WhatsApp Cloud API integration](#phase-11--whatsapp-cloud-api-integration)
- [Phase 12 — Seed demo data, polish, demo script](#phase-12--seed-demo-data-polish-demo-script)
- [13. Definition of done](#13-definition-of-done)
- [14. Troubleshooting](#14-troubleshooting)

---

## 0. Read this first — instructions for Claude Code

These rules apply to the whole project. Follow them without exception.

### Working method

1. **Work one phase at a time, in order.** Do not start Phase N+1 until every acceptance check in Phase N passes. Print the acceptance check results before moving on.
2. **At the start of each phase**, restate in two lines what you are about to build and which files you will create or modify. Then build it.
3. **At the end of each phase**, run the phase's acceptance command, paste the output, and make a git commit with the message `phase-N: <short description>`.
4. **When a phase has MANUAL steps that block you**, stop and print a clear message: `⛔ BLOCKED — human action required:` followed by the exact steps. Do not fake, mock, or work around a blocked credential unless the phase explicitly says a fallback is allowed.
5. **Never invent data.** If the government API returns nothing, say so and stop. Do not generate synthetic price data and present it as real. The only place synthetic data is allowed is `scripts/seed_demo_data.py`, and every row it creates must have `source='seed_demo'`.

### Code rules

6. **One feature function.** `backend/features/builder.py::build_features()` is used by training, backtesting and serving. Never write a second version. If serving needs something different, change the one function.
7. **All numbers that a human might want to tune live in YAML** under `config/`, never hardcoded in Python. This includes fees, transport rates, spoilage rates, grade factors, risk lambdas, model hyperparameters, and the list of mandis and crops.
8. **Point-in-time correctness is mandatory.** Any feature computed for date `D` may only use rows where `obs_date <= D`. Add an assertion in the feature builder that raises if this is violated.
9. **Type hints on every function.** Pydantic models for every API request and response.
10. **Errors are loud.** No bare `except:`. No silently returning `None` when data is missing — raise a typed exception or return an explicit `InsufficientData` result that the API layer converts to a clear message.
11. **Log every external call** (URL, status, row count) to stdout in a structured single line.
12. **Do not add a dependency** that is not in §3 without printing `⚠️ NEW DEPENDENCY: <name> because <reason>` first.

### Things that will fail the project — never do these

- Random train/test split on time-series data. Use walk-forward only.
- Forward-filling missing prices without setting `is_imputed = true`.
- Showing a farmer a single price number without a range and a confidence.
- Storing secrets in code. Everything goes in `.env`, which is gitignored.
- Building authentication, user accounts, an admin panel, or CI. Out of scope for Round 1.

### Definition of "done" for a file

A file is done when: it runs, it has type hints, its numbers come from config, and the phase acceptance command exercises it.

---

## 1. What we are building in Round 1

A working prototype of **Bhav Setu** — a selling-decision engine for Indian farmers.

The demo path a judge will walk:

```
1.  Opens the website on a laptop or phone
2.  Sees a live price chart with a forecast fan (P10–P90) for onion at 5 Nashik mandis
3.  Enters a lot: 80 quintals of onion, grade B, stored in a shed
4.  Gets a decision: "Sell 50 qtl today at Lasalgaon, hold 30 for 9 days"
       — with net ₹/quintal, expected extra rupees, a one-line reason, confidence %
5.  Sees the MANDI COMPARISON table where ranking by gross flips when ranked by net
6.  Sees the BACKTEST page: "+8.4% vs selling immediately, 64% win rate"
7.  Clicks "Continue on WhatsApp" → deep link opens WhatsApp with a prefilled message
8.  Sends it → the bot replies in Marathi with the same recommendation
9.  Bot asks "what price did you actually get?" → judge replies a number
10. Website's Transparency page updates with the new report
```

Step 8 is the risky one (Meta approval, tunnels, wifi). Therefore we also build a **web chat simulator** at `/chat` that runs the exact same bot engine. If WhatsApp fails on demo day, the story is unchanged.

---

## 2. Scope: in and out

### IN — build all of this

| Area | Round 1 scope |
|---|---|
| Crop | **Onion only** (config supports more; adding tomato must be a YAML edit, not a code change) |
| Geography | **5 mandis** in the Nashik belt, Maharashtra |
| History | 2–3 years of daily price + arrivals |
| Model | LightGBM quantile, horizons 1 / 3 / 7 / 15, P10 / P50 / P90 |
| Economics | Full Net In-Hand engine with spoilage, fees, transport, holding cost |
| Decision | sell / hold / split optimiser with risk aversion and hard constraints |
| Evaluation | Walk-forward validation + ₹-uplift backtest |
| Shock radar | ~20 hand-curated events in a CSV, wired as model features |
| Website | 5 pages: Home, Advisor, Mandi Compare, Accuracy, Transparency, plus `/chat` |
| Bot | Shared bot engine, 5 conversation flows, Marathi + English |
| WhatsApp | Cloud API test number, deep-link entry from the website |
| Feedback loop | Sale report intake + transparency score (seeded to ~30 reports) |

### OUT — do not build

Authentication · user accounts · admin panel · payments · mobile app · multi-state support · satellite/NDVI · photo grading · IVR · truck pooling · CI/CD · Kubernetes · Alembic migrations (a single `schema.sql` is enough) · live DGFT scraping (CSV is enough).

---

## 3. Technology stack

Claude Code: use exactly these. Do not substitute without asking.

### Backend
| Thing | Version / package | Why |
|---|---|---|
| Python | 3.11 | LightGBM + pandas stability |
| FastAPI | `fastapi>=0.110` | API layer |
| Uvicorn | `uvicorn[standard]` | ASGI server |
| Pydantic | v2 | request/response schemas |
| SQLAlchemy | 2.0, **Core with `text()`**, sync engine | no ORM ceremony needed at this size |
| psycopg | `psycopg[binary]>=3.1` | Postgres driver |
| pandas | `>=2.1` | feature building |
| numpy | `>=1.26` | |
| LightGBM | `>=4.1` | the forecasting model |
| scikit-learn | `>=1.4` | metrics, preprocessing |
| SHAP | `>=0.44` | explanation generation |
| httpx | `>=0.27` | all HTTP calls |
| PyYAML | `>=6.0` | config loading |
| RapidFuzz | `>=3.6` | mandi/commodity name resolution |
| python-dotenv | | env loading |
| APScheduler | `>=3.10` | daily jobs |
| redis | `>=5.0` | bot session state |
| pytest | `>=8.0` | acceptance tests |
| rich | | readable CLI output for audit/backtest reports |

### Frontend
| Thing | Version | Why |
|---|---|---|
| Next.js | 14, **App Router** | website |
| React | 18 | |
| TypeScript | 5 | |
| Tailwind CSS | 3 | styling |
| Recharts | 2 | line chart + forecast fan (use `Area` for the band) |
| lucide-react | | icons |

### Infrastructure
| Thing | Notes |
|---|---|
| PostgreSQL 15 | via Docker Compose |
| Redis 7 | via Docker Compose, bot session state only |
| Docker + Docker Compose | one command to bring up DB |
| cloudflared **or** ngrok | public HTTPS tunnel for the WhatsApp webhook |

### External services
| Service | Needed for | Cost |
|---|---|---|
| data.gov.in API | live/recent Agmarknet prices | free, needs registration |
| Kaggle | historical backfill CSV | free, needs account |
| Open-Meteo | weather, historical + forecast | free, **no key needed** |
| OSRM public demo server | road distance between village and mandi | free, rate limited — **cache every result** |
| Meta WhatsApp Cloud API | the bot | free tier, test number |

---

## 4. MASTER MANUAL CHECKLIST

Do these yourself. Items marked ⏰ have lead time — start them on day 1 even if coding hasn't reached that phase.

### Before Phase 0
- [ ] Install **Docker Desktop** and confirm `docker --version` works
- [ ] Install **Python 3.11** and confirm `python3.11 --version`
- [ ] Install **Node.js 20** and confirm `node --version`
- [ ] Install **git**

### ⏰ Start on day 1 — these have waiting time

- [ ] **data.gov.in API key**
  1. Go to `https://data.gov.in` → Sign Up → verify email
  2. Log in → click your profile → **My Account → API Key** (some accounts show it under "Generate API Key")
  3. Copy the key. It is a long alphanumeric string.
  4. Also open `https://www.data.gov.in/catalog/current-daily-price-various-commodities-various-markets-mandi`, click **Data API**, and copy the **resource ID** from the URL (a UUID-looking string).
  5. Paste both into `.env` as `DATA_GOV_IN_API_KEY` and `AGMARKNET_RESOURCE_ID`.
  - ⚠️ The publicly shown demo key is heavily row-limited. You need your own.

- [ ] **Kaggle historical mandi dataset** (this is what you actually train on — the API mostly serves recent data)
  1. Create a Kaggle account
  2. Search for a daily Indian mandi/commodity price dataset with several years of history (e.g. "Daily Wholesale Commodity Prices India Mandis")
  3. Download the CSV
  4. Place it at `data/raw/mandi_history.csv`
  5. Open it once and note the exact column names — tell Claude Code what they are; it will write the mapping into `config/sources.yaml`
  - If the dataset covers a different state, that is fine — just pick 5 mandis with dense onion history from whatever it covers, and update `config/mandis.yaml`.

- [ ] **Meta WhatsApp Cloud API test number**
  1. Go to `https://developers.facebook.com` → log in with a Facebook account
  2. **My Apps → Create App → Business → Next**, give it a name (e.g. "BhavSetu")
  3. In the app dashboard, find **WhatsApp** → **Set up**
  4. Meta gives you a **test phone number** and a **temporary access token** (valid 24h)
  5. Copy: `Phone number ID`, `WhatsApp Business Account ID`, `Temporary access token`
  6. Under **API Setup → To**, click **Manage phone number list** and add the phone numbers of everyone on your team who will demo. ⚠️ **The test number can only message numbers you register here — maximum 5.** Add them now.
  7. Under **App Settings → Basic**, copy the **App Secret**
  8. Invent a random string for `WHATSAPP_VERIFY_TOKEN` (e.g. `bhavsetu_verify_9x2k`) — you will type the same string into Meta later
  9. Put all of these in `.env`
  - ⚠️ The temporary token expires every 24 hours. On demo day, regenerate it in the morning and update `.env`.

- [ ] **Install a tunnel** (needed only in Phase 11)
  - Easiest, no account: `brew install cloudflared` (macOS) or download from Cloudflare's site (Windows/Linux)
  - Alternative: `ngrok` (needs a free account and authtoken)

### Data verification (do this in Phase 2, it needs your judgement)
- [ ] Open the audit report Claude Code generates and confirm the 5 chosen mandis actually have dense onion data. If one is sparse, swap it for another and tell Claude Code to update `config/mandis.yaml`.

### Cost model verification (Phase 5) — **do not skip, your headline number depends on it**
- [ ] Search for the current **APMC commission percentage** and **market cess** for Maharashtra (and specifically Nashik district APMC if you can find it)
- [ ] Search for a typical **hamali (loading) charge per quintal** for onion in Nashik mandis
- [ ] Search for a typical **truck hire rate per km** for a ~9 tonne truck in Maharashtra
- [ ] Put the numbers into `config/cost_model.yaml` and note your source in a comment next to each. A judge will ask where the numbers came from.

### Shock events (Phase 2)
- [ ] Fill `data/manual/shock_events.csv` with ~20 real onion policy events from the last 3 years (export bans, minimum export price orders, export relaxations, stock limits, buffer releases). One line each: date, type, direction, magnitude, source URL. This takes about an hour of searching and it directly improves your model.

---

## 5. Repository structure

Claude Code: create exactly this tree in Phase 0.

```
bhav-setu/
├── PLAN.md                     # this file
├── README.md
├── Makefile
├── docker-compose.yml
├── .env.example
├── .gitignore
│
├── config/
│   ├── app.yaml                # horizons, quantiles, top-K mandis, cache TTLs
│   ├── mandis.yaml             # the 5 mandis: name, lat, lon, district, state
│   ├── crops.yaml              # onion params: k_c, grade factors, max hold days
│   ├── cost_model.yaml         # fees, transport, storage, interest
│   ├── model.yaml              # LightGBM hyperparameters
│   ├── sources.yaml            # API endpoints, resource ids, CSV column mapping
│   └── decision.yaml           # risk lambdas, constraint thresholds
│
├── data/
│   ├── raw/                    # gitignored — mandi_history.csv goes here
│   ├── manual/
│   │   ├── shock_events.csv
│   │   └── festivals.csv
│   └── artifacts/              # gitignored — trained models, backtest reports
│
├── db/
│   └── schema.sql
│
├── backend/
│   ├── requirements.txt
│   ├── pytest.ini
│   ├── core/
│   │   ├── config.py           # loads all YAML + .env into typed objects
│   │   ├── db.py               # engine, get_conn()
│   │   ├── logging.py
│   │   └── errors.py           # InsufficientData, IngestionError, etc.
│   ├── ingestion/
│   │   ├── agmarknet.py
│   │   ├── backfill_csv.py
│   │   ├── weather.py
│   │   ├── shocks.py
│   │   ├── routing.py          # OSRM road distance + cache table
│   │   ├── cleaners.py
│   │   ├── entity_resolution.py
│   │   └── audit.py            # generates the data audit report
│   ├── features/
│   │   ├── registry.py         # FEATURE_NAMES list — single source of truth
│   │   └── builder.py          # build_features() — used by train AND serve
│   ├── ml/
│   │   ├── baselines.py
│   │   ├── dataset.py          # builds the training matrix
│   │   ├── train.py
│   │   ├── predict.py
│   │   ├── explain.py
│   │   └── registry.py         # model_registry table read/write
│   ├── economics/
│   │   ├── spoilage.py
│   │   └── net_realisation.py
│   ├── decision/
│   │   ├── engine.py
│   │   ├── constraints.py
│   │   └── confidence.py
│   ├── transparency/
│   │   └── scoring.py
│   ├── bot/
│   │   ├── engine.py           # ⭐ pure function: (session, text) -> reply
│   │   ├── intents.py
│   │   ├── session.py          # Redis-backed state
│   │   └── locales/
│   │       ├── mr.yaml
│   │       └── en.yaml
│   ├── backtest/
│   │   ├── scenarios.py
│   │   ├── runner.py
│   │   └── report.py
│   ├── api/
│   │   ├── main.py
│   │   ├── deps.py
│   │   ├── schemas.py
│   │   └── routers/
│   │       ├── mandis.py
│   │       ├── forecast.py
│   │       ├── recommend.py
│   │       ├── sale_reports.py
│   │       ├── transparency.py
│   │       ├── accuracy.py
│   │       ├── chat.py         # web simulator -> bot engine
│   │       └── whatsapp.py     # webhook -> bot engine
│   └── tests/
│       ├── test_phase1_schema.py
│       ├── test_phase2_ingestion.py
│       ├── test_phase3_features.py
│       ├── test_phase4_model.py
│       ├── test_phase5_economics.py
│       ├── test_phase6_decision.py
│       ├── test_phase8_api.py
│       └── test_phase9_bot.py
│
├── scripts/
│   ├── init_db.py
│   ├── backfill.py
│   ├── train.py
│   ├── backtest.py
│   ├── seed_demo_data.py
│   └── daily_job.py
│
└── frontend/
    ├── package.json
    ├── tailwind.config.ts
    ├── app/
    │   ├── layout.tsx
    │   ├── page.tsx                 # Home
    │   ├── advisor/page.tsx
    │   ├── compare/page.tsx
    │   ├── accuracy/page.tsx
    │   ├── transparency/page.tsx
    │   └── chat/page.tsx            # WhatsApp-lookalike simulator
    ├── components/
    │   ├── ForecastChart.tsx
    │   ├── NetComparisonTable.tsx
    │   ├── RecommendationCard.tsx
    │   ├── LotForm.tsx
    │   ├── WhatsAppCTA.tsx
    │   └── ChatWindow.tsx
    └── lib/
        ├── api.ts
        └── types.ts
```

---

# Phase 0 — Environment and scaffold

**Goal:** an empty but complete, runnable skeleton with config loading and a healthy database.

### Claude Code builds

1. The full directory tree from §5, with `.gitkeep` in empty dirs.
2. `.gitignore` — must include `.env`, `data/raw/`, `data/artifacts/`, `__pycache__/`, `node_modules/`, `.next/`, `*.pkl`.
3. `docker-compose.yml`:
```yaml
services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_USER: bhav
      POSTGRES_PASSWORD: bhav
      POSTGRES_DB: bhav
    ports: ["5433:5432"]          # 5433 to avoid clashing with a local postgres
    volumes: ["pgdata:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U bhav"]
      interval: 5s
      retries: 10
  redis:
    image: redis:7-alpine
    ports: ["6380:6379"]
volumes:
  pgdata: {}
```
4. `.env.example` with every variable listed, empty values, and a one-line comment each.
5. `backend/requirements.txt` with pinned versions from §3.
6. `backend/core/config.py` — loads every YAML in `config/` plus `.env` into a single frozen `Settings` object accessible as `from core.config import settings`. Must fail loudly at import time if a required env var is missing.
7. `backend/core/db.py` — SQLAlchemy engine + `get_conn()` context manager.
8. `backend/core/logging.py` — one-line structured logging helper.
9. All seven config YAML files, populated with sensible defaults (values below in the relevant phases).
10. `Makefile` with targets: `up`, `down`, `install`, `initdb`, `backfill`, `train`, `backtest`, `api`, `web`, `seed`, `test`, and one `check-phaseN` per phase.

### Config values to write now

`config/mandis.yaml` (verify coordinates roughly; exact values are not critical):
```yaml
mandis:
  - name: Lasalgaon
    district: Nashik
    state: Maharashtra
    lat: 20.1436
    lon: 74.2372
  - name: Pimpalgaon Baswant
    district: Nashik
    state: Maharashtra
    lat: 20.1667
    lon: 73.9833
  - name: Nashik
    district: Nashik
    state: Maharashtra
    lat: 19.9975
    lon: 73.7898
  - name: Yeola
    district: Nashik
    state: Maharashtra
    lat: 20.0424
    lon: 74.4894
  - name: Chandvad
    district: Nashik
    state: Maharashtra
    lat: 20.3300
    lon: 74.2400

reference_village:
  name: Vinchur
  lat: 20.1100
  lon: 74.3200
```

`config/app.yaml`:
```yaml
horizons: [1, 3, 7, 15]
quantiles: {p10: 0.10, p50: 0.50, p90: 0.90}
top_k_mandis: 5
max_distance_km: 150
default_language: mr
history_lookback_days: 400
```

### MANUAL steps for you

1. `cp .env.example .env`
2. Paste in your `DATA_GOV_IN_API_KEY` and `AGMARKNET_RESOURCE_ID`
3. Leave WhatsApp variables blank for now — Phase 11 uses them
4. Run `make up` and wait for `docker compose ps` to show both containers healthy
5. Run `make install`

### Acceptance check

```bash
make check-phase0
```
Must confirm: all directories exist, `python -c "from core.config import settings; print(settings.app.horizons)"` prints `[1, 3, 7, 15]`, Postgres accepts a connection, Redis responds to PING.

### 🟢 What we just did, in simple words

We built the empty house before putting anything in it. Every folder now exists, the database is running inside Docker, and all the numbers we might want to change later — fee percentages, which mandis we cover, how many days ahead we predict — are sitting in plain text files under `config/` instead of being buried in code. This matters because during the hackathon you will want to change these numbers live in front of judges, and now you can do that by editing one line.

---

# Phase 1 — Database schema and seed reference data

**Goal:** the database has all tables and knows about our 5 mandis, onion, MSP, festivals.

### Claude Code builds

1. `db/schema.sql` with these tables (use the DDL from the project README, but only this subset for Round 1):

`states`, `mandis`, `commodities`, `commodity_aliases`, `msp_schedule`, `price_observations`, `weather_daily`, `shock_events`, `festivals`, `distance_cache`, `forecasts`, `model_registry`, `farmers`, `lots`, `recommendations`, `sale_reports`, `transparency_scores`, `bot_sessions`, `ingestion_runs`.

Key points the schema must get right:
- `price_observations` unique on `(obs_date, mandi_id, commodity_id, variety, grade)`, with `is_imputed BOOLEAN`, `suspect BOOLEAN`, `source TEXT NOT NULL`, `arrival_qtl NUMERIC`, and index on `(commodity_id, mandi_id, obs_date DESC)`.
- `distance_cache(from_lat, from_lon, to_lat, to_lon, road_km, duration_min)` with a primary key on the four coordinates rounded to 4 decimals — OSRM is rate-limited, we call it once per pair ever.
- `bot_sessions(phone_e164 PK, state TEXT, context JSONB, updated_at)` — Redis holds the hot copy, Postgres is the durable one so a Redis restart during the demo does not wipe a conversation.

2. `scripts/init_db.py` — drops and recreates everything (`--force` flag required to drop), then seeds:
   - `states`: Maharashtra with fee percentages read from `config/cost_model.yaml`
   - `mandis`: from `config/mandis.yaml`
   - `commodities`: onion (+ aliases: "Onion", "Onion Red", "Onion(Big)", "Onion Local", "Kanda", "कांदा")
   - `festivals`: from `data/manual/festivals.csv`
   - `msp_schedule`: onion has no MSP — insert nothing, but the table must exist and the MSP check must handle "no MSP for this crop" gracefully

3. `data/manual/festivals.csv` — pre-populate with Diwali, Dussehra, Navratri, Ganesh Chaturthi, Sankranti, Holi, Ramzan Eid, Bakri Eid, Onam for 2022–2026, with a `demand_effect` column of `1` for vegetables.

### MANUAL steps for you

1. Run `make initdb`
2. Open a SQL client (or `docker compose exec postgres psql -U bhav`) and run `SELECT name FROM mandis;` — confirm 5 rows

### Acceptance check

```bash
make check-phase1
```
Runs `backend/tests/test_phase1_schema.py`: every table exists, 5 mandis seeded, onion seeded with at least 5 aliases, festivals table non-empty, `distance_cache` accepts an insert.

### 🟢 What we just did, in simple words

We designed the filing cabinet. Every kind of information the system will ever touch — daily prices, weather, policy events, farmers, what we recommended, what price they actually got — now has a labelled drawer with rules about what can go in it. We also filled in the things that never change: which five markets we cover, what onion is called in five different spellings, and when the festivals fall. The important one to notice is `sale_reports` — that empty table is the thing no competing product has.

---

# Phase 2 — Data ingestion, cleaning and audit

**Goal:** 2–3 years of clean onion price and arrival history for 5 mandis, plus weather and shock events, in the database — and an honest audit report telling us how good it is.

**This phase is the foundation. Spend the time. A model on dirty data is worthless.**

### Claude Code builds

#### 2.1 `backend/ingestion/backfill_csv.py`
Loads `data/raw/mandi_history.csv`. Column mapping comes from `config/sources.yaml` (the human will tell you the real column names). Steps:
- read CSV in chunks
- filter to onion (via alias matching) and to the 5 configured mandis (via fuzzy match, see 2.4)
- normalise units → prices to ₹/quintal, arrivals to quintals; if the source is in tonnes, multiply by 10; record the original unit
- pass every row through `cleaners.validate_row()`
- upsert into `price_observations` with `source='csv_backfill'`

#### 2.2 `backend/ingestion/agmarknet.py`
Pulls recent data from `https://api.data.gov.in/resource/{resource_id}` with params `api-key`, `format=json`, `limit`, `offset`, `filters[state]=Maharashtra`, `filters[commodity]=Onion`. Paginate until fewer than `limit` rows come back. Retry with exponential backoff (1,2,4,8s; 5 attempts). Upsert with `source='agmarknet_api'`. Log the run into `ingestion_runs`.

#### 2.3 `backend/ingestion/cleaners.py`
Implement each rule as a named function so the audit report can count rejections by rule:

| Rule | Condition | Action |
|---|---|---|
| `reject_nonpositive` | `modal_price <= 10` | reject |
| `reject_absurd` | `modal_price > 20 × trailing_median_90` | reject |
| `reject_inconsistent` | `min > modal` or `modal > max` | reject |
| `flag_suspect` | rolling z-score of daily log-return > 6 | keep, `suspect=true` |
| `impute_gap` | missing day, gap ≤ 3 days | forward-fill, `is_imputed=true` |
| `leave_gap` | missing day, gap > 3 days | leave missing |

⚠️ **Do not winsorise price spikes.** A tripling onion price is real and is exactly the event we want to predict. Only remove physically impossible values.

#### 2.4 `backend/ingestion/entity_resolution.py`
`resolve_mandi(raw_name, district, state) -> mandi_id | None` using RapidFuzz `token_sort_ratio` against `mandis.normalised_name`:
- score ≥ 95 → auto-map
- 90–94 → map, but write to `data/artifacts/fuzzy_review.csv` for a human to eyeball
- < 90 → return None, count as unmatched

Same approach for commodity via `commodity_aliases`.

#### 2.5 `backend/ingestion/weather.py`
Open-Meteo, **no API key needed**:
- historical: `https://archive-api.open-meteo.com/v1/archive?latitude=..&longitude=..&start_date=..&end_date=..&daily=precipitation_sum,temperature_2m_max,temperature_2m_min`
- forecast: `https://api.open-meteo.com/v1/forecast?latitude=..&longitude=..&daily=precipitation_sum,temperature_2m_max,temperature_2m_min&forecast_days=16`

Store forecast rows with `is_forecast=true`. **Never overwrite a historical row with a forecast row.**

#### 2.6 `backend/ingestion/shocks.py`
Round 1 = read `data/manual/shock_events.csv` only. No scraping. Columns: `event_date, event_type, commodity, scope, direction, magnitude, decay_days, title, source_url`.

#### 2.7 `backend/ingestion/routing.py`
`road_distance_km(from_lat, from_lon, to_lat, to_lon) -> float`:
- check `distance_cache` first
- else call `http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false`
- store in cache
- on failure, fall back to haversine × 1.3 and log a warning (never crash the demo over a routing call)

#### 2.8 `backend/ingestion/audit.py` — **the deliverable of this phase**
Generates `data/artifacts/data_audit.md` and prints a `rich` table containing, per mandi:
- date range covered, total rows
- % of business days present vs missing
- % imputed, % suspect, % rejected (by rule)
- min / median / max modal price, and the same for arrivals
- longest continuous gap in days
- a verdict line: `USABLE` / `THIN` / `UNUSABLE`

#### 2.9 `scripts/backfill.py`
Orchestrates: CSV backfill → Agmarknet top-up → weather → shocks → audit. Idempotent, safe to rerun.

### MANUAL steps for you

1. Download the Kaggle CSV → place at `data/raw/mandi_history.csv`
2. Open it, note the exact column headers, tell Claude Code so it writes the mapping into `config/sources.yaml`
3. Fill `data/manual/shock_events.csv` with ~20 real onion policy events (see master checklist)
4. Run `make backfill` (takes a few minutes)
5. **Open `data/artifacts/data_audit.md` and read it.** This is a judgement call only you can make:
   - If a mandi shows `THIN` or `UNUSABLE`, pick a replacement mandi with denser onion data from the CSV and update `config/mandis.yaml`, then rerun
   - Aim for at least 3 mandis with ≥ 60% of business days covered over 2+ years
6. Skim `data/artifacts/fuzzy_review.csv` — confirm nothing absurd got matched

### Acceptance check

```bash
make check-phase2
```
Must assert: ≥ 500 rows per mandi for at least 3 mandis; no `modal_price <= 10` anywhere; no rows where `min > modal`; weather rows exist for every mandi; ≥ 15 shock events loaded; audit file exists.

### 🟢 What we just did, in simple words

We went and collected the actual data — three years of what onion sold for every day in five real markets, how much arrived, what the weather was, and when the government banned exports. Then we cleaned it, because government data is genuinely messy: missing days, zero prices, the same market spelled four different ways. The most important output here is not the data, it's the **audit report** — an honest page telling us exactly how much of the data is real and how much is patched. If a judge asks "how good is your data?", you open that file instead of guessing. Teams that skip this step build models on garbage and don't find out until the demo.

---

# Phase 3 — Feature builder

**Goal:** one function that turns (date, mandi, commodity) into a row of numbers, used identically by training and by the live API.

### Claude Code builds

#### 3.1 `backend/features/registry.py`
```python
FEATURE_NAMES: list[str] = [...]      # exact ordered list
CATEGORICAL_FEATURES: list[str] = ["mandi_id", "commodity_id", "dow", "month"]
```
Everything downstream imports from here. If a feature name appears anywhere else as a string literal, that is a bug.

#### 3.2 `backend/features/builder.py`

```python
def build_features(as_of: date, mandi_id: int, commodity_id: int,
                   conn) -> dict[str, float]:
    """
    Point-in-time correct. Uses ONLY rows with obs_date <= as_of.
    Used by training, backtesting AND serving. There is no other version.
    Raises InsufficientData if fewer than 60 real observations in lookback.
    """
```

Feature groups to implement (all of them — this is what beats the other teams):

**A. Price history**
`lag_1, lag_3, lag_7, lag_14, lag_30` (log returns), `roll_mean_7/14/30` (of log price), `roll_std_7/30`, `price_vs_ma30`, `days_since_max_90`, `days_since_min_90`, `spread_pct` = `(max-min)/modal`

**B. Arrivals — the leading indicator other teams ignore**
`arr_lag_1/3/7` (log change), `arr_vs_ma30`, `arr_zscore_seasonal` (vs same week-of-year historical mean), `arr_momentum` (slope of 7-day linear fit on log arrivals), `price_arrival_elasticity` (rolling 60-day OLS coefficient of Δlog price on Δlog arrivals)

**C. Cross-mandi**
`nbr_price_mean_k4` (mean modal of the other 4 mandis), `price_vs_nbr` = `log(own/neighbour_mean)`, `nbr_arr_change`

**D. Calendar**
`dow`, `month`, `week_of_year`, `days_to_festival`, `festival_demand_effect`, `harvest_season_flag` (from `config/crops.yaml` season windows)

**E. Weather**
`rain_7d_sum`, `rain_30d_sum`, `rain_forecast_7d` (use `is_forecast` rows — legitimate, it was available at the time), `tmax_7d_mean`, `unseasonal_rain_flag`

**F. Shock**
`shock_active_bearish`, `shock_active_bullish` — decayed sums:
```
Σ over events with event_date <= as_of:
    magnitude × exp( −(as_of − event_date) / τ ),   τ = decay_days / 3
```
split by sign of `direction`. Plus `days_since_shock`.

**G. Entity**
`mandi_id`, `commodity_id`, `perishability_class`, `mandi_liquidity` (mean arrivals last 90d), `mandi_data_quality` (share of non-imputed in last 90d)

**H. Guards**
`days_since_observation`, `imputed_share_14d`

#### 3.3 Point-in-time assertion
Inside the function, after loading the series:
```python
assert series["obs_date"].max() <= as_of, "LEAKAGE: future data in feature window"
```

#### 3.4 `backend/ml/dataset.py`
```python
def build_training_matrix(start: date, end: date, horizons: list[int]) -> pd.DataFrame
```
Loops every (mandi, commodity) × every business day × every horizon, calls `build_features`, attaches the label `y = log(price[t+h] / price[t])`, drops rows where the label is missing. Caches the result to `data/artifacts/train_matrix.parquet`.

### MANUAL steps for you

None. Just review the printed feature count.

### Acceptance check

```bash
make check-phase3
```
`test_phase3_features.py` must assert:
- `build_features()` returns exactly `len(FEATURE_NAMES)` keys, in order
- calling it with `as_of = D` gives an identical result whether the DB contains data after `D` or not (leakage test — insert a fake future row, rebuild, compare)
- training matrix has ≥ 3,000 rows and no infinite values
- `InsufficientData` is raised for a mandi with no history

### 🟢 What we just did, in simple words

This is the part that turns raw prices into things a model can learn from. On its own, "yesterday's price was ₹1,860" tells a model almost nothing. But "arrivals are 22% below the monthly average, prices at neighbouring markets are 4% higher, Diwali is 11 days away, and an export ban was announced 6 days ago" — that's a picture. We built about 40 such signals. The single most important design decision here is that **the same function** produces these signals when training and when answering a live question. Most student projects write two versions, they drift apart, and the live system quietly performs far worse than the notebook claimed. We will not have that bug. The leakage test in the acceptance check is what guarantees it.

---

# Phase 4 — Baselines and the forecasting model

**Goal:** trained P10/P50/P90 models for 4 horizons that provably beat naive baselines, validated walk-forward.

### Claude Code builds

#### 4.1 `backend/ml/baselines.py` — **build these first, before any ML**
`naive` (price[t+h] = price[t]), `seasonal_naive` (= price[t+h−365]), `drift` (linear extrapolation of last 30 days), `ma7`. Each returns predictions on the same validation folds so the comparison is apples to apples.

#### 4.2 `backend/ml/train.py`
- Target: `y = log(price[t+h] / price[t])`. Never train on raw price.
- 12 models: `{p10,p50,p90} × {1,3,7,15}`, LightGBM `objective='quantile'` with the matching `alpha`.
- Hyperparameters from `config/model.yaml`:
```yaml
lightgbm:
  learning_rate: 0.05
  num_leaves: 63
  min_data_in_leaf: 40
  feature_fraction: 0.8
  bagging_fraction: 0.8
  bagging_freq: 1
  lambda_l2: 1.0
  num_boost_round: 800
  early_stopping_rounds: 60
```
- Categorical features passed via LightGBM's native `categorical_feature`.
- **One global model**, not one per mandi. `mandi_id` and `commodity_id` are features.

#### 4.3 Walk-forward validation with purge
```
Fold 1: train [start .. T-9mo]   validate [T-9mo .. T-6mo]
Fold 2: train [start .. T-6mo]   validate [T-6mo .. T-3mo]
Fold 3: train [start .. T-3mo]   validate [T-3mo .. T]
```
Insert a **purge gap of `h` days** between train end and validation start, otherwise a 15-day label overlaps the training window. Never use `train_test_split` or K-fold.

#### 4.4 Metrics — `backend/ml/train.py` prints and stores this table

| | naive | seasonal | ma7 | LightGBM |
|---|---|---|---|---|
| MAPE h=1 | | | | |
| MAPE h=7 | | | | |
| MAPE h=15 | | | | |
| Pinball loss | | | | |
| PICP (P10–P90) | — | — | — | target ≈ 0.80 |
| Directional accuracy h=7 | | | | target > 0.60 |

#### 4.5 `backend/ml/predict.py`
```python
def predict_quantiles(as_of, mandi_id, commodity_id, horizons) -> list[Forecast]
```
- builds features via the shared builder
- predicts log-return, inverts: `price_hat = current_price × exp(y_hat)`
- **sorts p10/p50/p90 before returning** (independently trained quantiles occasionally cross)
- writes rows into `forecasts`

#### 4.6 `backend/ml/explain.py`
SHAP `TreeExplainer` on the P50 model. Take the top 3 contributors, map to templates in `config/decision.yaml`:
```yaml
explanation_templates:
  arr_vs_ma30: "arrivals are {pct}% {direction} than normal"
  days_to_festival: "{festival} demand starts in {n} days"
  shock_active_bearish: "a policy announcement {n} days ago is pushing prices down"
  rain_forecast_7d: "heavy rain is expected in the next few days"
  price_vs_nbr: "nearby markets are paying {pct}% more"
  roll_std_30: "prices have been swinging a lot this month"
```
Return **two clauses maximum**, joined with "and". No jargon, no numbers a farmer can't act on.

#### 4.7 `backend/ml/registry.py`
Saves the model bundle to `data/artifacts/models/{version}/`, writes metrics JSON into `model_registry`, and promotes to `is_active` **only if** pinball loss beats the current active model on the most recent fold.

#### 4.8 `scripts/train.py`
CLI: `python scripts/train.py --from 2022-01-01 --to <today> --promote`

### MANUAL steps for you

1. Run `make train`
2. **Read the metrics table.** Sanity targets: h=1 MAPE under ~5%, h=7 under ~10%, PICP between 0.72 and 0.88.
3. If LightGBM does not beat `naive` at h=7, do not proceed — tell Claude Code, and the likely causes are: too little data, a leakage-free-but-broken feature, or wrong target. Fix it before Phase 5.
4. Screenshot this table. It goes in your deck.

### Acceptance check

```bash
make check-phase4
```
Asserts: 12 model files exist; LightGBM pinball loss < naive pinball loss at every horizon; `0.65 ≤ PICP ≤ 0.92`; `predict_quantiles` returns `p10 ≤ p50 ≤ p90` for 100 random cases; one model version is marked active.

### 🟢 What we just did, in simple words

We taught the system to forecast — but with two twists that matter. First, before training anything clever, we built four dumb baselines ("tomorrow will be the same as today"). If our fancy model can't beat a dumb rule, we need to know immediately, and now we do. Judges notice this; it signals you know what you're doing. Second, we never predict a single number. We predict a **range**: a low case, a most-likely case and a high case. That's not a technical detail, it's honesty — nobody can predict onion prices exactly, and pretending otherwise is how you give a farmer advice that ruins him. The range also feeds directly into the risk logic in Phase 6.

---

# Phase 5 — Net In-Hand economics engine

**Goal:** convert a predicted mandi price into the money that actually reaches the farmer. **This is the differentiator — get it right.**

### Claude Code builds

#### 5.1 `backend/economics/spoilage.py`
```python
def spoilage_fraction(k_c: float, days: int, storage: str, tmax_mean: float) -> float:
    f_storage = cfg.storage_factor[storage]      # ambient 1.0, shed 0.7, cold_store 0.25
    f_temp    = 1 + 0.04 * max(0.0, tmax_mean - 30)
    return 1 - math.exp(-k_c * f_storage * f_temp * days)
```

#### 5.2 `backend/economics/net_realisation.py`
```python
@dataclass(frozen=True)
class NetResult:
    gross: float
    deductions: float
    transport: float
    holding: float
    spoilage_qtl: float
    net_total: float
    net_per_qtl: float
    breakdown: dict        # every component, for the UI

def net_in_hand(price_per_qtl, qty_qtl, days_held, mandi, commodity,
                farmer_ctx, tmax_mean, pooled_with: int = 1) -> NetResult
```

The formula, exactly:
```
q_eff       = qty × (1 − spoilage_fraction(...))
gross       = price_per_qtl × q_eff × grade_factor[grade]

pct_fees    = (commission_pct + apmc_cess_pct + other_fees_pct) / 100
per_qtl_fee = hamali_per_qtl + weighing_per_qtl + packing_per_qtl
deductions  = gross × pct_fees + q_eff × per_qtl_fee

trucks      = ceil(q_eff / truck_capacity_qtl)
transport   = trucks × road_km × transport_per_km / max(pooled_with, 1)

holding     = storage_cost_per_qtl_per_day[storage] × qty × days_held
            + gross × (interest_rate_annual / 365) × days_held

net_total   = gross − deductions − transport − holding
net_per_qtl = net_total / qty            ← note: divided by ORIGINAL qty, so
                                            spoilage shows up as a lower ₹/qtl
```

`breakdown` must contain every line item so the website can render the full cost waterfall. Judges love seeing the waterfall.

#### 5.3 `config/cost_model.yaml`
```yaml
grade_factor: {A: 1.10, B: 1.00, C: 0.86}
storage_factor: {ambient: 1.0, shed: 0.7, cold_store: 0.25}

defaults:
  hamali_per_qtl: 12          # SOURCE: <fill in>
  weighing_per_qtl: 3         # SOURCE: <fill in>
  packing_per_qtl: 8          # SOURCE: <fill in>
  truck_capacity_qtl: 90
  transport_per_km: 42        # SOURCE: <fill in>
  interest_rate_annual: 0.14
  storage_cost_per_qtl_per_day: {ambient: 0, shed: 0.6, cold_store: 3.5}

states:
  Maharashtra:
    commission_pct: 3.0       # SOURCE: <fill in>
    apmc_cess_pct: 1.05       # SOURCE: <fill in>
    other_fees_pct: 0.3       # SOURCE: <fill in>
  _default:
    commission_pct: 2.5
    apmc_cess_pct: 1.5
    other_fees_pct: 0.5
```

#### 5.4 `config/crops.yaml`
```yaml
onion:
  aliases: [Onion, "Onion Red", "Onion(Big)", "Onion Local", Kanda, कांदा]
  perishability_class: 3
  k_c: 0.006
  shelf_life_days: 90
  max_hold_days: 20
  msp_applicable: false
  seasons:
    kharif: {harvest_start: "10-01", harvest_end: "12-15"}
    rabi:   {harvest_start: "03-01", harvest_end: "05-15"}
```

#### 5.5 The comparison function — powers the money shot
```python
def compare_mandis(price_forecasts, qty_qtl, days_held, farmer_ctx) -> list[MandiComparison]
```
Returns each mandi with `gross_per_qtl`, `net_per_qtl`, `rank_by_gross`, `rank_by_net`, and a boolean `rank_flipped`.

### MANUAL steps for you

1. **Research and fill in every `SOURCE: <fill in>` in `config/cost_model.yaml`.** Search for Maharashtra APMC commission rate, market cess, hamali charges for onion in Nashik, and truck hire ₹/km. Put the source URL in the comment. A judge *will* ask.
2. Run `python -c` snippet Claude Code provides, with a case you understand (80 qtl, 62 km, 0 days) and sanity-check the output against your own intuition. If the net is 40% below gross, something is wrong.

### Acceptance check

```bash
make check-phase5
```
Asserts: net < gross always; net decreases as distance increases; net decreases as days held increases for onion; a 0-day hold has zero spoilage; **at least one test case exists where ranking by gross and ranking by net produce a different winner** (this is the demo moment — the test guarantees you have it).

### 🟢 What we just did, in simple words

This is the heart of the whole project. Every other team will show a farmer the market price — say ₹2,010 at Lasalgaon. But that number is a lie for him. Out of it comes 3% commission, 1% market cess, loading charges, the diesel to get 80 quintals 62 km up the road, and if he waits a week, some of the onion rots. What reaches his hand might be ₹1,842. We now compute that. And the striking consequence is that **the market with the highest price is sometimes not the best market for him** — a nearer market with a lower headline price can pay more in the end. The acceptance test literally forces us to have one such case ready, because showing that table flipping in front of judges is worth more than any accuracy number.

---

# Phase 6 — Decision engine and explainer

**Goal:** turn forecasts + economics into one imperative sentence with a rupee figure.

### Claude Code builds

#### 6.1 `backend/decision/constraints.py`
Applied **before** scoring; they override the optimiser:

| Constraint | Rule |
|---|---|
| `msp_floor` | if crop has MSP and `net(p50) < msp` and procurement active → force `action = sell_to_procurement`. (Onion has no MSP — the code must handle "not applicable" cleanly.) |
| `spoilage_cliff` | drop any horizon `d` where `spoilage_fraction(d) > 0.15` |
| `max_hold_days` | drop any `d > crops.onion.max_hold_days` |
| `min_viable_load` | if `qty < 0.25 × truck_capacity` and no pooling → drop mandis beyond 40 km |
| `confidence_floor` | if `(p90−p10)/p50 > 0.35` → force `sell_fraction ≥ 0.5` |
| `shock_override` | if an active bearish shock has `magnitude = 3` and `days_since_shock ≤ 3` → force `sell_fraction = 1.0` |

#### 6.2 `backend/decision/engine.py`
```python
def optimise(lot: LotContext, forecasts: dict, mandis: list[Mandi],
             risk_profile: str) -> Recommendation
```
Grid search over:
- `sell_now_fraction ∈ {0, 0.25, 0.5, 0.75, 1.0}`
- `hold_days ∈ {3, 7, 15}`
- `mandi_now ∈ top-5`, `mandi_later ∈ top-5`

Score each candidate with a **mean–risk objective** (a smallholder fears loss more than he wants gain):
```
E_net    = net(p50, now) + net(p50, later)
downside = max(0, net(p50, later) − net(p10, later))
score    = E_net − λ × downside
λ from config/decision.yaml: cautious 0.8, balanced 0.45, aggressive 0.2
```

Also compute the baseline — **sell 100% today at the nearest mandi** — and report `expected_gain = best.E_net − baseline.net`.

#### 6.3 `backend/decision/confidence.py`
```
confidence = 0.5 × band_tightness + 0.2 × data_quality + 0.3 × historical_hit_rate

band_tightness      = clip(1 − ((p90−p10)/(2×p50)) / 0.30, 0, 1)
data_quality        = 1 − imputed_share_14d
historical_hit_rate = rolling PICP for this (mandi, commodity) over the last 60 days
```
If `confidence < 0.5`, the recommendation text must explicitly say the market is unusually unpredictable and it is safer to sell now.

#### 6.4 Output object
```python
@dataclass
class Recommendation:
    action: Literal["sell_now", "hold", "split", "sell_to_procurement"]
    tranches: list[Tranche]            # qty, date, mandi, net_per_qtl, range
    baseline_net: float
    strategy_net: float
    expected_gain: float
    confidence: float
    reason_text: str                   # from ml/explain.py, max 2 clauses
    constraints_applied: list[str]
    alternatives_considered: int
```

#### 6.5 `config/decision.yaml`
```yaml
sell_fractions: [0.0, 0.25, 0.5, 0.75, 1.0]
hold_horizons: [3, 7, 15]
risk_lambda: {cautious: 0.8, balanced: 0.45, aggressive: 0.2}
constraints:
  max_spoilage_fraction: 0.15
  wide_band_threshold: 0.35
  min_viable_load_ratio: 0.25
  near_mandi_km: 40
explanation_templates: {...}
```

### MANUAL steps for you

1. Run the engine on 3 scenarios you can reason about and check the answers are sane:
   - onion, 80 qtl, harvest today, balanced → expect a split
   - onion, 5 qtl, harvest today → expect "sell at the nearest mandi", not a 90 km trip
   - onion, 80 qtl, with a magnitude-3 bearish shock 2 days ago → expect "sell everything now"
2. If any answer looks wrong, it is almost always a constraint, not the model. Check `constraints_applied` in the output.

### Acceptance check

```bash
make check-phase6
```
Asserts: `expected_gain ≥ 0` for the chosen strategy in ≥ 90% of 200 random scenarios; tranche quantities sum to lot quantity; every constraint has at least one test that proves it fires; `cautious` never recommends a longer hold than `aggressive` on the same input.

### 🟢 What we just did, in simple words

Now the system stops describing and starts deciding. It tries 375 different plans — sell everything now, sell half and wait a week, sell a quarter and wait two weeks, at each of five markets — works out the net rupees for each, and picks the best. But not simply the highest average: it deliberately penalises plans with a bad worst case, because a farmer with a loan cannot afford a gamble that occasionally goes badly. On top of that sit six hard rules that override the maths entirely — never recommend holding tomatoes for two weeks, never send five quintals ninety kilometres, and if the government just banned exports, sell today and don't argue. The output is one sentence a person can act on, plus the reason, plus how sure we are.

---

# Phase 7 — Backtest and the ₹-uplift number

**Goal:** one number that decides whether you advance: *"following our advice beats selling immediately by X%."*

### Claude Code builds

#### 7.1 `backend/backtest/scenarios.py`
Generate scenarios over a held-out period the model never trained on (last 6 months):
- for each mandi × every 5th business day
- quantity sampled log-normally, median 25 qtl
- grade sampled from {A: 0.2, B: 0.6, C: 0.2}
- storage sampled from {ambient: 0.5, shed: 0.45, cold_store: 0.05}

#### 7.2 `backend/backtest/runner.py`
For each scenario:
1. Rebuild features **point-in-time as of the scenario date** (same builder, no shortcuts)
2. Call the **live** `decision.engine.optimise()` — not a special backtest path. If backtest and production run different code, the backtest is fiction.
3. Settle each tranche at the **actual realised price** on its execution date, applying the actual spoilage model
4. Compute `baseline_net` (sell 100% that day at nearest mandi) and `model_net`
5. `uplift_pct = (model_net − baseline_net) / baseline_net`

#### 7.3 `backend/backtest/report.py`
Writes `data/artifacts/backtest_report.md` and prints:

| Statistic | Value |
|---|---|
| Mean uplift % | |
| Median uplift % | |
| **Win rate** (uplift > 0) | |
| 5th percentile uplift (worst case) | |
| 95th percentile uplift | |
| Scenarios evaluated | |
| Mean uplift by month | |

Plus the **ablation table** — rerun the whole backtest with feature groups disabled:

| Configuration | MAPE h=7 | PICP | ₹-uplift |
|---|---|---|---|
| Naive (sell now) | — | — | 0.0% |
| Price-only features | | | |
| + arrivals | | | |
| + weather | | | |
| + shock radar | | | |
| + net-cost decision engine | | | |

Implement this with a `--feature-groups` flag on the runner so each row is one command.

#### 7.4 `scripts/backtest.py`
`python scripts/backtest.py --test-from 2025-XX-XX --ablation`

### MANUAL steps for you

1. Run `make backtest`
2. **Read every number, including the bad ones.** If the 5th percentile uplift is −12%, that is your honest answer to "what if you're wrong" — do not hide it, present it. Judges trust teams that name their own downside.
3. Screenshot the ablation table. It is the single most persuasive slide you will have.
4. If mean uplift is negative or win rate is under 50%, stop and debug before building any UI. Likely causes: cost model too aggressive, spoilage rate too high, or the decision engine holding too long.

### Acceptance check

```bash
make check-phase7
```
Asserts: ≥ 200 scenarios evaluated; report file exists; ablation table has ≥ 4 rows; backtest calls the same `optimise()` function as the API (verify by import path assertion).

### 🟢 What we just did, in simple words

This is the exam. We rewound time six months, pretended we knew nothing after that date, asked our system for advice on hundreds of imaginary harvests, and then checked what actually happened next. The result is one honest sentence: following our advice would have earned X% more than just selling on harvest day. That single number is worth more to a judge than any accuracy percentage, because it's in rupees — the thing the farmer actually cares about. The ablation table underneath it proves each part of the system earns its place: look, adding arrival data lifted it by 2.7%, adding the policy events by another 1.2%. And notice the last row: the model didn't get more accurate, but the farmer earned more — because we fixed the *economics*, not the *prediction*. That row is the entire argument of the project.

---

# Phase 8 — FastAPI backend

**Goal:** every capability exposed as a clean HTTP API the website and bot both consume.

### Claude Code builds

`backend/api/main.py` with CORS allowing `http://localhost:3000`, and these routers. All responses are Pydantic models defined in `api/schemas.py`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/mandis` | list configured mandis with lat/lon and latest price |
| GET | `/api/v1/forecast` | `?mandi_id=&commodity_id=&horizons=1,3,7,15` → p10/p50/p90 + drivers + confidence |
| GET | `/api/v1/history` | `?mandi_id=&commodity_id=&days=180` → price + arrivals series for the chart |
| POST | `/api/v1/recommend` | lot in → full `Recommendation` out |
| GET | `/api/v1/mandis/compare` | gross vs net table with `rank_flipped` flags |
| POST | `/api/v1/sale-report` | intake for the ground-truth loop |
| GET | `/api/v1/transparency` | scores per mandi with `n_reports` |
| GET | `/api/v1/accuracy` | live metrics + backtest summary for the Accuracy page |
| POST | `/api/v1/chat` | `{session_id, text}` → bot reply (web simulator) |
| GET/POST | `/webhooks/whatsapp` | Phase 11 |
| GET | `/healthz` | ops |

Rules:
- Precompute forecasts nightly (`scripts/daily_job.py`) into the `forecasts` table so `/recommend` never trains or waits on the model. Target p95 latency **under 500 ms**.
- Cache `/forecast` and `/history` in Redis with a 15-minute TTL.
- On `InsufficientData`, return HTTP 200 with `{"status": "insufficient_data", "message": "..."}` — never a 500. The demo must degrade gracefully.
- Every endpoint documented via FastAPI's automatic `/docs`.

`/api/v1/recommend` response shape (frontend depends on this exactly):
```json
{
  "recommendation_id": 5521,
  "action": "split",
  "tranches": [
    {"quantity_qtl": 50, "when": "2026-08-12", "days_from_now": 0,
     "mandi_id": 412, "mandi_name": "Lasalgaon",
     "gross_per_qtl": 1960, "net_per_qtl": 1842,
     "range_per_qtl": null},
    {"quantity_qtl": 30, "when": "2026-08-21", "days_from_now": 9,
     "mandi_id": 412, "mandi_name": "Lasalgaon",
     "gross_per_qtl": 2085, "net_per_qtl": 1961,
     "range_per_qtl": [1704, 2183]}
  ],
  "baseline": {"description": "Sell everything today at the nearest mandi",
               "net_total": 145600},
  "strategy": {"net_total": 159830},
  "expected_gain": 14230,
  "confidence": 0.71,
  "reason": "Arrivals are 22% below normal and Diwali demand starts in 11 days.",
  "cost_breakdown": {"gross": 168400, "commission": 5052, "cess": 1768,
                     "hamali": 960, "transport": 2604, "holding": 186,
                     "spoilage_qtl": 1.6},
  "constraints_applied": ["spoilage_ok"],
  "alternatives_considered": 375
}
```

### MANUAL steps for you

1. `make api`, open `http://localhost:8000/docs`
2. Click through `/api/v1/recommend` in the Swagger UI with a real payload and confirm the numbers match what the CLI gave you in Phase 6

### Acceptance check

```bash
make check-phase8
```
`test_phase8_api.py` hits every endpoint with `TestClient`, asserts 200 and schema validity, and asserts `/recommend` p95 latency under 500 ms across 50 calls.

### 🟢 What we just did, in simple words

We put a doorway on the engine. Until now everything ran from the command line; now the website and the WhatsApp bot can both ask the same questions over HTTP and get the same answers. Two decisions matter here: we compute tomorrow's forecasts overnight so a live request is fast, and when we don't have enough data we say so politely instead of crashing. A demo that shows "not enough data for this market yet" is fine; a demo that shows a red 500 error is not.

---

# Phase 9 — Bot engine and web chat simulator

**Goal:** a conversation engine that is completely independent of WhatsApp, plus a browser page that looks and behaves like WhatsApp.

**Build this before Phase 11. It is your insurance policy against Meta breaking on demo day.**

### Claude Code builds

#### 9.1 `backend/bot/engine.py` — the core, pure and testable
```python
def handle_message(session: Session, text: str) -> BotReply:
    """
    Pure function. No HTTP, no WhatsApp SDK, no I/O except DB reads
    through injected repositories. Both /api/v1/chat and the WhatsApp
    webhook call THIS. There is no second implementation.
    """
```
`BotReply` = `{messages: list[str], buttons: list[str], new_state: str}`.

#### 9.2 `backend/bot/session.py`
State stored in Redis (hot) and mirrored to `bot_sessions` (durable). States:
```
NEW → AWAITING_LANGUAGE → AWAITING_VILLAGE → IDLE
IDLE → AWAITING_CROP_QTY → AWAITING_GRADE → AWAITING_STORAGE → ADVICE_GIVEN
ADVICE_GIVEN → AWAITING_SALE_PRICE → IDLE
```

#### 9.3 `backend/bot/intents.py`
**Regex and keyword first, no LLM.** The domain is tiny and bounded:
- crop: match against `commodity_aliases` including Devanagari
- quantity: `(\d+(?:\.\d+)?)\s*(क्विंटल|quintal|qtl|kg|किलो)` — convert kg to quintals
- yes/no: `हो|होय|हा|yes|y|ok|ठीक` / `नाही|नको|no|n`
- advice request: `विकू|भाव|सल्ला|sell|price|advice|rate`
- sale report: a bare number in a plausible price range while state is `AWAITING_SALE_PRICE`
- fallback: send the help message. **Do not call an LLM.** It is slower, costs money, and can hallucinate a price.

#### 9.4 The five flows

**Flow A — Welcome and setup**
```
User: (anything, first time)
Bot:  नमस्कार! 🌾 मी भाव सेतू.
      मी तुम्हाला योग्य वेळी, योग्य बाजारात विकायला मदत करेन.
      भाषा निवडा:  [मराठी] [English]
Bot:  तुमचे गाव कोणते? (नाव लिहा किंवा location पाठवा)
User: विंचूर
Bot:  ✅ नोंदवले. जवळचा बाजार: लासलगाव (12 किमी)
      आता तुमचा माल सांगा — उदा. "कांदा 80 क्विंटल"
```

**Flow B — Declare lot**
```
User: कांदा 80 क्विंटल
Bot:  कांदा, 80 क्विंटल ✅
      प्रत कोणती?  [A - उत्तम] [B - साधारण] [C - कमी]
User: B
Bot:  साठवण कुठे?  [घरात] [शेड] [कोल्ड स्टोरेज]
User: शेड
Bot:  ठीक आहे. सल्ला तयार करतोय... ⏳
```

**Flow C — The recommendation (the core message)**
```
Bot:  ⚠️ आजच सगळं विकू नका.

      ✅ आज 50 क्विंटल लासलगावला विका
         → हातात ₹1,842/क्विंटल

      ⏳ 30 क्विंटल 9 दिवस थांबवा
         → अंदाजे ₹1,961/क्विंटल (₹1,704 – ₹2,183)

      💰 जास्त मिळकत: सुमारे ₹14,230
      📊 खात्री: 71%

      कारण: आवक 22% कमी आहे आणि 11 दिवसांत
      दिवाळीची मागणी सुरू होते.

      [तपशील] [इशारा लावा] [दुसरा बाजार]
```
Rules for every bot message: max 6 lines of content, ₹ always per quintal, exactly one reason, confidence always shown, and **never** the words "model", "algorithm", "AI" or "prediction".

**Flow D — Alert (simulated in Round 1 via a "send test alert" button on the site)**
```
Bot:  ⚠️ लासलगावात कांद्याचा भाव 3 दिवसांत ₹120 वाढला.
      तुमचे उरलेले 30 क्विंटल विकण्यासाठी चांगली वेळ आहे.
```

**Flow E — The ground-truth loop** ⭐
```
Bot:  काल विक्री झाली का? प्रत्यक्ष किती भाव मिळाला? (फक्त आकडा लिहा)
User: 1880
Bot:  नोंदवले, धन्यवाद 🙏
      अधिकृत दर ₹1,890 होता — तुम्हाला जवळपास योग्य भाव मिळाला.
      तुमच्या माहितीमुळे इतर शेतकऱ्यांनाही मदत होते.
```
Validation: reject values outside `[0.3×, 2.0×]` of the official modal price and ask again. Write to `sale_reports`, then recompute the mandi's transparency score.

#### 9.5 `backend/bot/locales/{mr,en}.yaml`
All strings live here with `{placeholders}`. **Never concatenate translated strings in code.**

#### 9.6 `backend/transparency/scoring.py`
```
gap_r      = (expected_net_r − reported_net_r) / expected_net_r
raw_gap    = trimmed_median({gap_r}, trim=0.10)
shrunk_gap = (n × raw_gap + 15 × global_gap) / (n + 15)
score      = clip(10 × (1 − shrunk_gap / 0.25), 0, 10)
```
Hard rule: **do not display a score when `n < 10`** — show "not enough reports yet" instead. One report per farmer per mandi per week counts.

#### 9.7 `POST /api/v1/chat`
Thin wrapper: `{session_id, text}` → `handle_message()` → `BotReply`.

### MANUAL steps for you

1. Once Phase 10 is up, open `/chat` and run the full conversation end to end, in Marathi
2. Check the Marathi wording with anyone who speaks it natively — machine-translated Marathi reads badly and a Maharashtra judge will notice instantly. This is a 20-minute task with real payoff.

### Acceptance check

```bash
make check-phase9
```
`test_phase9_bot.py` drives a full scripted conversation (welcome → lot → advice → sale report) through `handle_message()` only, asserting state transitions and that a `sale_reports` row is written. **No WhatsApp code involved in this test at all** — that is the point.

### 🟢 What we just did, in simple words

We built the conversation as a standalone brain that doesn't know or care whether it's talking to WhatsApp, a web page, or a test script. You hand it "what the user said" and it hands back "what to reply." That one design choice gives us two things: we can test the whole conversation without any Meta account, and if WhatsApp collapses on demo day we open the `/chat` page on the website and the demo continues exactly as scripted. The last flow is the important one — after the sale we ask what price he actually got. That question is the piece of the product nobody else has built, and it takes about ten lines of code.

---

# Phase 10 — Next.js website

**Goal:** the primary demo surface. Mobile-first, fast, and honest.

### Claude Code builds

**Design rules:** clean and calm, not a "dashboard". System font stack, generous whitespace, one accent colour (deep green `#1D9E75`), rupee figures large and prominent. Must look correct on a phone at 390 px — a judge will pull it up on their own phone.

#### Page 1 — `/` Home
- One-line pitch: *"Not today's price. Today's decision."*
- Three stat cards pulled live from the API: mandis tracked, days of history, **backtested uplift %**
- A 3-step "how it works" strip
- Two buttons: **Get advice** → `/advisor`, **Continue on WhatsApp** → deep link

#### Page 2 — `/advisor` ⭐ the core page
- `LotForm`: crop (onion), quantity, grade (A/B/C), storage, village (default Vinchur), risk profile
- On submit → `POST /api/v1/recommend`
- `RecommendationCard` showing:
  - the action headline in plain language
  - each tranche as a card: quantity, when, mandi, **big ₹ net/quintal**, and the range for future tranches
  - `expected_gain` as the hero number, with the baseline stated underneath: *"vs ₹1,45,600 if you sold everything today"*
  - confidence as a labelled bar
  - the one-sentence reason
  - an expandable **cost waterfall** from `cost_breakdown`: gross → commission → cess → hamali → transport → holding → net. This is where judges lean forward.
- `ForecastChart` (Recharts): price history line + forecast fan. Use a stacked `Area` for the p10–p90 band with ~20% opacity, and a solid line for p50. Mark today with a vertical reference line.
- `WhatsAppCTA` at the bottom

#### Page 3 — `/compare` ⭐ the money shot
- Table of 5 mandis with columns: Mandi, Distance, Gross ₹/qtl, Fees, Transport, Spoilage, **Net ₹/qtl**
- A toggle: **Rank by gross / Rank by net** — rows animate to reorder
- When the top row changes between the two rankings, show a callout: *"Lasalgaon has the highest price, but Pimpalgaon puts more money in your hand."*
- This single interaction is your strongest 10 seconds. Make the animation smooth.

#### Page 4 — `/accuracy`
- MAPE by horizon vs baselines (from `/api/v1/accuracy`)
- PICP with a plain-English line: *"When we say 80% likely, it happened 79% of the time."*
- The ablation table from the backtest
- Worst-case uplift stated openly
- A short paragraph titled "Where we are weak" — perishables, thin mandis, missing government data. **Publishing your own weaknesses is a trust move almost no team makes.**

#### Page 5 — `/transparency`
- The 5 mandis with score, `n_reports`, and median gap
- Mandis with `n < 10` show "not enough reports yet" — never a score
- An explainer box on what the score means and, importantly, what it does not mean (it is about markets, not named individuals)

#### Page 6 — `/chat`
- A WhatsApp-lookalike chat window (green bubbles right, white left, the familiar background)
- Calls `POST /api/v1/chat`
- Quick-reply buttons rendered from `BotReply.buttons`
- A small honest label at the top: *"Demo simulator — same engine as our WhatsApp bot"*

#### `components/WhatsAppCTA.tsx`
```tsx
const phone = process.env.NEXT_PUBLIC_WHATSAPP_NUMBER;   // digits only, with country code
const text  = encodeURIComponent("नमस्कार, मला कांद्याचा सल्ला हवा आहे");
const href  = `https://wa.me/${phone}?text=${text}`;
```
Renders a WhatsApp-green button: **"Continue on WhatsApp"**, plus small print: *"Demo number — works for registered testers"*, plus a secondary link **"Try the web version instead"** → `/chat`.

#### `lib/api.ts`
Typed fetch wrappers for every endpoint, `NEXT_PUBLIC_API_URL` from env, all types mirrored in `lib/types.ts`.

### MANUAL steps for you

1. `cd frontend && npm install && npm run dev`
2. Open `http://localhost:3000` on your **phone** (same wifi, use your laptop's LAN IP) and check every page
3. Fix any layout break you see — judges will use phones

### Acceptance check

```bash
make check-phase10
```
`npm run build` succeeds with no type errors, and a Playwright-free smoke script confirms all 6 routes return 200 with the API running.

### 🟢 What we just did, in simple words

This is what the judges will actually look at. Six pages, and each one exists to make a single point. Home says what we are in one line. Advisor shows a real decision with real rupees and lets you open up the full cost breakdown. Compare is the page that wins the round — you flip a toggle and the ranking of markets changes, proving that the highest price is not the best price. Accuracy is where we publish our own error rates, including the bad ones, because a team that admits its weaknesses is believed about its strengths. Transparency shows the feedback loop working. And `/chat` is the backup demo that makes us immune to WhatsApp failing.

---

# Phase 11 — WhatsApp Cloud API integration

**Goal:** the deep link from the website opens WhatsApp and the bot replies for real.

**Everything up to here works without this phase. Treat it as a bonus, not a dependency.**

### Claude Code builds

#### 11.1 `backend/api/routers/whatsapp.py`

**GET `/webhooks/whatsapp`** — Meta's verification handshake:
```python
if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp.verify_token:
    return PlainTextResponse(hub_challenge)
return PlainTextResponse("forbidden", status_code=403)
```

**POST `/webhooks/whatsapp`**:
1. Verify the `X-Hub-Signature-256` header (HMAC-SHA256 of the raw body with the app secret). Reject mismatches.
2. Return `200 OK` **immediately**, then process in a background task. Meta retries aggressively if you are slow.
3. Extract `from`, `text.body` (or `interactive.button_reply.title`)
4. Load session → `handle_message()` → send replies
5. Deduplicate on `message.id` — Meta sends duplicates.

#### 11.2 `backend/bot/whatsapp_client.py`
```python
POST https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages
Authorization: Bearer {ACCESS_TOKEN}
```
Support text messages and interactive reply buttons (max 3 buttons, max 20 chars each — Meta's limit; if `BotReply.buttons` exceeds this, degrade to a numbered text list).

#### 11.3 Graceful degradation
If `WHATSAPP_ACCESS_TOKEN` is missing or empty, the app must still start, log `WhatsApp disabled — /chat simulator active`, and serve everything else normally.

### MANUAL steps for you — follow exactly

1. **Start the API**: `make api` (port 8000)

2. **Open a public tunnel**:
   ```bash
   cloudflared tunnel --url http://localhost:8000
   ```
   Copy the printed URL, e.g. `https://random-words-1234.trycloudflare.com`

3. **Configure the webhook in Meta**:
   - developers.facebook.com → your app → **WhatsApp → Configuration**
   - **Callback URL**: `https://<your-tunnel>/webhooks/whatsapp`
   - **Verify token**: the exact string you put in `.env` as `WHATSAPP_VERIFY_TOKEN`
   - Click **Verify and save**. If it fails, your API isn't running or the token doesn't match — check the API logs, the GET handler logs every attempt.

4. **Subscribe to message events**: on the same page, under **Webhook fields**, click **Manage** and tick **messages**. ⚠️ Easy to miss, and without it nothing arrives.

5. **Register the demo phones**: **API Setup → To → Manage phone number list** → add every phone that will be used in the demo (max 5). The test number cannot message anyone else.

6. **Put the test number in the frontend**: `frontend/.env.local` → `NEXT_PUBLIC_WHATSAPP_NUMBER=<digits only, with country code, no + or spaces>`

7. **Test**: from a registered phone, send "Hi" to the test number. You should get the welcome message. Watch the API logs.

8. **⚠️ On demo day, first thing in the morning**: the temporary access token expires every 24 hours. Regenerate it in the Meta dashboard, update `.env`, restart the API. Also restart the tunnel — its URL changes — and re-save the new callback URL in Meta. **Budget 15 minutes for this and do it before you leave for the venue.**

### Acceptance check

```bash
make check-phase11
```
Asserts: GET verification returns the challenge for the right token and 403 for the wrong one; POST with a valid signature and a sample Meta payload produces a queued outbound message; POST with a bad signature is rejected; the app boots with WhatsApp env vars empty.

### 🟢 What we just did, in simple words

We connected the bot to real WhatsApp. Meta needs a public web address to deliver messages to, which is why we run a tunnel — your laptop gets a temporary internet address for the duration of the demo. Three things about this phase to keep in mind: the token dies every 24 hours, the tunnel URL changes every restart, and the test number can only talk to five phones you register in advance. None of that is a bug, it's just how the free tier works. This is also exactly why we built `/chat` first — if any of those three things goes wrong at the venue, you switch to the web simulator and nobody watching can tell the difference in the story you're telling.

---

# Phase 12 — Seed demo data, polish, demo script

**Goal:** everything is rehearsed, seeded and screenshot-ready.

### Claude Code builds

#### 12.1 `scripts/seed_demo_data.py`
- 1 demo farmer (Ramesh, Vinchur, Marathi, balanced)
- 1 open lot: onion, 80 qtl, grade B, shed
- **~35 realistic sale reports** spread across the 5 mandis over the last 90 days, generated so that transparency scores come out *differently* for different mandis (one clearly better, one clearly worse) — otherwise the page is boring
- Every seeded row gets `source='seed_demo'` and `verification='self_reported'`
- A `--clear` flag to wipe seed rows only

#### 12.2 Demo mode safeguards
- `DEMO_MODE=true` in `.env` → API serves the last successfully computed forecast if live computation fails, instead of erroring. **The demo must never show a stack trace.**
- A `/api/v1/reset-demo` endpoint that restores the demo lot to unsold, so you can run the demo repeatedly.

#### 12.3 `README.md` (rewrite for the judges)
Trim the full technical README to what is actually built. Everything not built moves to a clearly labelled **"Round 2 roadmap"** section. Add: the uplift number at the top, a screenshot, and a 5-command quickstart.

#### 12.4 `docs/DEMO_SCRIPT.md`
The exact 3-minute walkthrough with timings:

| Time | Say | Show |
|---|---|---|
| 0:00–0:20 | "Ramesh has 80 quintals of onion. A trader offers ₹1,650. He has no way to know if that's fair." | Home page |
| 0:20–0:50 | "Every app shows him the mandi rate — ₹2,010 at Lasalgaon. That number is wrong for him." | `/compare`, toggle gross → net, ranking flips |
| 0:50–1:30 | "Here's what we tell him instead." | `/advisor`, submit the lot, expand the cost waterfall |
| 1:30–2:00 | "In his own language, on WhatsApp, by voice." | Phone: send the message, show the reply |
| 2:00–2:30 | "We backtested this on real 2024–25 data." | `/accuracy`, ablation table, and state the worst case openly |
| 2:30–3:00 | "And after he sells, we ask what he actually got. Nobody else has this data." | `/chat` sale-report flow → `/transparency` updates |

### MANUAL steps for you

1. Run `make seed`
2. **Record a full screen capture** of the working demo, including the phone. Venue wifi fails, tokens expire, laptops sleep. This video has saved more hackathon teams than any feature.
3. Rehearse the 3-minute script **five times** out loud. Time yourself. Most teams run 90 seconds over and get cut off before the backtest slide — which is the slide that wins.
4. Prepare answers to these, from the project README Appendix B: *how is this different from Agmarknet · how accurate is it really · what if you're wrong · will a farmer actually use this · where does the sale data come from · does it scale · what's the business model · what can't you do.*
5. Take screenshots of: the metrics table, the ablation table, the compare page mid-flip, the WhatsApp conversation. These go in the deck.

### Acceptance check

```bash
make check-phase12
```
Asserts: demo farmer and lot exist; ≥ 30 seed sale reports; at least 3 mandis have `n_reports ≥ 10` so scores actually display; `/api/v1/reset-demo` restores the lot; every page returns 200 with the API in `DEMO_MODE`.

### 🟢 What we just did, in simple words

We made the demo bulletproof and rehearsed it. The seeded sale reports matter more than they look — with only two or three reports the transparency page shows "not enough data" everywhere and the judges never see your best idea working. So we generate about thirty realistic ones, honestly labelled as seed data, so the mechanism is visible. Then the boring but decisive part: record a backup video and practise the three minutes five times. Most teams lose not because their project was weak but because they spent ninety seconds explaining their architecture and got cut off before the number that would have won it.

---

## 13. Definition of done

Round 1 is complete when all of these are true:

- [ ] `make check-phase0` through `check-phase12` all pass
- [ ] `data/artifacts/data_audit.md` shows ≥ 3 mandis marked USABLE
- [ ] LightGBM beats every baseline on pinball loss at all 4 horizons
- [ ] PICP is between 0.72 and 0.88
- [ ] `data/artifacts/backtest_report.md` shows a **positive mean ₹-uplift** and win rate > 55%
- [ ] The ablation table has at least 4 rows with real numbers
- [ ] `/compare` demonstrates at least one gross-vs-net ranking flip
- [ ] `/advisor` returns a recommendation in under 1 second
- [ ] `/chat` completes the full conversation including a sale report
- [ ] WhatsApp replies to a registered test phone **or** the `/chat` fallback is rehearsed
- [ ] Backup demo video recorded
- [ ] Deck has: the uplift number, the ablation table, the net-flip screenshot
- [ ] Every `SOURCE: <fill in>` in `config/cost_model.yaml` is filled with a real citation

---

## 14. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| data.gov.in returns 0 records | Wrong resource ID, or filter values don't match exactly (`Onion` vs `onion`) | Hit the URL in a browser first, check the raw JSON field names, filters are case-sensitive |
| Only a few dozen rows come back | Using the public demo key | Register for your own key |
| Model MAPE looks impossibly good (<1%) | Leakage | Run the Phase 3 leakage test; check that the label uses `t+h` and no feature does |
| PICP near 0.99 | Bands trained on too little data, or quantile alpha mixed up | Check `alpha` maps p10→0.10, p90→0.90 |
| Backtest uplift is negative | Cost model too harsh, spoilage rate too high, or the engine holds too long | Print `constraints_applied` distribution; check `k_c` for onion is 0.006 not 0.06 |
| Net price is more than 30% below gross | A percentage entered as a fraction, or vice versa | `commission_pct: 3.0` means 3%, not 300% |
| Meta webhook verification fails | API not running, tunnel down, or token mismatch | The GET handler logs every attempt — read the log, compare the token character by character |
| WhatsApp messages never arrive | Forgot to tick the `messages` webhook field, or the phone isn't in the registered list | Meta → WhatsApp → Configuration → Webhook fields → Manage |
| WhatsApp worked yesterday, not today | The temporary token expired (24h) | Regenerate in Meta dashboard, update `.env`, restart |
| Frontend gets CORS errors | API CORS origin doesn't match | Allow `http://localhost:3000` and your LAN IP in `api/main.py` |
| OSRM calls hang | Public demo server is rate-limiting | It should be cached after first call; check `distance_cache` is being written |

---

## Appendix — Suggested prompts for driving Claude Code

Paste these one at a time, in order. Do not paste two phases at once.

```
Read PLAN.md fully. Then implement Phase 0 exactly as specified.
Print the acceptance check output. Do not start Phase 1.
```

```
Phase 0 passed. Implement Phase 1. The mandi list is in config/mandis.yaml.
Run make check-phase1 and paste the output.
```

```
Phase 1 passed. Implement Phase 2. My CSV is at data/raw/mandi_history.csv
and the column names are: <paste your actual headers here>.
Write the mapping into config/sources.yaml before you write any parsing code.
```

...and so on. After each phase, read the 🟢 explanation paragraph so you understand what you now have before moving on.
