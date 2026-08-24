# PLAN-FINAL.md — Bhav Setu, Final Round

> Round 1 is done and we're through. This document replaces [PLAN.md](PLAN.md) as the
> working plan. PLAN.md stays for reference — it describes the onion-only prototype.
>
> **Target:** a genuinely working product — real market data, a real trained forecasting
> model, a real backend, and a WhatsApp agent that talks to farmers in Marathi.
> The website UI stays exactly as it is today.

---

## Part A — What we have built so far

Honest inventory. Green means tested and working; amber means written but unproven.

| Layer | State | Evidence |
|---|---|---|
| **Config + Docker** | ✅ Working | 6/6 tests. Postgres 5433, Redis 6380, 7 YAML config files |
| **Database schema** | ✅ Working | 14/14 tests. 19 tables, seeds 5 mandis + crops + 45 festivals |
| **Ingestion pipeline** | 🟡 Code done, data thin | 24/25 tests. Fetch → clean → fuzzy-match → audit all run; only ~45 rows per mandi loaded |
| **Feature builder** | 🟡 Code done, unproven | 19/26 tests. Fails on `InsufficientData` — needs denser history, not a code fix |
| **Forecasting model** | ❌ Not started | — |
| **Economics engine** | ⚠️ TypeScript only | Runs in the browser; no Python version |
| **Decision engine** | ⚠️ TypeScript only | Runs in the browser; no Python version |
| **Backtest** | ❌ Not started | — |
| **API** | ❌ Not started | — |
| **Website** | ✅ Complete | 16 routes, 51 logic tests, 36 route tests, clean build |
| **WhatsApp** | ❌ Deep link only | No webhook, no bot |

**What this means in plain words.** The website is finished and looks like a real product,
but underneath it is running on invented numbers generated in the browser. The database and
the data-cleaning machinery are real and tested. The brain — the part that learns from
history and decides — exists only as a browser-side imitation. The final round is about
replacing that imitation with the real thing.

**Two things we learned the hard way, which shape this plan:**

1. **Data acquisition is the hardest part, not the modelling.** We burned two attempts —
   a Kaggle dataset with no onion and no Maharashtra, then a CEDA portal that capped
   exports at 1000 rows and then rate-limited us. Phase 1 below treats data as a
   first-class engineering problem with fallbacks, not a download step.
2. **A demo that looks right can still be wrong.** Our own test suite passed 47/47 while
   every crop silently returned "sell now" and a split recommendation was mathematically
   impossible. Every phase below has an anti-vacuity check: a test that fails if the
   component is doing nothing.

---

## Part B — What the finished product must do

| Requirement | Target |
|---|---|
| **Prediction** | LightGBM quantile model trained on real mandi history. P10/P50/P90 at 1/3/7/15 days. Must beat naive, seasonal, MA-7 and drift baselines |
| **Coverage** | 3–4 districts, every vegetable and fruit the data actually supports |
| **Backend** | FastAPI serving every page from Postgres — no mock data anywhere |
| **WhatsApp** | An LLM agent (Claude) that understands free Marathi/Hindi/English and answers using real tool calls |
| **UI** | Unchanged. Same pages, same design, same routes |

**One honest caveat about "all vegetables and fruits."** We cannot promise 16 crops before
seeing the data — that is exactly the mistake that cost us two attempts. Phase 1 ends by
*measuring* which crops have enough history per district, and Phase 2 configures the crop
list from that measurement. Expect 8–14 crops to survive; the rest get shown as
"price only, no forecast" rather than being faked.

---

# The Phases

Thirteen phases. Each has: what it is, what we build, what it means in simple words, how to
test it, and when it's done. Work them in order — each depends on the one before.

---

## Phase 1 — Get real data, reliably

**Goal:** 2–3 years of daily prices and arrivals for 3–4 districts × as many crops as
exist, in the database, from a source that will still work on demo day.

### What we build

| File | Purpose |
|---|---|
| `backend/ingestion/datagov.py` | data.gov.in Agmarknet API — daily pull, accumulates forward |
| `backend/ingestion/ceda.py` | already written — add polite pacing, resume from disk cache |
| `backend/ingestion/bulk_csv.py` | generalise `backfill_csv.py` for any bulk dump |
| `scripts/collect_daily.py` | cron-able daily collector, logs to `ingestion_runs` |
| `scripts/inspect_dataset.py` | already written — the gate before anything is imported |
| `config/sources.yaml` | source priority, retry, chunking, cache paths |

**Three sources, in priority order.** data.gov.in for the daily forward feed (needs your
free API key — this is the one that keeps working every day). CEDA for the historical
backbone, fetched slowly with disk caching so a throttle costs us nothing. A bulk CSV as
the fallback if both fail.

### In simple words

> This is the water supply. Everything else in the project is a tap, and a tap with no water
> behind it is decoration. Last time we tried to fill the tank twice and both times the
> hose was the wrong shape — once the file had no onion in it, once the website only gave
> us a thousand rows and then stopped answering. So this time we build three hoses instead
> of one, we save every bucket we manage to fill so a failure never costs us what we already
> had, and we check what is actually in the tank before we start plumbing.

### How to test it

1. Run `python scripts/collect_daily.py --once` — it should print how many rows it fetched
2. Run `python scripts/inspect_dataset.py` on whatever landed — read the verdict
3. In psql: `SELECT district, count(*) FROM price_observations p JOIN mandis m ON ... GROUP BY district;`
4. Kill it halfway and re-run — it should resume, not restart from zero

### Done when

- ≥ 3 districts each have ≥ 500 daily rows for at least one crop
- ≥ 8 crops have ≥ 300 rows in at least one district
- Re-running the collector adds no duplicates (the UNIQUE key does its job)
- `data/artifacts/data_audit.md` marks ≥ 3 districts USABLE

**Time:** 2–4 days, most of it waiting on rate limits. Start this first, today.

---

## Phase 2 — Multi-crop database and cleaning

**Goal:** the schema, config and cleaning rules handle many crops across several districts,
not one crop in one belt.

### What we build

| File | Purpose |
|---|---|
| `config/crops.yaml` | one block per crop — aliases, `k_c`, shelf life, max hold days, seasons |
| `config/mandis.yaml` | the 3–4 districts and their mandis, with coordinates |
| `db/schema.sql` | add `crop_coverage` view; index on `(commodity_id, mandi_id, obs_date)` |
| `scripts/init_db.py` | seed every crop and alias from config |
| `backend/ingestion/audit.py` | audit per (district × crop), not just per mandi |

**The crop list comes from Phase 1's measurement,** and each crop needs real perishability
numbers — `k_c` and max hold days drive the spoilage maths, and a wrong value there produces
confident nonsense.

### In simple words

> Round 1 knew about exactly one crop. Now the filing cabinet needs a drawer for every
> vegetable and fruit, and each drawer needs to know how fast that thing rots — because
> tomato and potato are completely different businesses. A tomato left for a week is
> rubbish; a potato is fine. If we get those numbers wrong the advice looks confident and
> is wrong, which is worse than no advice.

### How to test it

1. `python scripts/init_db.py --force` then `SELECT name FROM commodities;` — every crop listed
2. `pytest tests/test_phase2_ingestion.py` — all green now that data is dense
3. Open `data/artifacts/data_audit.md` — a table per district, verdict per crop
4. Spot-check one crop by hand: does its price range look sane for that vegetable?

### Done when

- Every crop in `crops.yaml` is seeded with ≥ 3 aliases
- Audit shows per-crop coverage for every district
- All 25 Phase 2 tests pass
- No crop has `max_hold_days > shelf_life_days`

**Time:** 1–2 days.

---

## Phase 3 — Prove the feature builder

**Goal:** `build_features()` runs for every (crop, mandi, date) with no leakage, and the
training matrix is big enough to learn from.

### What we build

| File | Purpose |
|---|---|
| `backend/features/builder.py` | exists — make arrivals optional, add crop features |
| `backend/features/registry.py` | the ordered feature list, single source of truth |
| `backend/ml/dataset.py` | build and cache `train_matrix.parquet` |

**One change needed:** feature group B (arrivals) must degrade cleanly when a crop has no
arrival data, instead of producing NaNs the model silently learns from.

### In simple words

> Raw prices tell a model almost nothing. "Yesterday it was ₹1,860" is not a signal.
> "Arrivals are 22% below the monthly average, the neighbouring market is 4% higher, Diwali
> is 11 days away, and an export ban was announced six days ago" — that is a picture, and
> this is the code that paints it. The critical rule is that the picture painted for a
> Tuesday may only use information that existed on that Tuesday. Break that rule and your
> model looks brilliant in testing and useless in real life.

### How to test it

1. `pytest tests/test_phase3_features.py` — all 26 green
2. The leakage test specifically: insert a fake future price, rebuild, confirm the numbers don't move
3. `python -c "import pandas; print(pandas.read_parquet('data/artifacts/train_matrix.parquet').shape)"`
4. Check no column is all-NaN for any crop

### Done when

- All 26 Phase 3 tests pass
- Training matrix ≥ 20,000 rows across all crops
- Zero infinite values, no all-NaN columns
- Leakage test passes for every crop

**Time:** 2–3 days.

---

## Phase 4 — Train the forecasting model

**Goal:** a trained multi-crop quantile model that provably beats four dumb baselines.

### What we build

| File | Purpose |
|---|---|
| `backend/ml/baselines.py` | naive, seasonal-naive, drift, MA-7 — **build these first** |
| `backend/ml/train.py` | LightGBM quantile × 12 (3 quantiles × 4 horizons) |
| `backend/ml/predict.py` | `predict_quantiles()` — sorts p10/p50/p90 before returning |
| `backend/ml/explain.py` | SHAP → the one-line reason a farmer reads |
| `backend/ml/registry.py` | model versions, metrics, promote-if-better |
| `scripts/train.py` | CLI entry point |

**One global model, not one per crop.** `commodity_id` and `mandi_id` are features. This is
what lets a crop with thin data borrow strength from crops with thick data.

**Walk-forward validation with a purge gap** of `h` days between train and validation —
otherwise a 15-day label leaks backwards into training.

### In simple words

> This is the part people picture when they hear "AI", and it's also the part where projects
> quietly cheat. Two rules keep us honest. First, before training anything clever we build
> four stupid predictors — "tomorrow will be the same as today" and friends. If the fancy
> model can't beat "same as today", we need to know immediately, not on stage. Second, we
> never predict one number. We predict a low case, a likely case and a high case, because
> nobody can predict onion to the rupee and pretending otherwise is how you give a farmer
> with a loan advice that ruins him.

### How to test it

1. `python scripts/train.py --from 2023-01-01 --promote` and read the printed table
2. Check LightGBM beats naive on pinball loss at every horizon — if not, stop and fix
3. Check PICP (band coverage) is between 0.72 and 0.88 — that means the range is honest
4. `pytest tests/test_phase4_model.py` — 100 random cases must return p10 ≤ p50 ≤ p90
5. Screenshot the metrics table — it goes in the deck

### Done when

- 12 model files saved, one version marked active
- LightGBM beats naive pinball loss at **all four** horizons
- 0.72 ≤ PICP ≤ 0.88
- Directional accuracy at 7 days > 0.60
- Sanity: h=1 MAPE under ~8%, h=7 under ~15% (multi-crop is harder than onion-only)

**Time:** 3–4 days. Budget re-runs — the first training round rarely beats the baselines.

---

## Phase 5 — Net In-Hand economics, in Python

**Goal:** port the TypeScript economics engine to Python, per-crop, as the single source
of truth.

### What we build

| File | Purpose |
|---|---|
| `backend/economics/spoilage.py` | `spoilage_fraction(k_c, days, storage, tmax)` |
| `backend/economics/net_realisation.py` | `net_in_hand()` → `NetResult` with full breakdown |
| `backend/economics/compare.py` | `compare_mandis()` → gross rank vs net rank |
| `config/cost_model.yaml` | fees, transport, storage, interest — **with sourced numbers** |

The formula is already written and tested in
[frontend/lib/mock/economics.ts](frontend/lib/mock/economics.ts) — port it exactly,
including `net_per_qtl` being divided by the **original** quantity so spoilage shows up as
a lower rate rather than hiding in the total.

### In simple words

> This is the heart of the whole product. Every other app shows a farmer the market price —
> say ₹2,010. But that number is a lie for him. Out of it comes 3% commission, 1% market
> cess, loading charges, the diesel to move 80 quintals 62 kilometres, and if he waits a
> week, some of it rots. What actually reaches his hand might be ₹1,842. We compute that.
> And the striking consequence is that **the market with the highest price is often not the
> best market for him** — a nearer market paying less can put more money in his pocket.

### How to test it

1. `pytest tests/test_phase5_economics.py`
2. Net is always below gross; net falls as distance grows; net falls as days held grows
3. Zero-day hold has exactly zero spoilage
4. **At least one case where ranking by gross and by net give different winners** — this is the demo moment, and the test guarantees you have it
5. Cross-check against the TypeScript: same inputs must give the same rupees

### Done when

- All economics tests pass, including the rank-flip case
- Python and TypeScript agree to the rupee on 20 sample lots
- Every `SOURCE: <fill in>` in `cost_model.yaml` is replaced with a real URL

**Time:** 1–2 days — the logic already exists and is tested.

---

## Phase 6 — Decision engine, in Python

**Goal:** turn forecasts + economics into one imperative sentence with a rupee figure.

### What we build

| File | Purpose |
|---|---|
| `backend/decision/engine.py` | grid search over sell-fraction × hold-days × mandi |
| `backend/decision/constraints.py` | the six hard rules that override the maths |
| `backend/decision/confidence.py` | band tightness + data quality + historical hit rate |

**Carry over the fix we found in Round 1.** The scoring must be *convex* in the sell
fraction:

```python
exposure = later_qty / lot.qty_qtl
score = e_net - risk_lambda * downside * exposure
```

A flat `e_net - λ × downside` is **linear**, so the best score always sits at a corner —
sell everything or hold everything — and the split recommendation the whole product is
built on becomes mathematically unreachable. We hit this exactly, and it passed 47 tests
before we caught it.

### In simple words

> Now the system stops describing and starts deciding. It tries hundreds of plans — sell
> everything now, sell half and wait a week, sell a quarter and wait two weeks, at each of
> several markets — works out the real rupees for each, and picks the best. But not simply
> the highest average: it deliberately penalises plans with a bad worst case, because a
> farmer with a loan cannot afford a gamble that occasionally goes badly. On top sit six
> hard rules that override the maths entirely — never tell someone to hold tomatoes for two
> weeks, never send five quintals ninety kilometres, and if the government just banned
> exports, sell today and don't argue.

### How to test it

1. `pytest tests/test_phase6_decision.py`
2. **Anti-vacuity:** at least one crop must return a genuine split (two tranches, both non-zero)
3. Perishable crops (tomato, okra, banana) must return sell-now
4. Storable crops (potato, garlic, onion) must sometimes hold or split
5. Tranche quantities sum to the lot quantity
6. Cautious never holds longer than aggressive on the same input
7. Every constraint has a test proving it fires

### Done when

- All decision tests pass **including the anti-vacuity ones**
- Expected gain ≥ 0 for the chosen plan in ≥ 90% of 200 random scenarios
- Python matches the TypeScript engine's decisions on 20 sample lots

**Time:** 2–3 days.

---

## Phase 7 — Backtest: the one number that matters

**Goal:** *"following our advice beats selling immediately by X%."*

### What we build

| File | Purpose |
|---|---|
| `backend/backtest/scenarios.py` | sample lots over a held-out period the model never saw |
| `backend/backtest/runner.py` | replay each scenario through the **live** decision engine |
| `backend/backtest/report.py` | the uplift number, win rate, per-crop breakdown |
| `scripts/backtest.py` | CLI |

**The runner must call the real `optimise()`,** not a special backtest path. If backtest and
production run different code, the backtest is fiction.

### In simple words

> This is the number that decides whether the judges believe us. We rewind to six months
> ago, pretend we know nothing after that date, ask our own system what to do with a
> thousand imaginary lots, then fast-forward and check what actually happened to those
> prices. If following our advice would have made farmers more money than just selling
> immediately, we have a product. If not, we have a science project, and we would rather
> find that out now than on stage.

### How to test it

1. `python scripts/backtest.py` and read `data/artifacts/backtest.md`
2. Check the held-out period genuinely postdates the training window
3. Look at the per-crop table — is the uplift coming from every crop or one lucky one?
4. Sanity: is the win rate plausible (55–70%)? 95% means a bug

### Done when

- Uplift is positive and you can explain where it comes from
- Win rate between 55% and 75%
- Per-crop breakdown produced
- The number goes in the deck and on the Accuracy page

**Time:** 2 days.

---

## Phase 8 — FastAPI backend

**Goal:** every page's data served from Postgres.

### What we build

| File | Endpoints |
|---|---|
| `backend/api/main.py` | app, CORS, error handlers |
| `backend/api/schemas.py` | Pydantic models matching `frontend/lib/types.ts` exactly |
| `routers/mandis.py` | `GET /mandis`, `GET /districts` |
| `routers/prices.py` | `GET /prices/today`, `GET /prices/series` |
| `routers/forecast.py` | `GET /forecast` |
| `routers/recommend.py` | `POST /recommend` |
| `routers/compare.py` | `GET /compare` |
| `routers/history.py` | `GET/POST /history` |
| `routers/community.py` | `GET/POST /pools` |
| `routers/accuracy.py` | `GET /accuracy` |
| `routers/sale_reports.py` | `POST /sale-reports` |
| `routers/chat.py` | `POST /chat` → bot engine |
| `routers/whatsapp.py` | `GET/POST /webhooks/whatsapp` |

**Match the response shapes to `frontend/lib/types.ts` exactly.** That file is already the
contract — if the API returns those shapes, Phase 9 is a one-file change.

### In simple words

> The website currently invents its numbers in the browser. This is the wire that connects
> it to the real machinery. Get the shapes right and the website won't notice the swap —
> it will just start telling the truth. We wrote the frontend with a single file that
> stands between it and the data precisely so this day would be easy.

### How to test it

1. `make api`, then open `http://localhost:8000/docs` — try every endpoint
2. `pytest tests/test_phase8_api.py`
3. Compare each response against the matching TypeScript type — field names identical?
4. Ask for a crop with no data — you should get a clear message, not a 500

### Done when

- Every endpoint returns 200 with correct shapes
- `InsufficientData` becomes a clean 422 with a readable message
- p95 response time under 500ms for cached forecasts

**Time:** 3–4 days.

---

## Phase 9 — Connect the website to the real backend

**Goal:** delete the mock layer. **Change nothing visual.**

### What we build

| File | Change |
|---|---|
| `frontend/lib/api.ts` | every function becomes a `fetch` — this is the only real change |
| `frontend/lib/mock/` | delete (keep `crops.ts` if it holds display metadata) |
| `frontend/.env.local` | `NEXT_PUBLIC_API_BASE_URL` |
| components | add loading and error states where they're missing |

### In simple words

> Everything the website shows becomes real in a single afternoon. We built it this way on
> purpose: every component asks one file for its data, and that file currently makes the
> data up. We change that file to ask the backend instead, and the same pages start showing
> real forecasts from a real model. Nobody watching can tell the difference — which is the
> point, because the design already works.

### How to test it

1. Backend running, then `npm run dev` — click every page
2. `bash .testbuild/route-tests.sh` — all 36 still pass
3. Stop the backend — pages should show a clear error, not a blank screen
4. Compare screenshots before and after — pixel-identical layout

### Done when

- No file under `frontend/lib/mock/` is imported by any page
- All 36 route tests pass against the live API
- Every page has a loading state and an error state
- The UI is visually unchanged

**Time:** 2 days.

---

## Phase 10 — Real accounts

**Goal:** replace demo auth with real OTP-over-WhatsApp login.

### What we build

| File | Purpose |
|---|---|
| `backend/auth/otp.py` | generate, store in Redis with TTL, verify, rate-limit |
| `backend/auth/session.py` | signed session tokens |
| `routers/auth.py` | `POST /auth/request-otp`, `POST /auth/verify` |
| `frontend/lib/auth.tsx` | swap localStorage for real session calls |

Rate-limit OTP requests per number. Never log the code.

### In simple words

> Right now anyone can type any number and get in — fine for a demo video, not for a real
> product. Now the code actually goes to the farmer's WhatsApp, expires in ten minutes, and
> can't be brute-forced. His lots, his history and his sale reports become genuinely his.

### How to test it

1. Request an OTP for your own number — it should arrive on WhatsApp
2. Wrong code → rejected. Expired code → rejected. Same code twice → rejected
3. Request 10 OTPs quickly → rate-limited
4. Log in, close the browser, reopen → still logged in

### Done when

- OTP arrives on a real phone
- Wrong/expired/reused codes all rejected
- Rate limiting works
- Sessions survive a restart

**Time:** 2 days.

---

## Phase 11 — The WhatsApp agent ⭐

**Goal:** a farmer types anything, in any of three languages, and gets a correct answer
built from real tool calls.

This is the headline feature of the final round. It uses **Claude with tool calling** — the
model handles language and intent; every number comes from our database.

### What we build

| File | Purpose |
|---|---|
| `backend/agent/tools.py` | the tool functions Claude may call |
| `backend/agent/agent.py` | the agent loop |
| `backend/agent/prompts.py` | system prompt (cached) |
| `backend/agent/session.py` | Redis conversation state per phone number |
| `backend/whatsapp/client.py` | send messages via Meta Cloud API |
| `backend/whatsapp/webhook.py` | receive + verify HMAC signature |
| `routers/whatsapp.py` | `GET` verification, `POST` inbound |

### The tools Claude gets

```python
from anthropic import beta_tool

@beta_tool
def get_price(crop: str, district: str) -> str:
    """Today's mandi price for a crop in a district, per quintal."""

@beta_tool
def get_forecast(crop: str, mandi: str, days: int) -> str:
    """Price forecast with a P10-P90 range for the next N days."""

@beta_tool
def get_recommendation(crop: str, qty_qtl: float, grade: str,
                       storage: str, risk: str) -> str:
    """Full sell/hold/split plan with net rupees and confidence."""

@beta_tool
def compare_mandis(crop: str, qty_qtl: float) -> str:
    """Net in hand at each mandi, ranked."""

@beta_tool
def find_transport_pool(mandi: str, date: str) -> str:
    """Farmers sharing a truck to that mandi, and the saving."""

@beta_tool
def record_sale(phone: str, crop: str, qty_qtl: float,
                price_received: float, mandi: str) -> str:
    """Record what the farmer actually got. Feeds transparency scores."""
```

### The agent loop

```python
import anthropic

client = anthropic.Anthropic()

runner = client.beta.messages.tool_runner(
    model="claude-opus-5",
    max_tokens=2048,
    system=[{
        "type": "text",
        "text": SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"},   # prompt caching
    }],
    thinking={"type": "adaptive"},
    output_config={"effort": "low"},              # latency matters on WhatsApp
    tools=[get_price, get_forecast, get_recommendation,
           compare_mandis, find_transport_pool, record_sale],
    messages=history + [{"role": "user", "content": incoming_text}],
)

for message in runner:
    if message.stop_reason == "refusal":
        reply = FALLBACK_REPLY[lang]
        break
```

Notes that matter: the SDK's tool runner drives the call → execute → loop cycle for us, so
we don't hand-write the loop. The system prompt is marked with `cache_control` so we don't
pay full price for it on every message. `effort: "low"` keeps replies fast — a farmer is
waiting. `stop_reason == "refusal"` must be checked before reading content, or the code
breaks on a refused message.

### The guardrail that matters most

> **Every number in a reply must come from a tool result. The model may translate,
> summarise and choose which tool to call — it may never invent a price, a forecast, or a
> rupee figure.** This goes in the system prompt in bold, and it is the single thing that
> separates a useful agent from a confident liar.

### In simple words

> Until now the bot followed a fixed script: crop, then grade, then storage, in that order,
> and anything unexpected confused it. Now a farmer can just write what he actually thinks —
> "कांदा ८० क्विंटल आहे, विकू का?" — and the system understands. The clever part is what the
> AI is *not* allowed to do. It is not allowed to know any prices. When it needs a number it
> has to ask our database, and it can only repeat what comes back. So we get the flexibility
> of a chatbot with the honesty of a calculator. This matters because a language model that
> guesses a price sounds exactly as confident as one that looked it up.

### How to test it

1. Start the tunnel (`cloudflared tunnel --url http://localhost:8000`), register the webhook in Meta
2. Send "hi" from a registered phone — you should get a Marathi greeting
3. Send "कांदा ८० क्विंटल" — it should call `get_recommendation` and reply with a real plan
4. Send something confusing — it should ask a clarifying question, not crash
5. **The honesty test:** ask about a crop with no data. It must say it doesn't know. If it invents a price, the guardrail has failed — fix the prompt before anything else
6. Check the logs: every number in every reply traces to a tool result
7. `pytest tests/test_phase11_agent.py`

### Done when

- Free-form Marathi, Hindi and English all work
- Every reply's numbers trace to a tool call in the logs
- Unknown crops produce an honest "I don't have data for that"
- Bad webhook signatures are rejected
- Median reply under 5 seconds
- The `/chat` page uses the same agent

**Time:** 4–5 days. The Meta approval and tunnel setup will eat a day on their own.

---

## Phase 12 — Community pooling, for real

**Goal:** transport pooling backed by the database.

### What we build

| File | Purpose |
|---|---|
| `db/schema.sql` | `transport_pools`, `pool_members` |
| `backend/community/pools.py` | create, join, leave, compute saving |
| `backend/community/matching.py` | suggest pools by mandi, date and proximity |
| `routers/community.py` | REST endpoints |

### In simple words

> Transport is the one cost a small farmer can actually control. At ₹42 a kilometre a
> 62 km trip costs ₹2,604 whether the truck is full or not — that's ₹260 a quintal on a
> ten-quintal lot, which is why the nearest mandi so often wins. Four farmers going the same
> morning split it four ways. Until now this page showed made-up neighbours; now it finds
> real ones going where you're going.

### How to test it

1. Create a pool as one user, join it as another, check the saving updates for both
2. Fill a truck to capacity — further joins must be refused
3. Leave a pool — costs recalculate for everyone remaining
4. Ask the WhatsApp agent about pooling — it should find the same pool

### Done when

- Pools persist and the maths matches the economics engine
- Capacity limits enforced
- The agent's `find_transport_pool` returns real pools

**Time:** 2 days.

---

## Phase 13 — Deploy, seed and harden

**Goal:** it runs somewhere other than your laptop, and survives demo day.

### What we build

| File | Purpose |
|---|---|
| `docker-compose.prod.yml` | api + worker + postgres + redis |
| `scripts/daily_job.py` | APScheduler — collect, retrain, precompute |
| `scripts/seed_demo_data.py` | demo farmer, lots, ~30 sale reports (`source='seed_demo'`) |
| `routers/admin.py` | `POST /reset-demo` |
| `docs/RUNBOOK.md` | what to do when something breaks on stage |

### In simple words

> Everything works on your machine. Demo day is a different country: someone else's wifi,
> a projector, a judge clicking things in an order you didn't plan for, and a WhatsApp token
> that expired overnight. This phase is about surviving that. It includes a reset button,
> because the fastest way to recover from a broken demo is to start it again cleanly.

### How to test it

1. Deploy, then run the full recording script end to end on the deployed version
2. Kill the API mid-demo and restart — does it come back cleanly?
3. Hit `/reset-demo` and confirm everything returns to its starting state
4. Test on phone data, not wifi
5. Regenerate the WhatsApp token and confirm the bot still works

### Done when

- Deployed and reachable over HTTPS
- Daily job runs on schedule
- Reset works
- Someone who isn't you can complete the demo from the runbook

**Time:** 2–3 days.

---

# Schedule

| Phase | Days | Can run in parallel with |
|---|---|---|
| 1 · Data | 2–4 | — (start immediately) |
| 2 · Multi-crop DB | 1–2 | — |
| 3 · Features | 2–3 | — |
| 4 · Model | 3–4 | 5 |
| 5 · Economics | 1–2 | 4 |
| 6 · Decision | 2–3 | — |
| 7 · Backtest | 2 | 8 |
| 8 · API | 3–4 | 7 |
| 9 · Frontend wiring | 2 | 10 |
| 10 · Auth | 2 | 9 |
| 11 · **WhatsApp agent** | 4–5 | 12 |
| 12 · Community | 2 | 11 |
| 13 · Deploy | 2–3 | — |

**Total: roughly 28–37 working days**, or 4–5 weeks with two people splitting the
model track (1→4) from the product track (5→12).

### Start these today, they have waiting time

- **data.gov.in API key** — free, but registration and email verification take a day
- **Anthropic API key** — for the WhatsApp agent
- **Meta WhatsApp Business** — app review is the longest pole in the whole plan
- **A cloud host** — Railway, Render or a small VPS

---

# The five things most likely to go wrong

Ranked by how much damage each does.

1. **Data never gets dense enough.** Already bit us twice. *Mitigation:* three sources,
   disk caching, and Phase 1 measures before Phase 2 commits. If a crop stays thin, show its
   price and say "not enough history to forecast" rather than faking it.
2. **The model doesn't beat the baselines.** *Mitigation:* baselines are built first, in
   Phase 4, so we find out on day one of training rather than after building everything on
   top. Usual causes: too little data, a broken feature, or the wrong target.
3. **The agent invents a price.** Fatal on stage — a judge will test it. *Mitigation:* the
   guardrail is in the system prompt, and Phase 11's honesty test is a release gate.
4. **Meta approval doesn't land in time.** *Mitigation:* the `/chat` page runs the same
   agent, so the story survives without WhatsApp. Apply now.
5. **We ship something that looks right and is wrong.** This is the one we actually
   experienced. *Mitigation:* every phase has an anti-vacuity test that fails if the
   component is doing nothing.

---

# What "done" means

- [ ] Real prices for 3–4 districts and every crop the data supports
- [ ] A trained model that beats all four baselines at all four horizons
- [ ] PICP between 0.72 and 0.88 — the ranges are honest
- [ ] A positive, explainable backtest uplift
- [ ] Every website page served from Postgres, zero mock imports
- [ ] The UI is visually identical to today
- [ ] A WhatsApp agent answering free-form Marathi with tool-grounded numbers
- [ ] Real OTP login
- [ ] Deployed, with a daily job and a reset button
- [ ] Someone else can run the demo from the runbook
