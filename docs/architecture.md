# Architecture

Bhav Setu turns raw mandi prices into one sentence a farmer can act on: how much to
sell today, where, and how much to hold. This page shows how the pieces fit.

The system is four layers with one rule between them — **every number a farmer sees
has been through the economics engine**. Nothing quotes a board price directly.

---

## 1. System architecture

```mermaid
graph TB
    subgraph sources["EXTERNAL SOURCES"]
        AGMARK["Agmarknet / data.gov.in<br/><i>daily price + arrivals</i>"]
        CEDA["CEDA, Ashoka University<br/><i>3-year history</i>"]
        METEO["Open-Meteo<br/><i>weather, no API key</i>"]
        OSRM["OSRM<br/><i>road distance</i>"]
        SHOCK["Curated policy events<br/><i>export bans, MEP orders</i>"]
    end

    subgraph ingest["INGESTION — backend/ingestion/"]
        FETCH["ceda.py · agmarknet.py<br/>backfill_csv.py · weather.py"]
        RESOLVE["entity_resolution.py<br/><i>RapidFuzz: 'Lasalgaon(Vinchur)' → Lasalgaon</i>"]
        CLEAN["cleaners.py<br/><i>reject impossible, flag suspect,<br/>impute gaps ≤ 3 days</i>"]
        AUDIT["audit.py<br/><i>honest data quality report</i>"]
    end

    subgraph store["STORAGE"]
        PG[("PostgreSQL 15<br/><i>price_observations, weather,<br/>shocks, lots, sale_reports</i>")]
        REDIS[("Redis 7<br/><i>bot session state</i>")]
    end

    subgraph brain["DECISION LAYERS — the product"]
        FEAT["features/builder.py<br/><b>ONE function</b><br/><i>~40 signals, point-in-time correct</i>"]
        MODEL["ml/train.py · predict.py<br/><i>LightGBM quantile ×12</i><br/><i>P10/P50/P90 at 1/3/7/15 days</i>"]
        ECON["economics/net_realisation.py<br/><i>commission, cess, hamali,<br/>transport, spoilage, interest</i>"]
        DECIDE["decision/engine.py<br/><i>grid search, mean-minus-risk,<br/>6 hard override rules</i>"]
    end

    subgraph serve["DELIVERY"]
        API["FastAPI<br/><i>/forecast /recommend /compare</i>"]
        BOT["bot/engine.py<br/><b>pure function</b><br/>(session, text) → reply"]
    end

    subgraph clients["WHAT THE FARMER TOUCHES"]
        WEB["Next.js website<br/><i>Dashboard · Advisor · Compare<br/>Community · History</i>"]
        WA["WhatsApp Cloud API<br/><i>Marathi + English</i>"]
        SIM["/chat simulator<br/><i>same engine, no Meta dependency</i>"]
    end

    AGMARK --> FETCH
    CEDA --> FETCH
    METEO --> FETCH
    OSRM --> FETCH
    SHOCK --> FETCH

    FETCH --> RESOLVE --> CLEAN --> PG
    CLEAN --> AUDIT

    PG --> FEAT
    FEAT --> MODEL
    MODEL --> ECON
    ECON --> DECIDE

    DECIDE --> API
    DECIDE --> BOT
    REDIS <--> BOT

    API --> WEB
    BOT --> WA
    BOT --> SIM

    WA -.->|"what price did<br/>you actually get?"| PG
    WEB -.->|sale reports| PG

    classDef ext fill:#EDEDE1,stroke:#C3C3B4,color:#16160F
    classDef core fill:#1F3D2B,stroke:#1F3D2B,color:#F3F3EA
    classDef data fill:#FFFFFF,stroke:#16160F,color:#16160F
    classDef client fill:#16160F,stroke:#16160F,color:#F3F3EA

    class AGMARK,CEDA,METEO,OSRM,SHOCK ext
    class FEAT,MODEL,ECON,DECIDE core
    class PG,REDIS data
    class WEB,WA,SIM client
```

---

## 2. Why it is shaped this way

**One feature function, not two.** `build_features()` is called by training, by
backtesting and by the live API. Most projects write a notebook version and a
serving version, they drift apart, and the live system quietly performs far worse
than the notebook claimed. A point-in-time assertion inside the function raises if
any row newer than the as-of date reaches the feature window.

**Economics sits between the model and the farmer.** A forecast of ₹2,010 at
Lasalgaon is not an answer. After 3% commission, 1.05% cess, hamali, the diesel for
62 km and whatever rots in a week, the farmer sees something closer to ₹1,842. The
striking consequence is that **the market with the highest price is often not the
best market**, and that flip is what the Compare page exists to show.

**The bot is a pure function.** `(session, text) → reply` has no knowledge of
WhatsApp. The webhook and the `/chat` web simulator both call it, so if Meta
approval or the tunnel fails on demo day, the story is unchanged.

**Sale reports flow backwards.** Anyone can scrape a price board. Only a system
farmers talk to learns what they were *actually paid* — and that gap, per mandi,
is the transparency score no competitor has.

---

## 3. Repository layout

```
bhav-setu/
├── config/          every tunable number — fees, mandis, crops, risk lambdas
│   ├── mandis.yaml         the 5 Nashik mandis
│   ├── crops.yaml          perishability, spoilage constant, max hold days
│   ├── cost_model.yaml     commission, cess, hamali, transport, interest
│   └── decision.yaml       risk lambdas, constraint thresholds
│
├── db/schema.sql    19 tables, single file, no migrations
│
├── backend/
│   ├── core/        config loader, DB engine, structured logging, typed errors
│   ├── ingestion/   fetch → resolve → clean → audit
│   ├── features/    registry.py (the ordered list) + builder.py (the function)
│   ├── ml/          baselines, training, prediction, SHAP explanations
│   ├── economics/   spoilage + net realisation
│   ├── decision/    engine, constraints, confidence
│   ├── bot/         engine, intents, session, mr/en locales
│   └── api/         FastAPI routers
│
├── frontend/
│   ├── app/         Dashboard · Advisor · Compare · Community · History · Chat
│   ├── components/  ForecastChart, NetComparisonTable, CostWaterfall, ChatWindow
│   └── lib/         api.ts is the single seam to the backend
│
└── scripts/         init_db · backfill · train · backtest · seed_demo_data
```

**Everything tunable lives in `config/`.** Fee percentages, which mandis are
covered, how many days ahead we forecast, how risk-averse the optimiser is — all
YAML, none of it buried in Python. Adding a crop is a config edit, not a code
change.

---

## 4. Request path for one recommendation

```mermaid
sequenceDiagram
    participant F as Farmer
    participant W as Website / WhatsApp
    participant A as FastAPI
    participant B as build_features()
    participant M as LightGBM
    participant E as Net In-Hand
    participant D as Decision engine

    F->>W: 80 qtl onion, grade B, shed
    W->>A: POST /recommend
    A->>B: as_of, mandi, commodity
    B-->>A: ~40 features (point-in-time)
    A->>M: predict quantiles
    M-->>A: P10 / P50 / P90 × 1,3,7,15 days
    A->>E: price × qty × distance × days
    E-->>A: net ₹/qtl per mandi, per horizon
    A->>D: forecasts + economics + risk profile
    D->>D: score candidate plans<br/>apply 6 hard constraints
    D-->>A: sell 40 today, hold 40 for 15 days
    A-->>W: plan + reason + confidence + ₹ gain
    W-->>F: one sentence he can act on
    F-->>W: (later) "I got ₹1,840"
    W->>A: POST /sale-reports → transparency score
```

---

## 5. Current build status

| Layer | State |
|---|---|
| Config + schema + seeds | Working, tested |
| Ingestion pipeline | Written and running; data volume is the open problem |
| Feature builder | Written; needs denser history to validate |
| Model, economics, decision | Specified; mirrored in TypeScript for the web demo |
| Website | Complete — 16 routes, 51 logic tests, 36 route tests |
| WhatsApp | Deep link live; webhook pending Meta approval |

The website currently runs on a seeded data layer that mirrors the Python
contracts exactly. `frontend/lib/api.ts` is the single seam — each function
becomes a `fetch` when the API lands, and no component changes.
