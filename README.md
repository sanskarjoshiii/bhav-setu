# Bhav Setu — Smart Agricultural Market Intelligence System

**A selling-decision engine for Indian farmers.**

Not a price prediction app. A system that tells a farmer *what to do*, computes the answer in **rupees that actually reach his pocket**, delivers it over WhatsApp in his own language, and learns from the price he actually got.

---

## Table of contents

1. [The problem, stated correctly](#1-the-problem-stated-correctly)
2. [What already exists and why it fails](#2-what-already-exists-and-why-it-fails)
3. [Product thesis and design principles](#3-product-thesis-and-design-principles)
4. [System architecture](#4-system-architecture)
5. [Data sources](#5-data-sources)
6. [Ingestion layer](#6-ingestion-layer)
7. [Database schema](#7-database-schema)
8. [Feature engineering](#8-feature-engineering)
9. [The forecasting model](#9-the-forecasting-model)
10. [The Net In-Hand Realisation Engine](#10-the-net-in-hand-realisation-engine)
11. [The Decision Engine](#11-the-decision-engine)
12. [Shock Radar](#12-shock-radar)
13. [The Ground-Truth Loop and Mandi Transparency Score](#13-the-ground-truth-loop-and-mandi-transparency-score)
14. [Glut Early Warning (stretch module)](#14-glut-early-warning-stretch-module)
15. [Evaluation and backtesting](#15-evaluation-and-backtesting)
16. [API specification](#16-api-specification)
17. [WhatsApp bot design](#17-whatsapp-bot-design)
18. [Web dashboard](#18-web-dashboard)
19. [Repository structure](#19-repository-structure)
20. [Configuration files](#20-configuration-files)
21. [Local setup](#21-local-setup)
22. [Build order for the hackathon](#22-build-order-for-the-hackathon)
23. [Team split](#23-team-split)
24. [Risks, limitations and ethics](#24-risks-limitations-and-ethics)
25. [Glossary](#25-glossary)

---

## 1. The problem, stated correctly

The official problem statement says: *farmers sell without reliable information on future prices, which reduces their income.*

That is true but incomplete. A farmer standing in a mandi with 80 quintals of onion is not making one decision. He is making five, and each one leaks money:

| # | Decision | What he lacks | Money lost |
|---|---|---|---|
| 1 | **When** to sell | Does the price rise or fall in the next 7–15 days? | Sells into a dip, or holds into a crash |
| 2 | **Where** to sell | Mandi A pays ₹200/qtl more but is 60 km away | Transport eats the gain, or he skips a genuinely better mandi |
| 3 | **Is this offer fair** | Official rate is ₹2,100; the trader offers ₹1,800 | 10–20% skimmed, invisibly |
| 4 | **How** to sell | Mandi vs FPO vs private trader vs government procurement | Sells below MSP when procurement was available |
| 5 | **What** to sow next season | Everyone plants the crop that paid well last year | The classic glut → crash cycle, repeated annually |

Three structural facts drive all of this:

- **The mandi price is not the farmer's price.** APMC fees, mandi cess, rural development cess, commission and hamali (loading) together come to roughly 10–15% of produce value. Formally traders pay them; in practice they are passed back by squeezing what the farmer is offered.
- **Most farmers are too small to move.** Around 86% of Indian farmers are small or marginal (under 2 ha). Their marketable surplus is a few quintals, which makes a solo trip to a distant mandi uneconomical even when the price there is better.
- **Perishables rot while you wait.** Post-harvest losses run 20–25% for fruits and vegetables. "Hold for 10 days" is not free — it has a physical cost that must appear in the maths.

**Conclusion:** a system that predicts the mandi modal price and stops there has solved roughly 20% of the problem. This project solves the other 80%.

---

## 2. What already exists and why it fails

| System | What it does | What it does not do |
|---|---|---|
| **Agmarknet** (DMI, Ministry of Agriculture) | Daily min / max / modal price plus **arrival quantities** for all regulated markets. Available as CSV/JSON through data.gov.in. | No forecast, no cost model, no decision, no personalisation |
| **eNAM** | Pan-India electronic trading portal linking APMC mandis; online bidding, direct payment | Farmer generally still has to reach a mandi to trade; adoption uneven across states |
| **Kisan Suvidha / KisanMitra / AgriBegri / private krishi apps** | Prices + weather + advisory + input sales | Display numbers. No net-price maths, no timing advice, no verification |
| **Academic literature (hundreds of papers)** | ARIMA / LSTM / Prophet fitted to mandi price series | Never deployed, evaluated only in MAPE, never in rupees, ignores arrivals and policy shocks |

**The gap, in one sentence:** every existing product answers *"what is the price?"* — none answers *"what should I do, and how many extra rupees will that put in my hand?"*

---

## 3. Product thesis and design principles

> **Thesis:** The unit of value is not a prediction. It is a decision, denominated in net rupees, delivered on a channel the farmer already uses, and validated against what he actually received.

Six principles that govern every design choice in this repo:

### P1 — Net, never gross
Every rupee figure shown to a user is **after** transport, commission, cess, hamali, weighing loss and spoilage. Mandis are ranked by net, not by headline price. Very often this reverses the ranking, and that reversal is the product.

### P2 — Ranges, never point estimates
The model outputs P10 / P50 / P90. The UI shows a band. When the band is wide, we say so and recommend selling sooner. A confident-looking single number is a lie about a volatile market.

### P3 — Decisions, never dashboards
The output is an imperative sentence: *"Sell 50 quintals at Lasalgaon today. Hold 30 for 9 days."* Charts exist for the dashboard and the judges, not for the farmer.

### P4 — Explain in one sentence
Every recommendation carries a plain-language reason derived from feature attributions: *"Arrivals are down 22% and Diwali demand starts in 11 days."* No SHAP waterfall plots for a farmer.

### P5 — Measure in rupees
The headline metric is not MAPE. It is **₹-gained versus the naive strategy** on a walk-forward backtest. If we cannot beat "sell everything at the nearest mandi on harvest day," we have built nothing.

### P6 — Close the loop
After every sale we ask one question: *what price did you actually get?* This single field creates a farmgate-price dataset that does not currently exist anywhere, turns every user into a labeller, and makes the system compound.

---

## 4. System architecture

### 4.1 Layer view

```
┌──────────────────────────────────────────────────────────────────────┐
│  L0  EXTERNAL SOURCES                                                 │
│  data.gov.in/Agmarknet · IMD/Open-Meteo · DGFT/PIB · OSRM · CACP MSP  │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │  scheduled pulls (APScheduler / cron)
┌────────────────────────────────▼─────────────────────────────────────┐
│  L1  INGESTION                                                        │
│  connectors → raw landing tables → validators → cleaners → canonical  │
│  entity resolution (mandi name → mandi_id, commodity name → id)       │
└────────────────────────────────┬─────────────────────────────────────┘
┌────────────────────────────────▼─────────────────────────────────────┐
│  L2  STORAGE                                                          │
│  PostgreSQL (+ TimescaleDB optional) · Redis cache · MinIO/local blob │
└────────────────────────────────┬─────────────────────────────────────┘
┌────────────────────────────────▼─────────────────────────────────────┐
│  L3  FEATURE LAYER                                                    │
│  point-in-time correct feature builder · training set + serving set   │
│  from the same code path (no train/serve skew)                        │
└────────────────────────────────┬─────────────────────────────────────┘
┌────────────────────────────────▼─────────────────────────────────────┐
│  L4  MODEL LAYER                                                      │
│  LightGBM quantile ensemble (P10/P50/P90) · baselines · model registry│
│  nightly retrain · walk-forward validation · drift checks             │
└────────────────────────────────┬─────────────────────────────────────┘
┌────────────────────────────────▼─────────────────────────────────────┐
│  L5  ECONOMICS LAYER                                                  │
│  Net In-Hand Engine (cost model) · Spoilage model · MSP floor check   │
└────────────────────────────────┬─────────────────────────────────────┘
┌────────────────────────────────▼─────────────────────────────────────┐
│  L6  DECISION LAYER                                                   │
│  sell/hold/split optimiser · mandi ranking · alert rules · explainer  │
└────────────────────────────────┬─────────────────────────────────────┘
┌────────────────────────────────▼─────────────────────────────────────┐
│  L7  DELIVERY                                                         │
│  FastAPI · WhatsApp Cloud API bot · IVR fallback · Next.js dashboard  │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │
                      ┌──────────▼───────────┐
                      │  FEEDBACK: sale_report│──────► back into L2/L4
                      │  "what did you get?"  │
                      └───────────────────────┘
```

### 4.2 Why this shape

- **L3 exists as its own layer** so that training features and serving features are generated by the *same function*. Train/serve skew is the single most common reason ML projects look great offline and fail live.
- **L5 is separate from L4** because the cost model is deterministic business logic, not learned. Keeping it out of the model makes it auditable, tunable per state, and explainable to a judge in ten seconds.
- **L6 is separate from L5** because the same net-price numbers can drive different policies (risk-averse smallholder vs a trader-like large farmer).

### 4.3 Request path (synchronous, farmer asks for advice)

```
WhatsApp msg → webhook → intent parse → resolve farmer + lot
  → GET features for (commodity, home mandi + K nearby mandis)   [Redis, ~5ms]
  → model.predict_quantiles(horizons=[1,3,7,15])                  [~10ms]
  → NetInHand.evaluate(for each mandi × each horizon)             [pure python]
  → DecisionEngine.optimise(splits × horizons × mandis)           [grid, ~20ms]
  → Explainer.to_sentence(top features)                           [template]
  → render Marathi/Hindi message → WhatsApp send
```

Total target latency: **under 3 seconds** end to end. Forecasts are precomputed nightly for every (mandi, commodity, horizon) so the online path only does economics and optimisation.

---

## 5. Data sources

| Source | Endpoint / access | Frequency | What we take | Notes |
|---|---|---|---|---|
| **Agmarknet via data.gov.in** | `https://api.data.gov.in/resource/{resource_id}` with `api-key`, `format=json`, `filters[...]`, `limit`, `offset` | daily | mandi, district, state, commodity, variety, grade, min/max/modal price, arrival qty, date | Register for your **own** API key — the public demo key is rate/row limited. Resource IDs occasionally change; keep the ID in config, not in code. |
| **Agmarknet daily price & arrival report** | agmarknet.gov.in report pages | daily | arrivals where the API is thin | HTML; scrape only as fallback, be polite (1 req/sec, cache) |
| **Kaggle historical mandi dataset** | one-time CSV download | once | 3–5 years of backfill history | The API is mostly *current* data. You need history to train. Backfill first, then go live. |
| **Open-Meteo / IMD** | `https://api.open-meteo.com/v1/forecast` (free, no key) | daily | rainfall, tmax, tmin per mandi lat/lon, past + 16-day forecast | Forecast weather is legitimately available at prediction time — no leakage |
| **DGFT / PIB / Dept. of Consumer Affairs** | notification pages, RSS | daily | export bans, stock limits, MSP announcements, buffer releases | Parsed into `shock_events` |
| **CACP MSP schedule** | annual PDF/table | seasonal | MSP per crop per season | Static config table, updated twice a year |
| **OSRM / OpenStreetMap** | self-hosted or public OSRM `/route/v1/driving/` | on demand, cached | **road** distance and duration mandi↔village | Never use straight-line distance — it understates cost by 20–40% |
| **Festival calendar** | static JSON | once | Diwali, Ramzan, Onam, Navratri, Sankranti etc. | Demand spikes; also fasting periods that *depress* some commodities |
| **Sentinel-2 (Copernicus / Earth Engine)** | optional | 5-day revisit | NDVI for acreage estimation | Only for the glut module. Skip in a 48-hour hackathon unless you have a spare person. |

### 5.1 Example: pulling Agmarknet

```python
# ingestion/connectors/agmarknet.py
import httpx, datetime as dt
from typing import Iterator

BASE = "https://api.data.gov.in/resource/{resource_id}"

class AgmarknetConnector:
    def __init__(self, api_key: str, resource_id: str, page_size: int = 1000):
        self.api_key = api_key
        self.resource_id = resource_id
        self.page_size = page_size
        self.client = httpx.Client(timeout=30.0)

    def fetch(self, state: str | None = None,
                    commodity: str | None = None) -> Iterator[dict]:
        offset = 0
        while True:
            params = {
                "api-key": self.api_key,
                "format": "json",
                "limit": self.page_size,
                "offset": offset,
            }
            if state:
                params["filters[state]"] = state
            if commodity:
                params["filters[commodity]"] = commodity

            r = self.client.get(BASE.format(resource_id=self.resource_id),
                                params=params)
            r.raise_for_status()
            records = r.json().get("records", [])
            if not records:
                return
            yield from records
            if len(records) < self.page_size:
                return
            offset += self.page_size
```

**Retry policy:** exponential backoff (1s, 2s, 4s, 8s), max 5 attempts, then write the failure to `ingestion_runs` and alert. Never let one failed pull silently produce a gap that the model then interprets as "no arrivals today."

---

## 6. Ingestion layer

### 6.1 Pipeline stages

```
pull → land raw (jsonb, untouched) → validate → normalise units
     → resolve entities → dedupe → upsert canonical → mark run complete
```

Landing the raw payload untouched matters: when a number looks wrong three weeks later you need to know whether the API said it or you broke it.

### 6.2 The data is dirty — assume it

Government mandi data has all of these problems, and your cleaner must handle each explicitly rather than crashing or silently ingesting garbage:

| Problem | Detection rule | Action |
|---|---|---|
| Missing days (mandi closed, holiday, staff didn't upload) | no row for (mandi, commodity, date) | Do **not** forward-fill blindly. Mark `is_imputed=true`, forward-fill up to 3 days, beyond that leave null and let the model see a `days_since_observation` feature |
| Price of 0, 1, or absurdly large | `modal_price <= 10` or `> 20 × trailing_median` | Reject to quarantine table |
| `min > modal` or `modal > max` | direct comparison | Reject; log |
| Unit inconsistency | arrivals sometimes in tonnes, sometimes quintals | Normalise everything to **quintals** for quantity and **₹/quintal** for price at ingest. Store the original unit too. |
| Mandi name spelling drift ("Lasalgaon", "Lasalgaon(Vinchur)", "LASALGAON") | fuzzy match (RapidFuzz `token_sort_ratio > 90`) against `mandis` table | Auto-map above 95, queue 90–95 for manual confirm, create new below 90 |
| Commodity/variety drift ("Onion", "Onion Red", "Onion(Big)") | same fuzzy approach + manual alias table | Alias table `commodity_aliases` is the source of truth |
| Duplicate rows | unique constraint on (mandi_id, commodity_id, variety, grade, date) | Upsert, keep latest `ingested_at` |
| Sudden step change in a series (mandi changed reporting basis) | rolling z-score of daily log return > 6 | Flag for review, still ingest but set `suspect=true` |

### 6.3 Outlier handling — a warning

Do **not** aggressively winsorise price spikes. In agricultural markets, the spike *is* the signal — an onion price tripling in three weeks is exactly the event a farmer needs warning about. Only remove values that are physically impossible (negative, zero, or 20× the trailing median). Everything else stays.

### 6.4 Scheduling

```python
# ingestion/scheduler.py
scheduler.add_job(pull_prices,   "cron", hour=18, minute=30)   # after mandi close
scheduler.add_job(pull_weather,  "cron", hour=5,  minute=0)
scheduler.add_job(pull_shocks,   "interval", hours=6)
scheduler.add_job(build_features,"cron", hour=19, minute=0)
scheduler.add_job(retrain_model, "cron", hour=1,  minute=0)    # nightly
scheduler.add_job(precompute_forecasts, "cron", hour=2, minute=0)
scheduler.add_job(fire_alerts,   "cron", hour=7,  minute=0)    # morning push
```

---

## 7. Database schema

PostgreSQL 15+. TimescaleDB is optional — turn `price_observations` into a hypertable if you want, but a plain table with a good index handles a hackathon-scale dataset fine.

```sql
-- ─────────────────────────── reference tables ───────────────────────────

CREATE TABLE states (
    id              SERIAL PRIMARY KEY,
    name            TEXT UNIQUE NOT NULL,
    apmc_cess_pct   NUMERIC(5,3) NOT NULL DEFAULT 1.0,
    commission_pct  NUMERIC(5,3) NOT NULL DEFAULT 2.0,
    other_fees_pct  NUMERIC(5,3) NOT NULL DEFAULT 0.5
);

CREATE TABLE mandis (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    normalised_name TEXT NOT NULL,
    district        TEXT,
    state_id        INT REFERENCES states(id),
    apmc_code       TEXT,
    lat             DOUBLE PRECISION,
    lon             DOUBLE PRECISION,
    is_enam         BOOLEAN DEFAULT FALSE,
    active          BOOLEAN DEFAULT TRUE,
    UNIQUE (normalised_name, district, state_id)
);
CREATE INDEX idx_mandis_geo ON mandis (lat, lon);

CREATE TABLE commodities (
    id                  SERIAL PRIMARY KEY,
    name                TEXT NOT NULL,
    variety             TEXT,
    crop_group          TEXT,          -- cereal | pulse | oilseed | vegetable | fruit | spice
    perishability_class SMALLINT,      -- 1 = very perishable ... 5 = storable
    shelf_life_days     INT,           -- ambient, ungraded
    msp_applicable      BOOLEAN DEFAULT FALSE,
    UNIQUE (name, variety)
);

CREATE TABLE commodity_aliases (
    alias        TEXT PRIMARY KEY,
    commodity_id INT REFERENCES commodities(id)
);

CREATE TABLE msp_schedule (
    commodity_id INT REFERENCES commodities(id),
    season       TEXT,                 -- kharif_2025 | rabi_2025_26
    msp_per_qtl  NUMERIC(10,2),
    valid_from   DATE,
    valid_to     DATE,
    PRIMARY KEY (commodity_id, season)
);

-- ─────────────────────────── core time series ───────────────────────────

CREATE TABLE price_observations (
    id              BIGSERIAL PRIMARY KEY,
    obs_date        DATE NOT NULL,
    mandi_id        INT  NOT NULL REFERENCES mandis(id),
    commodity_id    INT  NOT NULL REFERENCES commodities(id),
    variety         TEXT,
    grade           TEXT,
    min_price       NUMERIC(10,2),
    max_price       NUMERIC(10,2),
    modal_price     NUMERIC(10,2) NOT NULL,
    arrival_qtl     NUMERIC(12,2),      -- normalised to quintals
    source          TEXT NOT NULL,      -- agmarknet_api | agmarknet_scrape | kaggle_backfill
    is_imputed      BOOLEAN DEFAULT FALSE,
    suspect         BOOLEAN DEFAULT FALSE,
    raw             JSONB,
    ingested_at     TIMESTAMPTZ DEFAULT now(),
    UNIQUE (obs_date, mandi_id, commodity_id, variety, grade)
);
CREATE INDEX idx_po_lookup ON price_observations (commodity_id, mandi_id, obs_date DESC);
CREATE INDEX idx_po_date   ON price_observations (obs_date DESC);

CREATE TABLE weather_daily (
    obs_date     DATE,
    mandi_id     INT REFERENCES mandis(id),
    rainfall_mm  NUMERIC(6,2),
    tmax_c       NUMERIC(5,2),
    tmin_c       NUMERIC(5,2),
    humidity_pct NUMERIC(5,2),
    is_forecast  BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (obs_date, mandi_id)
);

CREATE TABLE shock_events (
    id            SERIAL PRIMARY KEY,
    event_date    DATE NOT NULL,
    event_type    TEXT NOT NULL,   -- export_ban | export_allowed | stock_limit |
                                   -- msp_hike | import_duty | buffer_release | strike
    commodity_id  INT REFERENCES commodities(id),
    scope         TEXT,            -- national | state:<name>
    direction     SMALLINT,        -- -1 bearish for farmer, +1 bullish
    magnitude     SMALLINT,        -- 1 low, 2 medium, 3 high
    source_url    TEXT,
    title         TEXT,
    decay_days    INT DEFAULT 30
);

CREATE TABLE festivals (
    fest_date DATE PRIMARY KEY,
    name      TEXT,
    demand_effect JSONB   -- {"vegetable": 1, "oilseed": 0, "pulse": 1}
);

-- ─────────────────────────── model outputs ──────────────────────────────

CREATE TABLE forecasts (
    id            BIGSERIAL PRIMARY KEY,
    issued_at     TIMESTAMPTZ NOT NULL,
    issued_for    DATE NOT NULL,       -- as-of date of information used
    target_date   DATE NOT NULL,
    horizon_days  SMALLINT NOT NULL,
    mandi_id      INT REFERENCES mandis(id),
    commodity_id  INT REFERENCES commodities(id),
    p10           NUMERIC(10,2),
    p50           NUMERIC(10,2),
    p90           NUMERIC(10,2),
    model_version TEXT NOT NULL,
    features_hash TEXT,
    UNIQUE (issued_for, target_date, mandi_id, commodity_id, model_version)
);
CREATE INDEX idx_fc_lookup ON forecasts (mandi_id, commodity_id, target_date);

CREATE TABLE model_registry (
    version        TEXT PRIMARY KEY,
    trained_at     TIMESTAMPTZ,
    train_start    DATE,
    train_end      DATE,
    algo           TEXT,
    params         JSONB,
    metrics        JSONB,     -- {"mape_h7": 8.2, "coverage_80": 0.79, "rupee_uplift_pct": 8.4}
    is_active      BOOLEAN DEFAULT FALSE,
    artifact_path  TEXT
);

-- ─────────────────────────── users and the loop ─────────────────────────

CREATE TABLE farmers (
    id             BIGSERIAL PRIMARY KEY,
    phone_e164     TEXT UNIQUE NOT NULL,
    name           TEXT,
    language       TEXT DEFAULT 'mr',       -- mr | hi | en
    village        TEXT,
    lat            DOUBLE PRECISION,
    lon            DOUBLE PRECISION,
    home_mandi_id  INT REFERENCES mandis(id),
    risk_profile   TEXT DEFAULT 'balanced', -- cautious | balanced | aggressive
    fpo_id         INT,
    consent_at     TIMESTAMPTZ,
    created_at     TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE lots (
    id             BIGSERIAL PRIMARY KEY,
    farmer_id      BIGINT REFERENCES farmers(id),
    commodity_id   INT REFERENCES commodities(id),
    variety        TEXT,
    quantity_qtl   NUMERIC(10,2) NOT NULL,
    remaining_qtl  NUMERIC(10,2) NOT NULL,
    harvest_date   DATE,
    quality_grade  TEXT DEFAULT 'B',   -- A | B | C, self-declared or photo-graded
    storage_type   TEXT DEFAULT 'ambient', -- ambient | shed | cold_store
    status         TEXT DEFAULT 'open',    -- open | partially_sold | closed
    created_at     TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE recommendations (
    id              BIGSERIAL PRIMARY KEY,
    lot_id          BIGINT REFERENCES lots(id),
    issued_at       TIMESTAMPTZ DEFAULT now(),
    action          TEXT,               -- sell_now | hold | split
    sell_now_qtl    NUMERIC(10,2),
    hold_qtl        NUMERIC(10,2),
    hold_days       SMALLINT,
    target_mandi_id INT REFERENCES mandis(id),
    expected_net_now      NUMERIC(12,2),
    expected_net_strategy NUMERIC(12,2),
    expected_gain         NUMERIC(12,2),
    confidence      NUMERIC(4,3),
    reason_code     TEXT,
    reason_text     TEXT,
    model_version   TEXT,
    payload         JSONB               -- full alternatives considered
);

-- ⭐ THE MOAT TABLE
CREATE TABLE sale_reports (
    id                BIGSERIAL PRIMARY KEY,
    lot_id            BIGINT REFERENCES lots(id),
    farmer_id         BIGINT REFERENCES farmers(id),
    recommendation_id BIGINT REFERENCES recommendations(id),
    sale_date         DATE NOT NULL,
    mandi_id          INT REFERENCES mandis(id),
    channel           TEXT,             -- mandi | fpo | private_trader | procurement | direct
    quantity_qtl      NUMERIC(10,2),
    gross_price_qtl   NUMERIC(10,2),    -- rate quoted to him
    net_received_qtl  NUMERIC(10,2),    -- what he actually took home, per quintal
    deductions_json   JSONB,            -- {"commission": 420, "hamali": 160, "weighing": 40}
    followed_advice   BOOLEAN,
    reported_at       TIMESTAMPTZ DEFAULT now(),
    verification      TEXT DEFAULT 'self_reported' -- self_reported | slip_photo | fpo_verified
);
CREATE INDEX idx_sr_mandi ON sale_reports (mandi_id, sale_date DESC);

CREATE TABLE transparency_scores (
    mandi_id      INT,
    commodity_id  INT,
    window_end    DATE,
    n_reports     INT,
    median_gap_pct NUMERIC(6,3),   -- (official_modal - farmer_net) / official_modal
    shrunk_gap_pct NUMERIC(6,3),   -- empirical-Bayes shrunk toward global mean
    score         NUMERIC(4,1),    -- 0-10, 10 = most transparent
    PRIMARY KEY (mandi_id, commodity_id, window_end)
);

CREATE TABLE alerts (
    id           BIGSERIAL PRIMARY KEY,
    farmer_id    BIGINT REFERENCES farmers(id),
    lot_id       BIGINT REFERENCES lots(id),
    alert_type   TEXT,   -- sell_window | price_drop | shock | msp_floor | pool_truck
    payload      JSONB,
    sent_at      TIMESTAMPTZ,
    delivered    BOOLEAN,
    acted_on     BOOLEAN
);

CREATE TABLE ingestion_runs (
    id          BIGSERIAL PRIMARY KEY,
    job         TEXT,
    started_at  TIMESTAMPTZ,
    ended_at    TIMESTAMPTZ,
    status      TEXT,       -- ok | partial | failed
    rows_in     INT,
    rows_kept   INT,
    rows_rejected INT,
    error       TEXT
);
```

---

## 8. Feature engineering

### 8.1 The golden rule: point-in-time correctness

Every feature for a row with `as_of_date = D` must be computable using **only** data that existed on or before `D`. This is the number one source of fake accuracy in price prediction projects. Two specific traps:

- **Revisions.** If a mandi uploads yesterday's price two days late, a naive query on `obs_date` will hand your training set information it could not have had. Filter on `ingested_at <= D` as well as `obs_date <= D`, or accept a one-day lag on everything.
- **Weather.** Past weather is fine. Future weather is fine **only** if you use the *forecast* that was available on D, not the observed value. Store `is_forecast` and use forecasted weather for future-facing features.

### 8.2 Target definition

Do not predict the raw price. Predict the **log return over the horizon**:

```
y_h = log( modal_price[t + h] / modal_price[t] )
```

Why:
- Makes the target roughly stationary across crops with wildly different price levels (₹1,800 wheat vs ₹9,000 chilli).
- Lets a single global model serve every commodity.
- Errors are naturally proportional, which is how a farmer thinks (a 5% miss on onion and a 5% miss on soybean feel the same).

At serve time you invert: `price_hat = modal_price[t] * exp(y_hat)`.

Horizons trained: `h ∈ {1, 3, 7, 15}`. One model per (quantile × horizon) → 3 × 4 = **12 LightGBM models**, all small, all trained in seconds.

### 8.3 Full feature list

**A. Price history (the base)**
| Feature | Definition |
|---|---|
| `lag_1, lag_3, lag_7, lag_14, lag_30` | log return over the trailing window |
| `roll_mean_7, roll_mean_14, roll_mean_30` | mean log price |
| `roll_std_7, roll_std_30` | realised volatility — drives band width |
| `price_vs_ma30` | `log(price / roll_mean_30)` — how stretched is it |
| `days_since_max_90`, `days_since_min_90` | position within recent range |
| `spread_pct` | `(max_price - min_price) / modal_price` — intra-day dispersion, a quality/uncertainty proxy |

**B. Arrivals — the leading indicator most projects ignore**

Price is a *lagging* variable; arrivals are *leading*. Agmarknet publishes arrivals in the same row as price and almost nobody uses them.

| Feature | Definition | Intuition |
|---|---|---|
| `arr_lag_1, arr_lag_3, arr_lag_7` | log change in arrival quantity | supply pulse |
| `arr_vs_ma30` | `log(arrivals / 30-day mean arrivals)` | glut or scarcity right now |
| `arr_zscore_seasonal` | arrivals vs same week-of-year historical mean | is this unusual *for this time of year* |
| `arr_momentum` | slope of a 7-day linear fit on log arrivals | supply accelerating or fading |
| `price_arrival_elasticity` | rolling 60-day regression coefficient of Δlog price on Δlog arrivals | how sensitive this mandi is to supply |

**C. Spatial / cross-mandi**
| Feature | Definition |
|---|---|
| `nbr_price_mean_k5` | mean modal price of 5 nearest mandis (by road distance) |
| `price_vs_nbr` | `log(own price / neighbour mean)` — is this mandi cheap or dear right now |
| `nbr_arr_change` | neighbours' arrival change — supply moving toward you |
| `state_price_index` | state-level volume-weighted price index for the commodity |
| `terminal_market_price` | price at the big consuming terminal (Delhi/Mumbai/Kolkata) — pulls regional prices |

**D. Calendar and season**
| Feature | Definition |
|---|---|
| `dow`, `month`, `week_of_year` | categorical |
| `days_to_festival`, `festival_demand_effect` | from `festivals` table, crop-group specific |
| `harvest_season_flag` | is this commodity in its arrival peak in this state |
| `days_into_season` | position within kharif/rabi arrival window |
| `is_market_holiday_tomorrow` | pre-holiday arrivals surge |

**E. Weather**
| Feature | Definition |
|---|---|
| `rain_7d_sum`, `rain_30d_sum` | past rainfall at the mandi's district |
| `rain_forecast_7d` | forecast rainfall (available at prediction time) |
| `tmax_7d_mean`, `heat_stress_days` | days above crop-specific threshold |
| `unseasonal_rain_flag` | rainfall > 2σ above the week-of-year norm — damages standing crop and accelerates distress selling |

**F. Policy / shock (from Shock Radar)**
| Feature | Definition |
|---|---|
| `shock_active_bearish`, `shock_active_bullish` | decayed indicator, see §12 |
| `days_since_shock` | recency |
| `msp_gap_pct` | `(modal_price - msp) / msp` — below zero means procurement is the better channel |
| `fuel_price_index` | diesel price, drives transport cost and trader margins |

**G. Entity embeddings (what makes the global model work)**
| Feature | Definition |
|---|---|
| `mandi_id` | LightGBM categorical |
| `commodity_id` | LightGBM categorical |
| `state_id` | LightGBM categorical |
| `perishability_class` | ordinal |
| `mandi_liquidity` | mean daily arrivals over 90 days — thin markets are noisier |
| `mandi_data_quality` | share of non-imputed observations in last 90 days |

**H. Data-quality guards (feed these to the model, don't hide them)**
| Feature | Definition |
|---|---|
| `days_since_observation` | staleness of the last real print |
| `imputed_share_14d` | fraction of the last 14 days that were filled |

### 8.4 Implementation note

```python
# features/builder.py
def build_features(as_of: date, mandi_id: int, commodity_id: int,
                   conn) -> dict:
    """
    THE SAME function is used for training (looped over history)
    and for serving (called once). Never write two versions.
    """
    series = load_series(conn, mandi_id, commodity_id,
                         end=as_of, lookback_days=400,
                         ingested_before=as_of)   # point-in-time guard
    ...
    return feats
```

Training set generation is then just:

```python
rows = []
for (m, c) in pairs:
    for d in business_days(train_start, train_end):
        f = build_features(d, m, c, conn)
        for h in HORIZONS:
            y = log_return(m, c, d, h)
            if y is not None:
                rows.append({**f, "horizon": h, "y": y})
```

Cache aggressively (the rolling windows dominate runtime). For 3 crops × 5 mandis × 3 years × 4 horizons you get roughly 45,000 rows — trivial.

---

## 9. The forecasting model

### 9.1 Baselines first (non-negotiable)

Build and score these **before** any ML. If the ML does not beat them, you have learned something important and cheap.

| Baseline | Definition |
|---|---|
| `naive` | `price[t+h] = price[t]` |
| `seasonal_naive` | `price[t+h] = price[t+h-365]` |
| `drift` | linear extrapolation of the last 30 days |
| `ma7` | trailing 7-day mean |

Report every model against these in the same table. Judges notice this. It is a two-hour investment that buys enormous credibility.

### 9.2 Main model: LightGBM with quantile objective

**Why gradient boosting and not LSTM/Transformer:**

- Tabular, moderate-size, heavy on engineered exogenous features — exactly GBDT's home turf. Deep sequence models reliably lose here unless you have millions of rows.
- Trains in seconds on a laptop. You will retrain fifty times during the hackathon.
- Handles missing values natively (and mandi data is full of them).
- Native categorical support for `mandi_id` / `commodity_id` → the global model works.
- Feature importance and SHAP come free, which powers the plain-language explanation (P4).

**Quantile regression** gives the bands directly. Train three models per horizon:

```python
# models/train.py
import lightgbm as lgb

QUANTILES = {"p10": 0.10, "p50": 0.50, "p90": 0.90}
HORIZONS  = [1, 3, 7, 15]

BASE_PARAMS = dict(
    objective="quantile",
    metric="quantile",
    learning_rate=0.05,
    num_leaves=63,
    min_data_in_leaf=40,
    feature_fraction=0.8,
    bagging_fraction=0.8,
    bagging_freq=1,
    lambda_l2=1.0,
    max_bin=255,
    verbosity=-1,
    num_threads=4,
)

CATEGORICALS = ["mandi_id", "commodity_id", "state_id", "dow", "month"]

def train_all(df):
    models = {}
    for h in HORIZONS:
        sub = df[df.horizon == h]
        X, y = sub[FEATURES], sub["y"]
        for qname, alpha in QUANTILES.items():
            params = {**BASE_PARAMS, "alpha": alpha}
            ds = lgb.Dataset(X, label=y, categorical_feature=CATEGORICALS,
                             free_raw_data=False)
            models[(h, qname)] = lgb.train(params, ds, num_boost_round=800,
                                           valid_sets=[ds],
                                           callbacks=[lgb.early_stopping(60, verbose=False)])
    return models
```

**Monotonicity fix:** quantile models are trained independently, so occasionally `p10 > p50`. Always sort the three outputs before returning them.

```python
p10, p50, p90 = sorted([m10, m50, m90])
```

### 9.3 One global model, not five thousand

Do **not** train a separate model per (mandi, commodity). Reasons:

- A thin mandi with 200 observations cannot support its own model.
- A new mandi has zero history — a global model handles it from day one via `state_id`, `perishability_class` and neighbour features.
- Cross-learning is real: what onion arrivals do to onion prices in Lasalgaon informs Pimpalgaon.
- Operationally, one artifact instead of thousands.

The `mandi_id` and `commodity_id` categoricals let the tree learn per-entity offsets where data supports it, and fall back to group behaviour where it doesn't. This is the same trick used in retail demand forecasting at scale.

### 9.4 Validation: walk-forward, never random split

Random K-fold on time series leaks the future into the past and will show you a beautiful, meaningless number.

```
Fold 1: train 2022-01 → 2023-12   validate 2024-01 → 2024-03
Fold 2: train 2022-01 → 2024-03   validate 2024-04 → 2024-06
Fold 3: train 2022-01 → 2024-06   validate 2024-07 → 2024-09
Fold 4: train 2022-01 → 2024-09   validate 2024-10 → 2024-12
```

Add a **purge gap** of `h` days between train end and validation start so that a 15-day-horizon label does not overlap the training window.

### 9.5 Metrics

| Metric | What it tells you | Target |
|---|---|---|
| **MAPE** per horizon | typical error size | h=1: <4%, h=7: <9%, h=15: <14% for staples; perishables will be worse and that's honest |
| **sMAPE** | MAPE's asymmetry fixed | report alongside |
| **Pinball loss** | correctness of the *whole distribution*, the right loss for quantiles | lower than baseline |
| **PICP (coverage)** | share of actuals falling inside [P10, P90] | should be ≈ 0.80. If it's 0.95 your bands are lazily wide; if 0.55 you're overconfident |
| **Directional accuracy** | did we get up vs down right | > 60% is genuinely useful |
| **⭐ ₹-uplift** | see §15 | the headline |

### 9.6 Model registry and rollout

Every training run writes to `model_registry` with metrics. A new version becomes `is_active` only if it beats the current active model on **pinball loss and ₹-uplift** on the most recent fold. Otherwise it is kept but not promoted. This is a five-line guard that prevents a bad nightly retrain from silently degrading advice.

---

## 10. The Net In-Hand Realisation Engine

**This is the differentiator. Give it your best engineer.**

Everyone else predicts the mandi's gross modal price. We predict the money that reaches the farmer.

### 10.1 The formula

For a lot of quantity `Q` quintals, commodity `c`, sold at mandi `m`, `d` days from today:

```
GROSS      = P̂(m, c, t+d) × Q_effective × G(grade)

Q_effective = Q × (1 − S(c, d, storage, temp))        ← spoilage shrinkage

DEDUCTIONS =
      commission%(state)      × GROSS
    + apmc_cess%(state)       × GROSS
    + other_fees%(state)      × GROSS
    + hamali_per_qtl          × Q_effective
    + weighing_per_qtl        × Q_effective
    + packing/bags_per_qtl    × Q_effective

TRANSPORT  = ceil(Q_effective / truck_capacity) × road_km(village, m) × ₹_per_km
             (÷ n_farmers if pooled)

HOLDING    = storage_cost_per_qtl_per_day × Q × d
           + (GROSS_now × interest_rate_daily × d)      ← opportunity cost

NET_IN_HAND = GROSS − DEDUCTIONS − TRANSPORT − HOLDING
NET_PER_QTL = NET_IN_HAND / Q                            ← what we show the farmer
```

### 10.2 The spoilage model

`S(c, d, storage, temp)` = cumulative fraction lost after holding `d` days. Model it as an exponential with a crop-specific daily rate, modulated by storage type and temperature:

```
S(c, d, storage, temp) = 1 − exp( −k_c × f_storage × f_temp × d )

k_c        : base daily decay rate from perishability_class
f_storage  : ambient 1.0 | ventilated shed 0.7 | cold store 0.25
f_temp     : 1 + 0.04 × max(0, tmax_forecast_mean − 30)
```

Indicative `k_c` values (calibrate against CIPHET post-harvest loss studies — F&V losses of 20–25% overall are the sanity anchor):

| Crop | class | k_c (per day) | 10-day loss, ambient |
|---|---|---|---|
| Tomato | 1 | 0.030 | ~26% |
| Leafy greens | 1 | 0.045 | ~36% |
| Onion (cured) | 3 | 0.006 | ~6% |
| Potato | 3 | 0.005 | ~5% |
| Soybean | 5 | 0.0005 | ~0.5% |
| Wheat | 5 | 0.0003 | ~0.3% |

**This single function is why "hold for 10 days" is good advice for onion and terrible for tomato** — and no existing app makes that distinction.

### 10.3 The grade factor

```
G(grade): A = 1.08, B = 1.00, C = 0.88
```

Calibrate from the `min/max/modal` spread in your own data: a mandi's `max_price` roughly corresponds to A-grade, `min_price` to C. Later, replace self-declared grade with photo-based CV grading.

### 10.4 Cost config, not code

```yaml
# config/cost_model.yaml
defaults:
  hamali_per_qtl: 12
  weighing_per_qtl: 3
  packing_per_qtl: 8
  truck_capacity_qtl: 90
  transport_per_km: 42          # full truck, ₹/km
  interest_rate_annual: 0.14    # informal credit rate
  storage_cost_per_qtl_per_day:
    ambient: 0
    shed: 0.6
    cold_store: 3.5

states:
  Maharashtra:
    commission_pct: 3.0
    apmc_cess_pct: 1.05
    other_fees_pct: 0.3
  Punjab:
    commission_pct: 2.5
    apmc_cess_pct: 3.0
    other_fees_pct: 3.0        # rural development fee etc.
  Karnataka:
    commission_pct: 2.0
    apmc_cess_pct: 1.5
    other_fees_pct: 0.35
```

Keeping this in YAML means a judge can ask *"what if commission is 4% in that district?"* and you change one line live. That moment wins points.

### 10.5 Implementation

```python
# economics/net_realisation.py
from dataclasses import dataclass
import math

@dataclass
class NetResult:
    gross: float
    deductions: float
    transport: float
    holding: float
    spoilage_qtl: float
    net_total: float
    net_per_qtl: float
    breakdown: dict

def spoilage_fraction(k_c: float, days: int, storage: str,
                      tmax_mean: float, cfg) -> float:
    f_storage = cfg["storage_factor"][storage]
    f_temp = 1 + 0.04 * max(0.0, tmax_mean - 30)
    return 1 - math.exp(-k_c * f_storage * f_temp * days)

def net_in_hand(price_per_qtl, qty_qtl, days_held, mandi, commodity,
                farmer, cfg, tmax_mean, pooled_with=1) -> NetResult:
    s      = spoilage_fraction(commodity.k_c, days_held,
                               farmer.storage_type, tmax_mean, cfg)
    q_eff  = qty_qtl * (1 - s)
    grade  = cfg["grade_factor"][farmer.grade]
    gross  = price_per_qtl * q_eff * grade

    st = cfg["states"].get(mandi.state, cfg["states"]["_default"])
    pct_fees = (st["commission_pct"] + st["apmc_cess_pct"]
                + st["other_fees_pct"]) / 100.0
    per_qtl_fees = (cfg["hamali_per_qtl"] + cfg["weighing_per_qtl"]
                    + cfg["packing_per_qtl"])
    deductions = gross * pct_fees + q_eff * per_qtl_fees

    trucks    = math.ceil(q_eff / cfg["truck_capacity_qtl"])
    km        = road_distance_km(farmer.lat, farmer.lon, mandi.lat, mandi.lon)
    transport = trucks * km * cfg["transport_per_km"] / max(pooled_with, 1)

    daily_i   = cfg["interest_rate_annual"] / 365.0
    holding   = (cfg["storage_cost_per_qtl_per_day"][farmer.storage_type]
                 * qty_qtl * days_held) + (gross * daily_i * days_held)

    net = gross - deductions - transport - holding
    return NetResult(gross, deductions, transport, holding,
                     qty_qtl - q_eff, net, net / qty_qtl,
                     {"pct_fees": pct_fees, "km": km, "trucks": trucks,
                      "spoilage_pct": round(s * 100, 2)})
```

### 10.6 The demo moment

Rank three mandis by gross, then by net, and show the table flipping:

| Mandi | Distance | Gross ₹/qtl | Fees | Transport | Spoilage | **Net ₹/qtl** |
|---|---|---|---|---|---|---|
| Lasalgaon | 62 km | **2,010** | −87 | −29 | −0 | **1,894** |
| Pimpalgaon | 21 km | 1,960 | −85 | −10 | −0 | **1,865** |
| Nashik | 88 km | 1,995 | −86 | −41 | −0 | 1,868 |

The headline winner and the actual winner can be different mandis. Show that.

---

## 11. The Decision Engine

Turns forecasts + net economics into one imperative sentence.

### 11.1 The decision space

For a lot with quantity `Q`, enumerate:

- **Fraction to sell now**: `f ∈ {0, 0.25, 0.50, 0.75, 1.00}`
- **Hold horizon for the remainder**: `d ∈ {3, 7, 15}` days
- **Mandi for each tranche**: top-K nearest/best mandis, `K = 5`

That is 5 × 3 × 5 × 5 = 375 candidate strategies. Trivial to brute-force.

### 11.2 Objective function

We are not maximising expected rupees. A smallholder is **risk averse** — a 10% chance of losing ₹20,000 matters more to him than a 10% chance of gaining ₹20,000. Use a mean–risk objective:

```
Score(strategy) = E[Net]  −  λ · DownsideRisk(Net)

E[Net]          ≈ Net(P50)
DownsideRisk    = max(0, Net(P50) − Net(P10))       ← how bad the bad case is
λ               = 0.8 cautious | 0.45 balanced | 0.2 aggressive
```

`λ` comes from `farmers.risk_profile`. A farmer who has an outstanding loan should be on `cautious`.

Because `Net()` is monotone in price, evaluating it at P10/P50/P90 gives you the net-value quantiles directly — no simulation needed. (If you want a distribution, sample 1,000 prices from a lognormal fitted to the three quantiles and run the cost model over the sample. Costs about 20 ms and gives you a proper CVaR.)

### 11.3 Hard constraints

Applied before scoring — these override the optimiser:

1. **MSP floor.** If `P50(net) < MSP` and a procurement centre is operating for that commodity, the recommendation becomes *"sell to procurement"* regardless of score.
2. **Spoilage cliff.** If `spoilage_fraction(d) > 0.15`, that horizon is removed from the candidate set. No amount of expected price rise justifies losing a sixth of the crop.
3. **Minimum viable load.** If `remaining_qtl < 0.25 × truck_capacity` and no pooling partner exists, drop distant mandis — the transport per quintal makes them absurd.
4. **Confidence floor.** If band width `(P90−P10)/P50 > 0.35`, force `f ≥ 0.5` (sell at least half now). We do not gamble a farmer's crop on a forecast we don't trust.
5. **Shock override.** An active high-magnitude bearish shock (e.g. export ban announced 2 days ago) forces `f = 1.0` — sell everything now.

### 11.4 Code sketch

```python
# decision/engine.py
def optimise(lot, farmer, forecasts, mandis, cfg) -> Recommendation:
    lam = {"cautious": 0.8, "balanced": 0.45, "aggressive": 0.2}[farmer.risk_profile]
    candidates = []

    for f in (0.0, 0.25, 0.5, 0.75, 1.0):
        for d in (3, 7, 15):
            if spoilage_fraction(lot.k_c, d, farmer.storage_type,
                                 tmax_mean(d), cfg) > 0.15 and f < 1.0:
                continue
            for m_now in top_k_mandis(farmer, k=5):
                for m_later in top_k_mandis(farmer, k=5):
                    q_now, q_later = lot.remaining_qtl * f, lot.remaining_qtl * (1 - f)

                    now = net_in_hand(forecasts[m_now][0].p50, q_now, 0, m_now, ...)
                    lo  = net_in_hand(forecasts[m_later][d].p10, q_later, d, m_later, ...)
                    md  = net_in_hand(forecasts[m_later][d].p50, q_later, d, m_later, ...)

                    e_net    = now.net_total + md.net_total
                    downside = max(0.0, md.net_total - lo.net_total)
                    score    = e_net - lam * downside
                    candidates.append(Candidate(f, d, m_now, m_later,
                                                e_net, downside, score))

    best     = max(candidates, key=lambda c: c.score)
    baseline = sell_all_now_nearest(lot, farmer, forecasts, cfg)
    return build_recommendation(best, baseline, confidence(forecasts))
```

### 11.5 Confidence score

Shown to the farmer as a percentage. Blend three things:

```
confidence = w1 · band_tightness + w2 · data_quality + w3 · historical_hit_rate

band_tightness       = clip(1 − (P90−P10)/(2·P50) / 0.30, 0, 1)
data_quality         = 1 − imputed_share_14d
historical_hit_rate  = rolling PICP for this (mandi, commodity) over last 60 days
weights              = 0.5, 0.2, 0.3
```

If confidence < 0.5, the message says so explicitly: *"market is unusually unpredictable this week — safer to sell now."*

### 11.6 Explanation generation

Take the top 3 SHAP contributors for the P50 model on this row, map each feature to a template, pick the two with the largest absolute contribution:

```python
TEMPLATES = {
  "arr_vs_ma30":      ("arrivals are {pct}% {dir} than usual", "down→prices likely up"),
  "days_to_festival": ("{fest} demand starts in {n} days", None),
  "shock_active_bearish": ("{event} announced {n} days ago", None),
  "rain_forecast_7d": ("heavy rain expected in {n} days", None),
  "price_vs_nbr":     ("nearby mandis are paying {pct}% more", None),
  "roll_std_30":      ("prices have been swinging a lot this month", None),
}
```

Output: **"Arrivals are 22% below normal and Diwali demand starts in 11 days."** Two clauses, no jargon, no numbers the farmer can't use.

---

## 12. Shock Radar

Most large price moves in Indian agri markets are event-driven, not trend-driven: an onion export ban, a stock limit under the Essential Commodities Act, an MSP announcement, a buffer stock release, unseasonal rain, a transport strike. A pure time-series model sees these as unexplained shocks *after* they hit. We feed them in as features *when they are announced*.

### 12.1 Sources and parsing

```python
SHOCK_PATTERNS = [
    (r"export.*(prohibit|ban|restrict)",        "export_ban",     -1, 3),
    (r"minimum export price|MEP",               "export_ban",     -1, 2),
    (r"export.*(allow|permit|lift)",            "export_allowed", +1, 3),
    (r"stock limit|stockholding limit",         "stock_limit",    -1, 2),
    (r"import duty.*(increase|hike|raise)",     "import_duty",    +1, 2),
    (r"import duty.*(cut|reduce|remove)",       "import_duty",    -1, 2),
    (r"buffer.*(release|offload|disposal)",     "buffer_release", -1, 2),
    (r"minimum support price.*(increase|hike)", "msp_hike",       +1, 1),
]
```

Poll DGFT notifications, PIB releases and the Department of Consumer Affairs feed every 6 hours. Match commodity names against `commodity_aliases`. Store direction (+1 bullish for the farmer, −1 bearish) and magnitude (1–3).

### 12.2 Decay

A shock's effect fades. Convert each event into a decaying feature:

```
shock_feature(t) = Σ_events  direction × magnitude × exp( −(t − event_date) / τ )
τ = decay_days / 3        (default decay_days = 30 → τ ≈ 10)
```

Two separate accumulators, `shock_active_bullish` and `shock_active_bearish`, so the model can learn asymmetric responses — and they usually are asymmetric. Bad news moves prices faster than good news.

### 12.3 Cold start

You will not have years of labelled shock events. That is fine — for the hackathon, hand-curate 20–30 major events for your three commodities from the last three years (an hour of work with news search), plus the live parser for the demo. Hand-curated history is real history.

---

## 13. The Ground-Truth Loop and Mandi Transparency Score

**This is the part that has not been built before, and it is what makes the system compound.**

### 13.1 The mechanism

After a farmer sells, the bot asks one question:

> *"आपल्याला प्रत्यक्ष किती भाव मिळाला?"* — "What price did you actually get?"

Optionally: a photo of the sale slip (`verification = 'slip_photo'`).

That one number produces three assets nobody else has:

| Asset | Why it matters |
|---|---|
| **A real farmgate price series** | Official data is trader/committee reported. Farmer-reported net realisation is a different, more honest number. The gap between them has never been measured at scale. |
| **The Mandi Transparency Score** | Reports of quality being deliberately downgraded and produce being bought below MSP are widespread. This turns anecdote into a measurable, mandi-by-mandi number. |
| **Free training labels** | Every sale is a supervised example. The system gets more accurate the more it is used — a moat that widens automatically. |

### 13.2 Score computation

For mandi `m`, commodity `c`, over a trailing 90-day window:

```
For each report r:
    expected_net_r = official_modal(m, c, sale_date) × G(grade)
                     − standard_deductions_per_config
    gap_r = (expected_net_r − reported_net_r) / expected_net_r
```

`gap_r` is the *unexplained* shortfall — we have already subtracted the deductions that are legitimate and known. Then:

```
raw_gap(m,c)   = trimmed_median({gap_r}, trim=10%)     ← robust to lying/typos
n              = number of reports
global_gap     = trimmed_median over all mandis
```

Shrink toward the global mean (empirical Bayes) so that a mandi with 3 reports doesn't get branded:

```
shrunk_gap = (n · raw_gap + k · global_gap) / (n + k),   k = 15

score = clip( 10 × (1 − shrunk_gap / 0.25), 0, 10 )
```

So a mandi with zero unexplained gap scores 10; one where farmers systematically lose 25% below the explainable level scores 0.

### 13.3 Anti-gaming (a judge will ask this)

| Attack | Mitigation |
|---|---|
| A farmer under-reports to punish a mandi | Trimmed median, not mean; cap each farmer's contribution to one report per (mandi, commodity, week) |
| A trader floods fake good reports | Reports only count from phone-verified farmers with a registered lot that matches the quantity; weight `slip_photo` and `fpo_verified` reports 3× |
| Small-sample defamation | Shrinkage + a hard rule: **do not display a score below `n = 10`**, show "not enough data yet" |
| Typos (₹18 instead of ₹1,800) | Reject values outside `[0.3×, 2.0×]` of official modal, ask again |

### 13.4 Publish it carefully

Display the score as a *relative* signal ("this mandi pays 6% below the district average, based on 34 reports"), never as an accusation of a named individual. Aggregate to mandi level, never to trader level, in v1. This is both legally safer and factually more defensible.

### 13.5 Cold start

Chicken-and-egg: no reports → no score. Solve it by going **deep, not wide**. Partner with one FPO, one district, one crop, 200 farmers. Density beats coverage. Seed the demo with 30–50 realistic entries so the mechanism is visible, and be transparent in the pitch that these are seed values.

---

## 14. Glut Early Warning (stretch module)

Cut this first if you are behind schedule. But if you land it, it is the most strategically interesting feature in the system.

### 14.1 The problem it solves

The cobweb cycle: onion pays well this year → everyone plants onion → next year supply doubles → price collapses → everyone abandons onion → shortage → price spikes. Repeat forever. It costs Indian farmers enormously and no consumer product warns about it.

### 14.2 Three supply signals

1. **User sowing declarations.** At sowing time, the bot asks what and how much each farmer is planting. Aggregate by district. If declared onion area among your users is up 38% year-on-year, that is a genuine leading signal — and it costs nothing to collect.
2. **Satellite acreage (NDVI).** Sentinel-2 based crop acreage estimation is well established, and commodity traders already buy exactly this intelligence to get ahead of official crop reports. You are taking a trader's tool and pointing it the other way. Implementation: monthly NDVI composites over district boundaries, a simple supervised classifier trained on known crop-mask samples, then area summation.
3. **Arrival-based nowcasting.** Cumulative season-to-date arrivals vs the same point in past seasons, extrapolated with the historical arrival curve shape.

### 14.3 Model

A simple, defensible relationship — do not over-engineer this:

```
log(harvest_season_avg_price) ~ β0
                              + β1 · log(estimated_area)
                              + β2 · log(area_lag_1)         # cobweb term
                              + β3 · rainfall_anomaly
                              + β4 · log(previous_season_price)
                              + β5 · carryover_stock_proxy
```

Fit per (commodity, region) on 10+ years of area/production data from the Directorate of Economics & Statistics. Report the answer as a **probability band**, not a point:

> *"Onion prices in November are likely to be 20–35% below last year. Consider limiting onion to 60% of your plot and splitting the rest to X."*

### 14.4 The ethical catch (mention this in your pitch — it shows maturity)

If everyone follows the advice, the glut does not happen and the prediction is "wrong." That is success, not failure. But it also means the advice must be given as a *distribution across alternatives*, not a single crop to switch to — otherwise you create the next glut in that crop. Recommend **diversification**, never a single substitute. Say this out loud to the judges; almost nobody thinks about it.

---

## 15. Evaluation and backtesting

### 15.1 The headline metric: ₹-uplift

This is what wins the hackathon. Define it precisely and defend it.

```
For each historical lot scenario (mandi m, commodity c, harvest date D, quantity Q):

  BASELINE strategy:  sell 100% at the nearest mandi on date D
     baseline_net = NetInHand(actual_price[m_near, D], Q, days=0, ...)

  MODEL strategy:     run the decision engine using ONLY information
                      available on date D, then settle every tranche at
                      the ACTUAL realised price on its execution date
     model_net    = Σ_tranches NetInHand(actual_price[m_t, D + d_t],
                                         Q_t, days=d_t, ...)

  uplift_pct = (model_net − baseline_net) / baseline_net
```

Report all of these, not just the mean:

| Statistic | Why |
|---|---|
| Mean uplift % | the headline |
| Median uplift % | robust to a few lucky trades |
| **Win rate** (share of scenarios with uplift > 0) | > 60% is what matters to a risk-averse farmer |
| **Worst-case uplift (5th percentile)** | how badly can following our advice hurt? Be honest. |
| Uplift by crop | perishables will look worse — say so |
| Uplift net of all costs | already included by construction |

### 15.2 Backtest protocol

1. Freeze a test period the model never saw (e.g. the most recent 6 months).
2. Generate scenarios: for each (mandi, commodity), simulate a lot on every 5th day, with a realistic quantity distribution (log-normal centred on 25 quintals).
3. At each scenario date, rebuild features **point-in-time** and call the live decision engine code path — not a special backtest path. If backtest and production use different code, your backtest is fiction.
4. Settle tranches at actual prices, applying the actual spoilage model.
5. Aggregate.

### 15.3 Ablation table (a slide that wins arguments)

| Configuration | MAPE h=7 | PICP | ₹-uplift |
|---|---|---|---|
| Naive (sell now) | — | — | 0.0% (by definition) |
| Price-only LightGBM | 10.9% | 0.71 | +3.1% |
| \+ arrivals features | 9.2% | 0.76 | +5.8% |
| \+ weather | 8.9% | 0.78 | +6.4% |
| \+ shock radar | 8.4% | 0.80 | +7.6% |
| \+ net-cost decision engine | 8.4% | 0.80 | **+8.4%** |

*(Fill these with your real numbers. The shape of the table — each feature group earning its place — is the argument.)*

Notice the last row: the model didn't get more accurate, but the *farmer earned more*. That is the entire thesis of the project in one row.

### 15.4 Live monitoring

- Daily PICP tracking per commodity — if coverage drifts below 0.65, alert.
- Feature drift: PSI on the top 15 features versus the training distribution.
- Advice-follow rate and realised uplift from `sale_reports` — the only truly honest metric, available once the loop is running.

---

## 16. API specification

FastAPI. All responses JSON. Auth via API key header for the dashboard; the WhatsApp webhook uses signature verification.

### `GET /api/v1/forecast`

```
Query: mandi_id, commodity_id, horizons=1,3,7,15
```

```json
{
  "mandi": {"id": 412, "name": "Lasalgaon", "district": "Nashik"},
  "commodity": {"id": 27, "name": "Onion", "variety": "Red"},
  "as_of": "2026-08-12",
  "current_modal": 1860.0,
  "forecasts": [
    {"horizon_days": 1,  "target_date": "2026-08-13", "p10": 1810, "p50": 1875, "p90": 1950},
    {"horizon_days": 7,  "target_date": "2026-08-19", "p10": 1760, "p50": 1985, "p90": 2210},
    {"horizon_days": 15, "target_date": "2026-08-27", "p10": 1690, "p50": 2040, "p90": 2480}
  ],
  "confidence": 0.71,
  "model_version": "lgbm-q-2026.08.11-a",
  "drivers": [
    {"feature": "arr_vs_ma30",      "contribution": -0.041, "text": "arrivals 22% below normal"},
    {"feature": "days_to_festival", "contribution":  0.028, "text": "Diwali demand in 11 days"}
  ]
}
```

### `POST /api/v1/recommend`

```json
{
  "farmer_id": 88,
  "lot": {"commodity_id": 27, "quantity_qtl": 80, "grade": "B",
          "harvest_date": "2026-08-11", "storage_type": "shed"},
  "max_distance_km": 120,
  "risk_profile": "balanced"
}
```

```json
{
  "recommendation_id": 5521,
  "action": "split",
  "tranches": [
    {"quantity_qtl": 50, "when": "2026-08-12", "mandi_id": 412,
     "mandi_name": "Lasalgaon", "expected_net_per_qtl": 1842},
    {"quantity_qtl": 30, "when": "2026-08-21", "mandi_id": 412,
     "mandi_name": "Lasalgaon", "expected_net_per_qtl": 1961,
     "range_per_qtl": [1704, 2183]}
  ],
  "baseline": {"description": "sell all today at nearest mandi",
               "net_total": 145600},
  "strategy":  {"net_total": 159830},
  "expected_gain": 14230,
  "confidence": 0.71,
  "reason": "Arrivals are 22% below normal and Diwali demand starts in 11 days.",
  "constraints_applied": ["spoilage_ok", "above_msp"],
  "alternatives_considered": 375
}
```

### `GET /api/v1/mandis/compare`

Returns the gross-vs-net ranking table from §10.6. This endpoint powers the single best visual in the demo.

### `POST /api/v1/sale-report`

```json
{
  "lot_id": 991, "recommendation_id": 5521,
  "sale_date": "2026-08-12", "mandi_id": 412,
  "quantity_qtl": 50, "gross_price_qtl": 1890,
  "net_received_qtl": 1744,
  "deductions": {"commission": 2835, "hamali": 600, "weighing": 150},
  "followed_advice": true, "channel": "mandi"
}
```

Response echoes the computed unexplained gap and the mandi's updated score.

### `GET /api/v1/transparency/{mandi_id}`

```json
{
  "mandi_id": 412, "commodity_id": 27,
  "window": "2026-05-14..2026-08-12",
  "n_reports": 34,
  "median_gap_pct": 5.8,
  "score": 7.7,
  "interpretation": "Farmers here receive about 6% less than the official modal price after standard deductions, based on 34 reports."
}
```

### Other endpoints

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/farmers` | register / update profile, language, home mandi |
| `POST /api/v1/lots` | declare a harvested lot |
| `GET /api/v1/alerts` | pending alerts for a farmer |
| `POST /api/v1/pool/search` | find nearby farmers with the same crop for truck pooling |
| `GET /api/v1/model/accuracy` | public accuracy dashboard data (P5 honesty) |
| `POST /webhooks/whatsapp` | inbound WhatsApp messages |
| `GET /healthz`, `GET /readyz` | ops |

---

## 17. WhatsApp bot design

### 17.1 Why WhatsApp and not an app

A React Native app scores zero on real-world adoption. It requires a smartphone with space, a download, an account, literacy in a UI language, and a reason to open it. WhatsApp requires none of that — it is already installed, already used daily, and supports **voice notes**, which removes the literacy barrier entirely.

Add an **IVR / missed-call fallback**: farmer gives a missed call, system calls back with a text-to-speech reading of the same recommendation. Now feature phones work too.

### 17.2 Conversation flows

**Flow A — Registration (once)**
```
Farmer: [any message]
Bot:    नमस्कार! मी तुम्हाला योग्य भावाने विकायला मदत करेन.
        तुमचे गाव कोणते? (location pin किंवा नाव पाठवा)
Farmer: [location pin]
Bot:    धन्यवाद. जवळचा बाजार: पिंपळगाव. बरोबर आहे का? [होय / बदला]
```
Store: phone, language (detect from message or ask), lat/lon, home mandi.

**Flow B — Declare a lot**
```
Farmer: "कांदा 80 क्विंटल"        (or a voice note saying the same)
Bot:    कांदा, 80 क्विंटल नोंदवले.
        प्रत ? [A उत्तम / B साधारण / C कमी]
        साठवण ? [घरात / शेड / कोल्ड स्टोरेज]
```

**Flow C — Get advice (the core)**
```
Farmer: "आज विकू का?"
Bot:    आजच सगळं विकू नका.

        ✅ आज 50 क्विंटल लासलगावला विका → ₹1,842/क्विंटल हातात
        ⏳ 30 क्विंटल 9 दिवस थांबवा     → अंदाजे ₹1,961/क्विंटल

        कारण: आवक 22% कमी आहे आणि 11 दिवसांत दिवाळीची मागणी सुरू होते.
        अंदाजे जास्त मिळकत: ₹14,230
        खात्री: 71%

        [तपशील पहा] [इशारा लावा]
```

**Flow D — Alert (push, 7 AM)**
```
Bot:    ⚠️ लासलगावात कांद्याचा भाव 3 दिवसांत ₹120 वाढला आहे.
        तुमचे उरलेले 30 क्विंटल विकण्यासाठी ही चांगली वेळ आहे.
```

**Flow E — The loop (24h after a recommended sale date)**
```
Bot:    काल विक्री झाली का? प्रत्यक्ष किती भाव मिळाला?
Farmer: "1880"
Bot:    नोंदवले, धन्यवाद 🙏
        अधिकृत दर ₹1,890 होता — तुम्हाला जवळपास योग्य भाव मिळाला.
        (या माहितीमुळे आमचा अंदाज अधिक अचूक होतो.)
```

### 17.3 Technical implementation

- **WhatsApp Cloud API** (Meta). Webhook receives messages; Graph API sends. Template messages for the 7 AM push (outside the 24-hour window); free-form for replies inside it.
- **Voice notes:** download the audio, transcribe with a Marathi/Hindi ASR model, run through the same intent parser.
- **Intent parsing:** do NOT reach for an LLM first. A regex + keyword + fuzzy-match parser handles 90% of a bounded domain (crop names, numbers, yes/no, "विकू का"). Fall back to an LLM only for unmatched messages — cheaper, faster, and it does not hallucinate a price.
- **State machine** per farmer stored in Redis with a 24h TTL: `AWAITING_LOCATION → IDLE → AWAITING_GRADE → ...`
- **Message templates** in a `locales/{mr,hi,en}.yaml` file. Never concatenate translated strings in code.

### 17.4 Message-writing rules

1. Never more than 6 lines.
2. Rupees per quintal, always — never per kg, never totals only.
3. One reason, never three.
4. Confidence always shown.
5. Never use the words "model", "algorithm", "AI", "prediction".
6. Every message ends with an action or a button.

---

## 18. Web dashboard

The dashboard is **not for the farmer**. It is for judges, FPO managers, and agri officers. Build it last.

Next.js + Tailwind + Recharts. Six screens:

| Screen | Contents |
|---|---|
| **Live map** | Mandis as markers, colour = today's price vs 30-day mean, size = arrivals. Click → detail. |
| **Forecast view** | Price history line + forecast fan chart (P10–P90 shaded). The single most persuasive visual you own. |
| **Net comparison** | The gross-vs-net mandi table from §10.6, with the ranking visibly flipping. |
| **Accuracy** | Live MAPE, PICP, directional accuracy per crop, and the ablation table. Publishing your own error rate is a trust move very few teams make. |
| **Transparency map** | Mandi Transparency Scores, choropleth by district, with report counts. |
| **FPO console** | Member lots, aggregate pooling opportunities, group recommendation. |

---

## 19. Repository structure

```
bhav-setu/
├── README.md
├── docker-compose.yml
├── .env.example
├── Makefile
│
├── config/
│   ├── cost_model.yaml          # fees, transport, storage, grade factors
│   ├── crops.yaml               # k_c decay rates, shelf life, MSP flags
│   ├── sources.yaml             # API resource IDs, endpoints, keys refs
│   ├── festivals.json
│   └── model.yaml               # hyperparameters, horizons, quantiles
│
├── backend/
│   ├── pyproject.toml
│   ├── alembic/                 # migrations
│   ├── app/
│   │   ├── main.py              # FastAPI entry
│   │   ├── deps.py
│   │   ├── routers/
│   │   │   ├── forecast.py
│   │   │   ├── recommend.py
│   │   │   ├── mandis.py
│   │   │   ├── sale_reports.py
│   │   │   ├── transparency.py
│   │   │   └── whatsapp.py      # webhook
│   │   ├── models/              # SQLAlchemy ORM
│   │   ├── schemas/             # Pydantic
│   │   └── services/
│   ├── ingestion/
│   │   ├── connectors/
│   │   │   ├── agmarknet.py
│   │   │   ├── weather.py
│   │   │   ├── shocks.py
│   │   │   └── routing.py       # OSRM distance, cached
│   │   ├── cleaners.py
│   │   ├── entity_resolution.py
│   │   ├── validators.py
│   │   └── scheduler.py
│   ├── features/
│   │   ├── builder.py           # THE shared train/serve function
│   │   ├── registry.py          # feature name list, single source of truth
│   │   └── cache.py
│   ├── models_ml/
│   │   ├── baselines.py
│   │   ├── train.py
│   │   ├── predict.py
│   │   ├── explain.py           # SHAP → sentence
│   │   └── registry.py
│   ├── economics/
│   │   ├── net_realisation.py
│   │   ├── spoilage.py
│   │   └── msp.py
│   ├── decision/
│   │   ├── engine.py
│   │   ├── constraints.py
│   │   └── confidence.py
│   ├── transparency/
│   │   └── scoring.py
│   ├── bot/
│   │   ├── intents.py
│   │   ├── state_machine.py
│   │   ├── renderer.py
│   │   ├── asr.py               # voice note → text
│   │   └── locales/{mr,hi,en}.yaml
│   └── backtest/
│       ├── scenarios.py
│       ├── runner.py
│       └── report.py            # generates the ablation table
│
├── frontend/                    # Next.js dashboard
│   ├── app/
│   ├── components/
│   └── lib/api.ts
│
├── notebooks/
│   ├── 01_data_audit.ipynb      # do this FIRST
│   ├── 02_baselines.ipynb
│   ├── 03_feature_analysis.ipynb
│   └── 04_backtest_results.ipynb
│
└── scripts/
    ├── backfill_history.py
    ├── seed_demo_data.py
    └── train_and_promote.py
```

---

## 20. Configuration files

### `config/crops.yaml`

```yaml
onion:
  commodity_ids: [27]
  perishability_class: 3
  k_c: 0.006
  shelf_life_days: 90
  storable: true
  msp_applicable: false
  grade_factors: {A: 1.10, B: 1.00, C: 0.86}
  season:
    kharif:  {sow: "06-15", harvest_start: "10-01", harvest_end: "12-15"}
    rabi:    {sow: "11-01", harvest_start: "03-01", harvest_end: "05-15"}

tomato:
  commodity_ids: [78]
  perishability_class: 1
  k_c: 0.030
  shelf_life_days: 12
  storable: false
  msp_applicable: false
  grade_factors: {A: 1.12, B: 1.00, C: 0.82}
  max_hold_days: 5          # hard cap regardless of forecast

soybean:
  commodity_ids: [156]
  perishability_class: 5
  k_c: 0.0005
  shelf_life_days: 365
  storable: true
  msp_applicable: true
  grade_factors: {A: 1.05, B: 1.00, C: 0.92}
```

### `.env.example`

```
DATABASE_URL=postgresql+asyncpg://bhav:bhav@postgres:5432/bhav
REDIS_URL=redis://redis:6379/0

DATA_GOV_IN_API_KEY=
AGMARKNET_RESOURCE_ID=

WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_VERIFY_TOKEN=
WHATSAPP_APP_SECRET=

OSRM_BASE_URL=http://osrm:5000
OPEN_METEO_BASE=https://api.open-meteo.com/v1

MODEL_ARTIFACT_DIR=/data/models
ACTIVE_MODEL_VERSION=
```

---

## 21. Local setup

```bash
git clone <repo> && cd bhav-setu
cp .env.example .env        # fill in your data.gov.in key

docker compose up -d postgres redis
make migrate

# 1. Backfill history (this is the slow one — start it first)
python scripts/backfill_history.py --crops onion,tomato,soybean \
    --state Maharashtra --from 2022-01-01

# 2. Sanity-check the data BEFORE modelling
jupyter lab notebooks/01_data_audit.ipynb

# 3. Baselines
python -m models_ml.baselines --report

# 4. Train
python scripts/train_and_promote.py --horizons 1,3,7,15

# 5. Backtest — this produces your headline number
python -m backtest.runner --test-from 2025-01-01 --report

# 6. Serve
docker compose up -d api worker frontend
```

### `docker-compose.yml` (sketch)

```yaml
services:
  postgres:
    image: postgres:15
    environment: {POSTGRES_USER: bhav, POSTGRES_PASSWORD: bhav, POSTGRES_DB: bhav}
    volumes: ["pgdata:/var/lib/postgresql/data"]
    ports: ["5432:5432"]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  api:
    build: ./backend
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000
    env_file: .env
    depends_on: [postgres, redis]
    ports: ["8000:8000"]
    volumes: ["modeldata:/data/models"]

  worker:
    build: ./backend
    command: python -m ingestion.scheduler
    env_file: .env
    depends_on: [postgres, redis]
    volumes: ["modeldata:/data/models"]

  frontend:
    build: ./frontend
    ports: ["3000:3000"]
    environment: {NEXT_PUBLIC_API_URL: "http://localhost:8000"}

volumes: {pgdata: {}, modeldata: {}}
```

---

## 22. Build order for the hackathon

**Scope discipline is the whole game. 3 crops, 5 mandis, 1 district, 1 language.** Depth beats breadth, every time.

| Hours | Deliverable | Definition of done |
|---|---|---|
| 0–4 | **Data spine** | 3 years of history for 3 crops × 5 mandis in Postgres, cleaned, audited. A notebook chart of each series. |
| 4–8 | **Baselines + first model** | Baseline MAPE table printed. LightGBM P50 beating naive on h=7. |
| 8–12 | **Quantiles + walk-forward** | P10/P50/P90 for 4 horizons, PICP ≈ 0.8, walk-forward validated. |
| 12–18 | **⭐ Net In-Hand Engine** | The gross-vs-net table flips for at least one real case. Cost config in YAML. |
| 18–24 | **⭐ Decision engine + ₹-uplift backtest** | A single number: "+X.X% vs selling immediately." This is your pitch. |
| 24–30 | **WhatsApp bot** | Four flows working end to end on a real phone. Marathi. |
| 30–34 | **⭐ Ground-truth loop** | Sale report accepted, transparency score computed and displayed. |
| 34–38 | **Shock radar + explanations** | 20 curated events loaded; every recommendation carries a one-sentence reason. |
| 38–44 | **Dashboard** | Map, fan chart, net comparison, accuracy page. |
| 44–48 | **Demo + rehearsal** | Seeded data, script written, run 5 times, offline fallback video recorded. |

**Cut list, in order:** glut warning → photo grading → IVR → truck pooling → dashboard polish.
**Never cut:** Net In-Hand Engine, ₹-uplift backtest, the WhatsApp flow, the ground-truth loop.

### Critical demo insurance
Record a screen capture of the working WhatsApp flow the night before. Venue wifi fails, Meta rate-limits, phones die. A team that keeps presenting when the demo breaks beats a team that panics.

---

## 23. Team split

For three people:

| Person | Owns | Must ship |
|---|---|---|
| **A — Data & ML** | ingestion, cleaning, features, models, backtest | the ₹-uplift number |
| **B — Economics & Backend** | net realisation, decision engine, FastAPI, transparency scoring | the net-vs-gross flip |
| **C — Delivery & Story** | WhatsApp bot, dashboard, locales, demo script, slides | a working phone demo |

**Interfaces frozen at hour 2** so nobody blocks:
- A → B: `forecasts` table + `predict(mandi, commodity, horizon) → (p10, p50, p90)`
- B → C: the `/api/v1/recommend` JSON contract from §16

Write those two contracts down before anyone writes code. Mock them immediately so C can build against fake data while A is still backfilling.

---

## 24. Risks, limitations and ethics

Say these out loud in the pitch. Teams that name their own weaknesses are trusted more than teams that pretend not to have any.

### Technical risks

| Risk | Mitigation |
|---|---|
| Government data gaps and delays | Explicit imputation flags fed to the model; `days_since_observation` feature; graceful "not enough recent data for this mandi" response |
| API rate limits / resource ID changes | Own API key, resource IDs in config, local backfill so the demo never depends on a live call |
| Model is genuinely bad for perishables | Report it honestly per crop; hard-cap hold days for class-1 crops; recommend selling sooner rather than pretending |
| Thin mandis are noisy | `mandi_liquidity` feature, wider bands, lower confidence, sometimes just say "we can't advise on this mandi yet" |
| Overfitting to a 3-crop 5-mandi slice | Walk-forward validation, hold out the last 6 months completely, report worst-case not just mean |

### Product and adoption risks

| Risk | Mitigation |
|---|---|
| Farmers won't type | Voice notes + IVR fallback |
| Trust — why believe an app over the trader they've known 20 years? | Publish our own accuracy; go through FPOs, which already have trust; start with small-stakes advice |
| Cold start on the feedback loop | One FPO, one district, one crop; seed transparently |
| Advice that loses money | Risk-averse objective, confidence floors, split recommendations so the farmer is never fully exposed to one forecast |

### Ethical considerations

1. **Never be a single point of failure.** Always present the recommendation as *advice with a stated confidence and a stated downside*, never as a guarantee. Include the P10 case in the message when it is materially bad.
2. **Do not create the next glut.** Sowing advice must recommend diversification across options, never a single substitute crop, or you cause the very cycle you are trying to prevent.
3. **Transparency scores are about mandis, not people.** Aggregate only. Never name an individual commission agent. This is both fairer and legally safer.
4. **Consent and data ownership.** Explicit opt-in for storing location and sale data. A farmer can request deletion. Under India's DPDP framework, sale price and location are personal data — treat them as such: purpose limitation, retention limits, and an erasure path.
5. **Don't widen the digital divide.** The IVR/missed-call path is not a nice-to-have; without it the product serves only farmers who were already better off.
6. **Be honest that we cannot fix structural problems.** We reduce information asymmetry. We do not fix APMC monopoly, credit-bondage to commission agents, or the lack of storage infrastructure. Claiming otherwise is dishonest and a judge will catch it.

---

## 25. Glossary

| Term | Meaning |
|---|---|
| **APMC** | Agricultural Produce Market Committee — the state body that regulates a mandi |
| **Agmarknet** | Government portal publishing daily mandi prices and arrivals, run by DMI under the Ministry of Agriculture |
| **Arrivals** | Quantity of a commodity brought into a mandi on a day. Leading indicator of price. |
| **Arhatiya / commission agent** | Intermediary in the mandi who handles the farmer's sale and takes a commission |
| **Cess** | A statutory levy on the transaction value in a regulated market |
| **eNAM** | National Agriculture Market — pan-India electronic trading portal linking APMC mandis |
| **Farmgate price** | What the farmer actually receives, after all deductions. Not the same as the mandi price. |
| **FPO** | Farmer Producer Organisation — a collective of farmers; the best distribution channel for this product |
| **Hamali** | Loading/unloading labour charge |
| **Mandi** | A regulated wholesale agricultural market |
| **Modal price** | The most frequently occurring transaction price for a commodity in a mandi on a day |
| **MSP** | Minimum Support Price, set on CACP recommendations; a floor the government commits to for certain crops |
| **Quintal (qtl)** | 100 kg. The standard trading unit in Indian mandis. |
| **PICP** | Prediction Interval Coverage Probability — share of actuals falling inside the predicted band |
| **Pinball loss** | The correct loss function for quantile forecasts |
| **NDVI** | Normalized Difference Vegetation Index — satellite-derived greenness, used for acreage and yield estimation |
| **Cobweb cycle** | The recurring pattern where high prices trigger over-planting, causing a crash next season |

---

## Appendix A — The 90-second pitch

> Ramesh in Nashik has 80 quintals of onion. A trader offers ₹1,650.
>
> He sends a voice note to our WhatsApp number. Three seconds later, in Marathi:
> *"Don't sell everything. Sell 50 quintals at Lasalgaon today — after transport and commission you'll net ₹1,842 per quintal. Hold 30 for nine days, arrivals are down 22% and Diwali demand starts in eleven days. Expected extra: ₹14,230. Confidence 71%."*
>
> Every other app would have shown him a number: ₹2,010 at Lasalgaon. That number is wrong for him — it's before transport, before 3% commission, before hamali. We compute what actually reaches his pocket, and we rank mandis by that. Sometimes the mandi with the highest price is the worst choice, and only we can see it.
>
> We backtested this on real 2024–25 mandi data: following our advice beat selling immediately by 8.4%, with a 64% win rate.
>
> And after he sells, we ask him one question — *what did you actually get?* That answer trains our model, and it builds something nobody has: a map of which mandis pay farmers fairly and which don't. Every sale makes the system smarter. That is a moat that widens on its own.

---

## Appendix B — Answers to the questions judges will ask

| Question | Answer |
|---|---|
| *How is this different from Agmarknet or eNAM?* | They report what happened. We tell you what to do, and we compute your net, not the mandi's gross. |
| *How accurate is it?* | h=1 around 4% error, h=7 around 8–9%, worse for tomato, and our 80% bands cover 80% of outcomes. We publish this in the app. We would rather be honestly uncertain than confidently wrong. |
| *What if you're wrong and he loses money?* | We never give one number. We give a range, a confidence, and a split so he's never fully exposed. When confidence drops below 50% we tell him to sell now. |
| *Will a farmer really use this?* | No app, no typing, no literacy needed — a voice note on WhatsApp, and a missed-call IVR for feature phones. Distribution through FPOs, which already have his trust. |
| *Where does the actual-price data come from at the start?* | One FPO, one district, one crop, 200 farmers. Density beats coverage. We seed the demo transparently. |
| *Does this scale to all of India?* | One global model with mandi and commodity embeddings. Adding a mandi is adding a row, not training a new model. |
| *What's your business model?* | Free for farmers, forever. Revenue from FPO/agri-business subscriptions to the aggregate market intelligence, and from the transparency dataset for policy research. The farmer is never the product. |
| *What can't you do?* | We reduce information asymmetry. We cannot fix APMC monopoly, debt bondage to commission agents, or missing cold storage. Being clear about that is part of being trustworthy. |
