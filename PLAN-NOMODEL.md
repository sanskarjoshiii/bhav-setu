# PLAN-NOMODEL.md — Building the whole product while the model is a black box

> Companion to [PLAN-FINAL.md](PLAN-FINAL.md). Same destination, different order.
>
> **The assumption:** the forecasting model will arrive later, already trained and
> working. We do not train it, tune it, or wait for it. We build every other part of
> the product now, against a **stub that speaks the model's exact language**, and on
> swap day we change one line of config.
>
> Two tracks. **Track A** is everything buildable today — 14 phases, ~22–27 days.
> **Track B** is the four things that only become possible once the model exists —
> ~4–5 days. Track B is short *because* Track A was built against a fixed contract.

---

## The one idea this whole plan rests on

Everything downstream of the model touches it through exactly one function:

```python
# backend/ml/port.py
class Quantiles(NamedTuple):
    p10: float
    p50: float
    p90: float

class ForecastProvider(Protocol):
    def predict_quantiles(
        self,
        commodity_id: int,
        mandi_id: int,
        as_of: date,
        horizons: Sequence[int] = (1, 3, 7, 15),
    ) -> dict[int, Quantiles]: ...
```

The decision engine, the API, the website and the WhatsApp agent may **only** know
about `ForecastProvider`. None of them may import LightGBM, a booster file, or a
feature frame. If that rule holds, the model is a plug. If it leaks — even once, even
"just for the accuracy page" — swap day becomes a rewrite.

### In simple words

> We are building a car while the engine is still at the machine shop. That is only
> sane if we agree on the engine mounts first: four bolts, this far apart, this much
> torque. Then we build the chassis, the wheels, the seats, the dashboard and the
> steering, and we drop in a small borrowed engine so we can drive it around the yard
> and find out that the horn doesn't work. When the real engine arrives it bolts to the
> same four points. If instead we build the car around the borrowed engine, we will be
> cutting metal on the day the real one shows up.

**The borrowed engine is not wasted work.** Track A's stub is the four naive baselines
that [PLAN-FINAL.md](PLAN-FINAL.md) Phase 4 requires anyway as the benchmark the real
model must beat. We build them once and they serve twice: as the stub today, as the
release gate on swap day.

---

# TRACK A — Without the model

Fourteen phases. Work them in order; the parallel column says what can overlap.

---

## Phase A0 — The forecast port

**Goal:** freeze the contract between the model and everything else, before a single
consumer of it exists.

### What we build

| File | Purpose |
|---|---|
| `backend/ml/port.py` | `Quantiles`, `ForecastProvider` protocol, `InsufficientData` |
| `backend/ml/provider.py` | `get_provider()` — reads `config/model.yaml`, returns the active provider |
| `config/model.yaml` | add `provider: baseline` (later `lightgbm`), `horizons: [1,3,7,15]` |
| `backend/tests/test_phaseA0_port.py` | contract tests any provider must pass |

The contract tests are the important artifact. They assert, for **any** provider:
p10 ≤ p50 ≤ p90 always; all four horizons returned; an unknown crop raises
`InsufficientData` rather than returning zeros; the same inputs give the same output
twice. The real model will be run against this same file, unmodified, on swap day.

### How to test it

1. `pytest backend/tests/test_phaseA0_port.py`
2. `grep -rn "lightgbm\|booster" backend/api backend/decision backend/agent` — must be empty, now and forever

### Done when

- Contract tests exist and pass against a trivial dummy provider
- `get_provider()` switches implementation from config alone, with no code edit

**Time:** half a day. Do it first — it is what makes the other thirteen phases safe.

---

## Phase A1 — Data, serving grade

**Goal:** enough real data to *show* prices and *serve* forecasts. Not yet enough to
*train* on — that gate moves to Track B.

This is [PLAN-FINAL.md](PLAN-FINAL.md) Phase 1 with the volume requirement cut. The
distinction matters: training wants 2–3 years across many crops; serving wants today's
price, a 90-day chart, and enough lag history for the feature builder.

### What we build

| File | Purpose |
|---|---|
| `backend/ingestion/datagov.py` | data.gov.in Agmarknet API — the daily forward feed |
| `backend/ingestion/ceda.py` | exists — add polite pacing and resume-from-disk-cache |
| `scripts/collect_daily.py` | cron-able collector, logs to `ingestion_runs` |
| `scripts/inspect_dataset.py` | exists — the gate before anything is imported |
| `config/sources.yaml` | exists — fill in source priority, retry, cache paths |

### In simple words

> The full plan treats data as a reservoir you must fill before the turbine can spin.
> Without the model there is no turbine yet — but the taps still have to run, because a
> farmer opening the dashboard wants to see today's actual onion price whether or not
> anything is being forecast. So we fill the tank to drinking level now and to reservoir
> level later. The collector we write today is the same one that fills it later; it just
> runs for more days.

### How to test it

1. `python scripts/collect_daily.py --once` — prints rows fetched
2. `python scripts/inspect_dataset.py` — read the verdict
3. Kill it halfway, re-run — it resumes and adds no duplicates

### Done when

- ≥ 3 districts have a current price for ≥ 5 crops
- ≥ 90 days of history for at least one crop per district (enough to draw a chart)
- Re-running adds no duplicates
- The collector runs unattended for 3 consecutive days without intervention

**Time:** 1–2 days. Start day one — this accumulates while you build everything else,
and by swap day it will have quietly become the training set.

---

## Phase A2 — Multi-crop database and cleaning

**Goal:** schema, config and cleaning handle many crops across several districts.

Unchanged from [PLAN-FINAL.md](PLAN-FINAL.md) Phase 2. [config/crops.yaml](config/crops.yaml)
currently holds onion only; it needs a block per crop with real `k_c`, `shelf_life_days`
and `max_hold_days`, because those three numbers drive the spoilage maths in Phase A5
and a wrong value there produces confident nonsense that no model can rescue.

### What we build

| File | Purpose |
|---|---|
| `config/crops.yaml` | one block per crop — aliases, `k_c`, shelf life, max hold, seasons |
| `config/mandis.yaml` | the 3–4 districts and their mandis, with coordinates |
| `db/schema.sql` | add `crop_coverage` view; index on `(commodity_id, mandi_id, obs_date)` |
| `scripts/init_db.py` | seed every crop and alias from config |
| `backend/ingestion/audit.py` | audit per (district × crop), not just per mandi |

### In simple words

> Round 1 knew about exactly one crop. Now the filing cabinet needs a drawer for every
> vegetable and fruit, and each drawer needs to know how fast that thing rots — because
> tomato and potato are completely different businesses. A tomato left for a week is
> rubbish; a potato is fine.

### Done when

- Every crop in `crops.yaml` seeded with ≥ 3 aliases
- No crop has `max_hold_days > shelf_life_days`
- `pytest backend/tests/test_phase2_ingestion.py` — all green
- Audit shows per-crop coverage per district

**Time:** 1–2 days.

---

## Phase A3 — The baseline forecaster (the borrowed engine)

**Goal:** a real, honest `ForecastProvider` that needs no training — and doubles as the
benchmark the trained model must beat.

### What we build

| File | Purpose |
|---|---|
| `backend/ml/baselines.py` | naive, seasonal-naive, drift, MA-7 — point forecasts |
| `backend/ml/baseline_provider.py` | wraps them as a `ForecastProvider` with real bands |
| `backend/ml/metrics.py` | pinball loss, PICP, MAPE, directional accuracy |

**How the bands come out honest without a model.** p50 is seasonal-naive. The band is
the *empirical* distribution of that baseline's own past errors, for that crop and that
horizon, widened by √h. So the range is derived from how wrong this method has actually
been historically — not invented, not a fixed ±15%. A thin-data crop gets a wide band
automatically, which is the correct behaviour.

### In simple words

> We need something that answers "what will onion cost in a week" today, without
> pretending to be clever. So we use the oldest trick there is: next week looks like
> last week, adjusted for the season. Then — and this is the part that keeps us honest —
> we look up how badly that guess has missed in the past, and we quote that miss as our
> uncertainty range. It is a humble forecast with a truthful error bar, which is far
> more useful than a confident forecast with an invented one. And when the real model
> arrives, this is exactly the opponent it has to beat before we are allowed to ship it.

### How to test it

1. `pytest backend/tests/test_phaseA3_baseline.py` — must pass the A0 contract tests unmodified
2. p10 ≤ p50 ≤ p90 on 100 random cases
3. PICP on held-out data — record it; this is the number the model must improve
4. A crop with 30 days of history must produce a visibly wider band than one with 300

### Done when

- `BaselineProvider` passes every A0 contract test
- Baseline metrics for all four horizons written to `model_registry` as version `baseline-v1`
- Those metrics are the recorded floor for Track B's gate

**Time:** 1–2 days.

---

## Phase A4 — Feature builder, serving path only

**Goal:** [backend/features/builder.py](backend/features/builder.py) produces one
leakage-free feature row for any (crop, mandi, as_of).

This is the part of [PLAN-FINAL.md](PLAN-FINAL.md) Phase 3 that does **not** disappear,
and it is the one that gets wrongly skipped. The trained model will need a feature row
built at inference time, in the column order frozen in
[backend/features/registry.py](backend/features/registry.py). If that path is not built
and tested now, swap day discovers it.

What *does* defer to Track B: the 20,000-row training matrix and the caching in
[backend/ml/dataset.py](backend/ml/dataset.py).

### What we build

| File | Change |
|---|---|
| `backend/features/builder.py` | arrivals group degrades cleanly when a crop has no arrival data — no silent NaNs |
| `backend/features/registry.py` | freeze the ordered list; it is now a versioned contract |
| `backend/ml/port.py` | `build_serving_row()` — the single inference-time entry point |

### In simple words

> Raw prices tell a model almost nothing. "Yesterday it was ₹1,860" is not a signal.
> "Arrivals are 22% below the monthly average, the neighbouring market is 4% higher,
> Diwali is 11 days away" — that is a picture, and this is the code that paints it. The
> critical rule is that the picture painted for a Tuesday may only use information that
> existed on that Tuesday. We build the painting machine now even though nothing is
> looking at the pictures yet, because the day the model arrives it will demand one
> immediately and in a very specific format.

### How to test it

1. `pytest backend/tests/test_phase3_features.py` — the leakage test especially
2. Insert a fake *future* price, rebuild, confirm the row does not move
3. Build a row for a crop with no arrivals — no NaN, no crash, flag set
4. Column order out of `build_serving_row()` matches `registry.FEATURE_ORDER` exactly

### Done when

- Leakage test passes for every crop
- No all-NaN column for any crop
- A serving row builds in under 100ms

**Time:** 1–2 days.

---

## Phase A5 — Net In-Hand economics, in Python

**Goal:** port the TypeScript economics engine to Python as the single source of truth.

**Zero model dependency.** This is pure arithmetic, and it is the heart of the product.

### What we build

| File | Purpose |
|---|---|
| `backend/economics/spoilage.py` | `spoilage_fraction(k_c, days, storage, tmax)` |
| `backend/economics/net_realisation.py` | `net_in_hand()` → `NetResult` with full breakdown |
| `backend/economics/compare.py` | `compare_mandis()` → gross rank vs net rank |
| `config/cost_model.yaml` | exists — replace every `SOURCE: <fill in>` with a real URL |

Port [frontend/lib/mock/economics.ts](frontend/lib/mock/economics.ts) exactly, including
`net_per_qtl` being divided by the **original** quantity, so spoilage shows up as a lower
rate rather than hiding inside the total.

### In simple words

> Every other app shows a farmer the market price — say ₹2,010. That number is a lie for
> him. Out of it comes 3% commission, 1% market cess, loading, the diesel to move 80
> quintals 62 kilometres, and if he waits a week, some of it rots. What reaches his hand
> might be ₹1,842. We compute that — and it needs no forecast at all, which is why it
> can be finished before the engine arrives. The striking consequence is that the market
> with the highest price is often not his best market.

### How to test it

1. `pytest backend/tests/test_phase5_economics.py`
2. Net always below gross; net falls with distance; net falls with days held; a zero-day hold has exactly zero spoilage
3. **At least one case where gross rank and net rank give different winners** — the demo moment, guaranteed by a test
4. Python and TypeScript agree to the rupee on 20 sample lots

### Done when

- All economics tests pass, including the rank-flip case
- Every `SOURCE: <fill in>` in `cost_model.yaml` is a real URL

**Time:** 1–2 days.

---

## Phase A6 — Decision engine, in Python

**Goal:** forecasts + economics → one imperative sentence with a rupee figure.

**Model-independent by construction.** It consumes `dict[int, Quantiles]` and nothing
else, so it never learns whether it is fed by a baseline or a booster.

### What we build

| File | Purpose |
|---|---|
| `backend/decision/engine.py` | grid search over sell-fraction × hold-days × mandi |
| `backend/decision/constraints.py` | the six hard rules that override the maths |
| `backend/decision/confidence.py` | band tightness + data quality + historical hit rate |
| `backend/decision/explain.py` | rule-based reason line from `decision.yaml` templates |

**Carry the Round 1 fix.** Scoring must be *convex* in the sell fraction:

```python
exposure = later_qty / lot.qty_qtl
score = e_net - risk_lambda * downside * exposure
```

A flat `e_net - λ × downside` is linear, so the optimum always sits at a corner — sell
everything or hold everything — and the split recommendation the whole product is built
on becomes mathematically unreachable. This passed 47 tests before we caught it.

**On explanations.** [config/decision.yaml](config/decision.yaml) already carries
`explanation_templates` keyed by feature name. Fill them from the feature row, ranked by
rule, not by SHAP. This is not a placeholder — it is the fallback you want anyway, since
SHAP output has to be translated into farmer language regardless. SHAP re-ranks it in B4.

### In simple words

> Now the system stops describing and starts deciding. It tries hundreds of plans — sell
> everything now, sell half and wait a week, sell a quarter and wait two weeks, at each of
> several markets — works out the real rupees for each, and picks the best. But not simply
> the highest average: it deliberately penalises plans with a bad worst case, because a
> farmer with a loan cannot afford a gamble that occasionally goes badly. On top sit six
> hard rules that override the maths entirely.

### How to test it

1. `pytest backend/tests/test_phase6_decision.py`
2. **Anti-vacuity:** at least one crop returns a genuine split — two tranches, both non-zero
3. Perishable crops (tomato, okra, banana) return sell-now; storable ones (potato, garlic, onion) sometimes hold
4. Tranche quantities sum to the lot quantity
5. Cautious never holds longer than aggressive on the same input
6. Every constraint has a test proving it fires
7. **Provider-swap test:** run the same lot through two different stub providers — the recommendation must change

Test 7 is the one that protects swap day. If the recommendation does not move when the
forecast moves, the engine is ignoring the forecast — and that is precisely the failure
a real model would mask rather than reveal. Write it now, while the stub makes it easy.

### Done when

- All decision tests pass, **including the anti-vacuity and provider-swap ones**
- Expected gain ≥ 0 for the chosen plan in ≥ 90% of 200 random scenarios
- Python matches the TypeScript engine's decisions on 20 sample lots

**Time:** 2–3 days.

---

## Phase A7 — FastAPI backend

**Goal:** every page's data served from Postgres.

### What we build

| File | Endpoints |
|---|---|
| `backend/api/main.py` | app, CORS, error handlers |
| `backend/api/schemas.py` | Pydantic models matching [frontend/lib/types.ts](frontend/lib/types.ts) exactly |
| `routers/mandis.py` | `GET /mandis`, `GET /districts` |
| `routers/prices.py` | `GET /prices/today`, `GET /prices/series` |
| `routers/forecast.py` | `GET /forecast` — calls `get_provider()`, never a model directly |
| `routers/recommend.py` | `POST /recommend` |
| `routers/compare.py` | `GET /compare` |
| `routers/history.py` | `GET/POST /history` |
| `routers/community.py` | `GET/POST /pools` |
| `routers/accuracy.py` | `GET /accuracy` — reads `model_registry`, returns the **active** version's metrics |
| `routers/sale_reports.py` | `POST /sale-reports` |
| `routers/chat.py` | `POST /chat` → agent |

**The accuracy endpoint is the one place the stub is visible.** It must return the
provider name and version alongside the metrics — `baseline-v1` today, `lgbm-v3` later.
The page shows honest numbers either way; only the label changes on swap day.

### In simple words

> The website currently invents its numbers in the browser. This is the wire that
> connects it to the real machinery. Get the shapes right and the website won't notice
> the swap — it will just start telling the truth.

### How to test it

1. `make api`, open `http://localhost:8000/docs`, exercise every endpoint
2. `pytest backend/tests/test_phase8_api.py`
3. Field names identical to the matching TypeScript type
4. Ask for a crop with no data → clean 422 with a readable message, not a 500

### Done when

- Every endpoint returns 200 with correct shapes
- `InsufficientData` → 422 with a readable message
- p95 under 500ms for cached forecasts
- No router imports anything from `backend/ml` except `get_provider`

**Time:** 3–4 days.

---

## Phase A8 — Connect the website to the real backend

**Goal:** delete the mock layer. **Change nothing visual.**

[frontend/lib/api.ts](frontend/lib/api.ts) is 86 lines and was written for this day —
every component already awaits these functions, and `USING_MOCK_DATA` is already there.
Each body becomes a `fetch`.

### What we build

| File | Change |
|---|---|
| `frontend/lib/api.ts` | every function becomes a `fetch` — the only real change |
| `frontend/lib/mock/` | delete, except `crops.ts` if it holds display metadata |
| `frontend/.env.local` | `NEXT_PUBLIC_API_BASE_URL` |
| components | loading and error states where missing |

### In simple words

> Everything the website shows becomes real in a single afternoon — real prices, real
> economics, real decisions, and a forecast from a humble model instead of a clever one.
> Nobody watching can tell which parts are which, and that is the point: on swap day the
> website does not change at all, it just gets a better forecast behind the same wire.

### How to test it

1. Backend running, `npm run dev`, click every one of the 15 pages
2. `bash .testbuild/route-tests.sh` — all 36 still pass
3. Stop the backend — pages show a clear error, not a blank screen

### Done when

- No file under `frontend/lib/mock/` is imported by any page
- All 36 route tests pass against the live API
- Every page has a loading and an error state
- Screenshots before and after are pixel-identical

**Time:** 2 days.

---

## Phase A9 — Backtest harness

**Goal:** the machinery that produces *"following our advice beats selling immediately
by X%"* — run today against the baseline, re-run on swap day against the model.

### What we build

| File | Purpose |
|---|---|
| `backend/backtest/scenarios.py` | sample lots over a held-out period |
| `backend/backtest/runner.py` | replay through the **live** `optimise()`, provider injected |
| `backend/backtest/report.py` | uplift, win rate, per-crop breakdown, **provider name in the header** |
| `scripts/backtest.py` | CLI — `--provider baseline` / `--provider lightgbm` |

The runner must call the real `optimise()`, not a special backtest path. If backtest and
production run different code, the backtest is fiction.

### In simple words

> This is the number the judges will believe or not believe. Running it now against the
> baseline tells us something genuinely useful and slightly uncomfortable: how much of
> our uplift comes from the *economics and the decision rules* rather than from the
> forecast. If the baseline already produces a positive uplift, the product has value
> before the AI even arrives — and the model's job becomes to widen a real gap rather
> than to create one from nothing. If the baseline uplift is negative, we have found a
> bug in the decision engine now, while it is still cheap to fix.

### How to test it

1. `python scripts/backtest.py --provider baseline` → read `data/artifacts/backtest.md`
2. Confirm the held-out period genuinely postdates the data used
3. Per-crop table — is the uplift broad, or one lucky crop?
4. Win rate plausible (55–70%); 95% means a bug

### Done when

- Baseline uplift produced, positive, and explainable
- Report header states the provider and version
- Re-running with a different provider needs only the flag

**Time:** 2 days.

---

## Phase A10 — Real accounts

**Goal:** replace demo auth with OTP-over-WhatsApp login. Zero model dependency.

| File | Purpose |
|---|---|
| `backend/auth/otp.py` | generate, store in Redis with TTL, verify, rate-limit |
| `backend/auth/session.py` | signed session tokens |
| `routers/auth.py` | `POST /auth/request-otp`, `POST /auth/verify` |
| `frontend/lib/auth.tsx` | swap localStorage for real session calls |

Rate-limit per number. Never log the code.

### In simple words

> Right now anyone can type any number and get in — fine for a demo video, not for a real
> product. Now the code actually goes to the farmer's WhatsApp, expires in ten minutes,
> and can't be brute-forced. His lots, his history and his sale reports become his.

### Done when

- OTP arrives on a real phone; wrong / expired / reused codes all rejected
- 10 rapid requests → rate-limited
- Sessions survive a restart

**Time:** 2 days.

---

## Phase A11 — The WhatsApp agent ⭐

**Goal:** a farmer types anything in Marathi, Hindi or English and gets a correct answer
built from real tool calls.

**Fully buildable without the model** — and this is the clearest proof the port works.
The agent's `get_forecast` tool calls `get_provider().predict_quantiles()`. The agent
cannot tell what is behind it, because it is forbidden from knowing any numbers itself.

### What we build

| File | Purpose |
|---|---|
| `backend/agent/tools.py` | the tool functions Claude may call |
| `backend/agent/agent.py` | the agent loop |
| `backend/agent/prompts.py` | system prompt (cached) |
| `backend/agent/session.py` | Redis conversation state per phone number |
| `backend/whatsapp/client.py` | send via Meta Cloud API |
| `backend/whatsapp/webhook.py` | receive + verify HMAC signature |
| `routers/whatsapp.py` | `GET` verification, `POST` inbound |

Tools: `get_price`, `get_forecast`, `get_recommendation`, `compare_mandis`,
`find_transport_pool`, `record_sale` — each a `@beta_tool`, driven by
`client.beta.messages.tool_runner`, system prompt marked `cache_control`,
`output_config={"effort": "low"}` because a farmer is waiting, and
`stop_reason == "refusal"` checked before reading content.

### The guardrail that matters most

> **Every number in a reply must come from a tool result. The model may translate,
> summarise and choose which tool to call — it may never invent a price, a forecast or a
> rupee figure.**

### In simple words

> The clever part is what the AI is *not* allowed to do. It is not allowed to know any
> prices. When it needs a number it has to ask our database, and it can only repeat what
> comes back. So we get the flexibility of a chatbot with the honesty of a calculator.
> That design is also why the missing forecasting model costs us nothing here: the agent
> was never going to be the thing that predicts, only the thing that asks.

### How to test it

1. Tunnel up, webhook registered, send "hi" → Marathi greeting
2. "कांदा ८० क्विंटल" → calls `get_recommendation`, replies with a real plan
3. Something confusing → a clarifying question, not a crash
4. **Honesty test:** ask about a crop with no data. It must say it doesn't know. If it invents a price, fix the prompt before anything else
5. Logs: every number in every reply traces to a tool result

### Done when

- Free-form Marathi, Hindi and English all work
- Unknown crops produce an honest "I don't have data for that"
- Bad webhook signatures rejected; median reply under 5 seconds
- The `/chat` page uses the same agent

**Time:** 4–5 days. Meta approval and tunnel setup eat a day on their own — apply now.

---

## Phase A12 — Community pooling

**Goal:** transport pooling backed by the database.

| File | Purpose |
|---|---|
| `db/schema.sql` | `transport_pools`, `pool_members` |
| `backend/community/pools.py` | create, join, leave, compute saving |
| `backend/community/matching.py` | suggest pools by mandi, date, proximity |
| `routers/community.py` | REST endpoints |

### In simple words

> Transport is the one cost a small farmer can actually control. At ₹42 a kilometre a
> 62 km trip costs ₹2,604 whether the truck is full or not — ₹260 a quintal on a
> ten-quintal lot, which is why the nearest mandi so often wins. Four farmers going the
> same morning split it four ways.

### Done when

- Pools persist; the maths matches the economics engine
- Capacity limits enforced; leaving recalculates for everyone remaining
- The agent's `find_transport_pool` returns real pools

**Time:** 2 days.

---

## Phase A13 — Deploy, seed and harden

**Goal:** it runs somewhere other than your laptop, and survives demo day.

| File | Purpose |
|---|---|
| `docker-compose.prod.yml` | api + worker + postgres + redis |
| `scripts/daily_job.py` | APScheduler — collect + precompute (**retrain step added in B4**) |
| `scripts/seed_demo_data.py` | demo farmer, lots, ~30 sale reports (`source='seed_demo'`) |
| `routers/admin.py` | `POST /reset-demo` |
| `docs/RUNBOOK.md` | what to do when something breaks on stage |

### Done when

- Deployed, reachable over HTTPS, daily job on schedule, reset works
- Someone who isn't you can complete the demo from the runbook

**Time:** 2–3 days.

---

# TRACK B — After the model lands

At this point the product is complete and demonstrable. Track B makes it *better*, and
it is short precisely because Track A never let the model leak into anything.

---

## Phase B1 — Build the training set

**Goal:** turn the data that has been accumulating since Phase A1 into a training matrix.

| File | Purpose |
|---|---|
| `backend/ml/dataset.py` | exists — build and cache `train_matrix.parquet` |
| `scripts/build_dataset.py` | CLI |

The volume gate deferred from Phase A4 applies here: ≥ 20,000 rows, zero infinite values,
no all-NaN columns, leakage test green per crop. By now the collector has been running
for weeks, which is exactly why this was worth deferring.

**Time:** 1 day, assuming the model arrives with its own training code.

---

## Phase B2 — Conform the model to the port

**Goal:** wrap whatever arrives so it satisfies `ForecastProvider`.

| File | Purpose |
|---|---|
| `backend/ml/lgbm_provider.py` | loads the boosters, builds the serving row, returns `Quantiles` |

Three rules, all enforced by tests written back in Phase A0:

1. It **sorts** p10/p50/p90 before returning — quantile models cross, and an unsorted
   band silently breaks the decision engine's downside term
2. It builds its feature row through `build_serving_row()`, so training order and
   serving order cannot diverge
3. It raises `InsufficientData` rather than extrapolating for an unknown crop

### How to test it

1. `pytest backend/tests/test_phaseA0_port.py --provider lightgbm` — the **same file** that passed for the baseline, unmodified
2. Phase A6's provider-swap test — recommendations must move
3. `grep` the API and agent for model imports — still empty

**Time:** 1 day.

---

## Phase B3 — The gate: beat the baseline, or don't ship

**Goal:** decide, on evidence, whether the model replaces the baseline.

Phase A3 recorded the baseline's pinball loss, PICP, MAPE and directional accuracy.
Phase A9 recorded the baseline's backtest uplift. Both are in `model_registry`. Now:

1. `python scripts/backtest.py --provider lightgbm`
2. Compare against the stored `baseline-v1` row

**Promote only if:** it beats naive pinball loss at all four horizons,
0.72 ≤ PICP ≤ 0.88, directional accuracy at 7 days > 0.60, h=1 MAPE under ~8%,
h=7 under ~15%, and the backtest uplift exceeds the baseline's.

**If it fails, `provider: baseline` stays in config and the product still works.** That
is the entire payoff of building this way: a disappointing model is a config decision,
not a crisis on stage.

### In simple words

> Because we built the humble version first and wrote its score down, the clever version
> has to earn its place by beating a number we already have. Most projects skip this and
> find out on stage that their model is worse than "same as yesterday". Ours cannot,
> because "same as yesterday" is already running in production and we know exactly how
> well it does.

**Time:** 1 day, plus re-runs.

---

## Phase B4 — Absorb the model into the product

**Goal:** the things that only become possible once a real model is active.

| File | Purpose |
|---|---|
| `backend/ml/explain.py` | SHAP → re-ranks the existing `decision.yaml` templates |
| `backend/ml/registry.py` | version, metrics, promote-if-better |
| `scripts/train.py` | CLI entry point for retraining |
| `scripts/daily_job.py` | add the weekly retrain step |
| `routers/accuracy.py` | **nothing to change** — it already reads the active version |
| `frontend/` | **nothing to change** |

Note the last two rows. The accuracy page, the dashboard, the advisor and the WhatsApp
agent all require zero edits on swap day. That is the receipt for Phase A0.

**Time:** 1–2 days.

---

# Schedule

| Phase | Days | Parallel with |
|---|---|---|
| A0 · Forecast port | 0.5 | — (do first) |
| A1 · Data, serving grade | 1–2 | everything after (it keeps collecting) |
| A2 · Multi-crop DB | 1–2 | — |
| A3 · Baseline forecaster | 1–2 | A4 |
| A4 · Feature builder (serving) | 1–2 | A3 |
| A5 · Economics | 1–2 | A3, A4 |
| A6 · Decision engine | 2–3 | — |
| A7 · API | 3–4 | A9 |
| A8 · Frontend wiring | 2 | A10 |
| A9 · Backtest harness | 2 | A7 |
| A10 · Auth | 2 | A8 |
| A11 · **WhatsApp agent** | 4–5 | A12 |
| A12 · Community | 2 | A11 |
| A13 · Deploy | 2–3 | — |
| **Track A total** | **22–27** | |
| B1 · Training set | 1 | — |
| B2 · Conform to port | 1 | — |
| B3 · The gate | 1 | — |
| B4 · Absorb | 1–2 | — |
| **Track B total** | **4–5** | |

**One ordering change from [PLAN-FINAL.md](PLAN-FINAL.md):** A7 (API) and A8 (frontend)
come *before* A9 (backtest). Getting the site off mock data is worth more right now than
an uplift number computed from baselines — and the backtest harness is easier to write
once the API has settled the shapes.

---

# Swap day — the whole checklist

When the model arrives, this is everything that happens:

```
1. python scripts/build_dataset.py                    # B1
2. write backend/ml/lgbm_provider.py                  # B2
3. pytest backend/tests/test_phaseA0_port.py          # B2 — unmodified file
4. python scripts/backtest.py --provider lightgbm     # B3
5. compare against model_registry baseline-v1         # B3
6. edit config/model.yaml:  provider: lightgbm        # ← the swap
7. restart api
```

**One config line.** No frontend change, no API change, no agent change, no decision
engine change. If swap day requires touching anything in `backend/api/`,
`backend/agent/`, `backend/decision/` or `frontend/`, then Phase A0 was violated
somewhere, and that is the bug to find.

---

# What is honestly missing until the model lands

Say these out loud rather than hiding them. Every one is a label, not a hole:

| Thing | Without model | After model |
|---|---|---|
| Forecast quality | Seasonal-naive with empirical error bands | LightGBM quantile |
| Accuracy page | Real metrics, labelled `baseline-v1` | Real metrics, labelled `lgbm-vN` |
| Backtest uplift | Real number, from baseline forecasts | Re-run, expected to be larger |
| Reason line | Rule-based from `decision.yaml` templates | SHAP-ranked, same templates |
| Daily job | Collect + precompute | Collect + precompute + retrain |

Nothing in that first column is fake. It is a working product with a modest forecaster —
a far better position than a clever forecaster wired to a product that does not exist.

---

# The five things most likely to go wrong

1. **The port leaks.** Someone imports a booster in a router "just for now", and swap day
   becomes a refactor. *Mitigation:* the `grep` check from A0 runs in CI.
2. **Data never gets dense enough.** This bit us twice already. *Mitigation:* A1 starts
   day one and accumulates across the whole of Track A, so B1 inherits weeks of collection.
3. **The decision engine ignores the forecast.** It would pass every test, look fine, and
   the model would change nothing. *Mitigation:* A6 test 7, the provider-swap test.
4. **The model doesn't beat the baseline.** *Mitigation:* B3 is a gate, not a formality,
   and failing it costs one config line rather than the demo.
5. **The agent invents a price.** Fatal on stage — a judge will test it. *Mitigation:*
   A11's honesty test is a release gate, and the guardrail sits in the system prompt.

---

# What "done" means for Track A

- [ ] `ForecastProvider` is the only way anything reaches a forecast
- [ ] Real prices for 3–4 districts and every crop the data supports
- [ ] A baseline forecaster with honest, empirically-derived bands
- [ ] Economics and decision engines in Python, matching the TypeScript to the rupee
- [ ] A genuine split recommendation exists (anti-vacuity)
- [ ] Every website page served from Postgres, zero mock imports, UI visually unchanged
- [ ] A positive, explainable backtest uplift from the baseline
- [ ] A WhatsApp agent answering free-form Marathi with tool-grounded numbers
- [ ] Real OTP login
- [ ] Deployed, with a daily job and a reset button
- [ ] Swap day is one line in `config/model.yaml`
