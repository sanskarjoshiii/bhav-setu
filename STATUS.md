# STATUS.md — Where Bhav Setu actually stands

> Generated 26 August 2026, by reading every file in the repo and running the tests that
> can run today. Measured against [PLAN-NOMODEL.md](PLAN-NOMODEL.md) (Track A + Track B)
> and [PLAN-FINAL.md](PLAN-FINAL.md).
>
> **Nothing here is guessed.** Where something could not be verified, it says so and says
> why.

---

## The one-paragraph answer

The **engine mounts are bolted down and a borrowed engine is running.** Phases A0–A3 of
the no-model plan are built and tested: the forecast port is frozen, the daily collector
is written, thirteen crops across four districts are configured, and a real seasonal-naive
forecaster with honest error bands answers questions today. **Everything from A5 onward —
the economics engine, the decision engine, the API, the WhatsApp agent, the backtest,
auth, pooling and deploy — is still an empty folder.** The website is finished and
beautiful but is still inventing all of its numbers in the browser. The model itself has
not been trained, and its training set does not exist yet.

**Roughly 4 of 14 Track A phases done. Track B's code now exists end to end
(see [MODEL.md](MODEL.md)) but cannot run on real data — the whole dataset is
three October snapshots, 70 distinct dates in a 753-day span, which yields
exactly zero trainable rows.**

---

## Scoreboard

| Phase | What it is | State |
|---|---|---|
| **A0** | Forecast port (the contract) | ✅ **Done** |
| **A1** | Daily data collection | 🟡 Code done · data thin, unverified |
| **A2** | Multi-crop database + cleaning | 🟡 Config done · DB verification blocked |
| **A3** | Baseline forecaster | 🟡 Code done · scores not recorded to DB |
| **A4** | Feature builder (serving path) | 🟡 Half done |
| **A5** | Economics in Python | ❌ Not started |
| **A6** | Decision engine in Python | ❌ Not started |
| **A7** | FastAPI backend | ❌ Not started |
| **A8** | Wire website to real backend | ❌ Not started |
| **A9** | Backtest harness | ❌ Not started |
| **A10** | Real OTP accounts | ❌ Not started |
| **A11** | WhatsApp agent ⭐ | ❌ Not started |
| **A12** | Community pooling | ❌ Not started |
| **A13** | Deploy + seed + harden | ❌ Not started |
| **B1** | Build the training set | 🟡 Code built · blocked on data |
| **B2** | Wrap the model to the port | 🟡 Built · unverified on real data |
| **B3** | The gate (beat the baseline) | 🟡 Built · no baseline recorded yet |
| **B4** | Absorb the model | 🟡 Registry + trainer built · SHAP pending |

Legend: ✅ built and proven · 🟡 built but not fully proven · ❌ nothing there yet

---

## Blocker found today, before anything else

**Docker is not running, so Postgres and Redis are down.**

```
docker ps  →  failed to connect to the docker API ... daemon not running
```

Every test that touches the database **hangs** rather than failing cleanly. When the full
suite is run it stalls partway and never finishes.

What this means for this report: the tests that need no database were run and their
results are real. The tests that need one could not be run at all, so those phases are
marked 🟡 *unverified*, not ❌ *broken*. Start Docker (`make up`) before trusting any
DB-related claim below.

| Test file | Needs DB? | Result today |
|---|---|---|
| `test_phaseA0_port.py` + `test_phaseA3_baseline.py` | No | ✅ **84 passed, 2 skipped** |
| `test_phase0_scaffold.py` | Yes | ⏸ hangs — Postgres down |
| `test_phase1_schema.py` | Yes | ⏸ hangs — Postgres down |
| `test_phase2_ingestion.py` | Yes | ⏸ hangs — Postgres down |
| `test_phase3_features.py` | Yes | ⏸ hangs — Postgres down |
| `test_phaseA1_collect.py` | Partly | ✅ 43 passed, then stalled on a DB test |
| `test_phaseA2_crops.py` | Yes | ⏸ hangs — Postgres down |

*(Both skips are expected. One is the `--provider` contract run, which needs the flag and a
database. The other is the Phase A0 guard that asserted "B2 has not landed" — now that
[backend/ml/lgbm_provider.py](backend/ml/lgbm_provider.py) exists it reports **"Phase B2 has
landed, this test retires"**, which is the port behaving as designed.)*

---

# TRACK A — the product without the model

## ✅ Phase A0 — The forecast port

**In simple words:** the engine mounts. Everything that ever needs a price prediction must
ask through one small door, so the day the real model arrives it just plugs into that door
and nothing else changes.

### Built

| File | What it does |
|---|---|
| [backend/ml/port.py](backend/ml/port.py) | `Quantiles` (p10/p50/p90), the `ForecastProvider` protocol, `validate_forecast()`, `ServingRow`, `build_serving_row()` |
| [backend/ml/provider.py](backend/ml/provider.py) | `get_provider()` — reads `config/model.yaml` and returns the live forecaster; also `register_provider()` and a cache reset |
| [config/model.yaml](config/model.yaml) | `provider: baseline`, plus a `providers:` map pointing at `baseline` and `lightgbm` |
| [backend/tests/contract_forecast.py](backend/tests/contract_forecast.py) | the reusable contract suite — ordering, shape, determinism, unknown-crop, uncertainty-grows-with-horizon, responds-to-input |
| [backend/tests/test_phaseA0_port.py](backend/tests/test_phaseA0_port.py) | 31 tests wrapping that suite |

### Proven

- All contract tests pass against the real baseline provider
- `p10 ≤ p50 ≤ p90` is enforced, not hoped for
- An unknown crop raises `InsufficientData` instead of returning zeros
- Swapping the forecaster is genuinely one line: `provider: baseline` → `provider: lightgbm`

### Still to do

- Nothing for the phase itself. **But** the plan's `grep` guard ("no router or agent may
  import LightGBM") is not wired into CI yet — there is no CI. It costs nothing today
  because no routers exist; add it the moment A7 starts.

---

## 🟡 Phase A1 — Data, serving grade

**In simple words:** the taps that fill the tank. The code to fetch prices every day is
written and looks solid. The tank is still nearly empty.

### Built

| File | What it does |
|---|---|
| [backend/ingestion/datagov.py](backend/ingestion/datagov.py) | the data.gov.in Agmarknet feed — 502 lines, the biggest new piece in the last commit |
| [backend/ingestion/ceda.py](backend/ingestion/ceda.py) | the CEDA fallback source |
| `agmarknet.py`, `cleaners.py`, `entity_resolution.py`, `routing.py`, `shocks.py`, `weather.py`, `backfill_csv.py`, `audit.py` | fetch → clean → fuzzy-match names → audit |
| [scripts/collect_daily.py](scripts/collect_daily.py) | the cron-able collector (`make collect`) |
| [scripts/inspect_dataset.py](scripts/inspect_dataset.py) | the gate you read before importing anything |
| [config/sources.yaml](config/sources.yaml) | source priority, retry and cache paths — filled in |
| [backend/tests/test_phaseA1_collect.py](backend/tests/test_phaseA1_collect.py) | 30 tests |

### Not proven — this is the real risk

The only evidence of actual data is
[data/artifacts/data_audit.md](data/artifacts/data_audit.md), and it is **stale and
damning**:

- Dated **14 August**, before the current collector was written
- Covers **onion only**, across **5 Nashik mandis** — not the 13 crops and 4 districts now configured
- **41–48 rows per mandi**, 7–9% business-day coverage, longest gap **250 days**
- Verdict printed at the bottom: **"0 of 5 mandis are USABLE."**
- 20+ source mandi names failed to resolve (Pune, Solapur, Jalgaon, Kalyan …) — those are
  rows that were fetched and then thrown away

### The A1 "done when" checklist, honestly

| Requirement | Status |
|---|---|
| ≥ 3 districts have a current price for ≥ 5 crops | ❌ unknown — last audit had 1 crop |
| ≥ 90 days of history for at least one crop per district | ❌ unknown — last audit had 250-day gaps |
| Re-running adds no duplicates | 🟡 tested in code, not observed on real runs |
| Collector runs unattended for 3 consecutive days | ❌ no evidence it has ever run on a schedule |

### Next actions

1. `make up`, then `make collect` and let it actually run
2. Re-run `python scripts/inspect_dataset.py` and regenerate the audit
3. Fix the unresolved mandi names — those are free rows currently being discarded
4. **Put the collector on a real schedule today.** Everything else in Track A takes weeks;
   the data only accumulates in wall-clock time. This is the single highest-value thing on
   this whole page.

---

## 🟡 Phase A2 — Multi-crop database and cleaning

**In simple words:** a drawer in the filing cabinet for every vegetable and fruit, and each
drawer knows how fast that thing rots.

### Built

| File | What it does |
|---|---|
| [config/crops.yaml](config/crops.yaml) | **13 crops** — garlic, onion, potato, pomegranate, cabbage, orange, grapes, mango, banana, cauliflower, green chilli, brinjal, tomato, okra — each with aliases (English + Hindi + Marathi + Devanagari), `crop_group`, `perishability_class`, `k_c`, `shelf_life_days`, `max_hold_days`, `msp_applicable`, harvest seasons |
| [config/mandis.yaml](config/mandis.yaml) | **17 market yards across 4 districts** — Nashik, Pune, Solapur, Ahmednagar — with coordinates |
| [db/schema.sql](db/schema.sql) | 19 tables + the `crop_coverage` view + `idx_po_lookup (commodity_id, mandi_id, obs_date DESC)` + `idx_mandis_district` |
| [scripts/init_db.py](scripts/init_db.py) | seeds every crop and alias from config |
| [backend/ingestion/audit.py](backend/ingestion/audit.py) | extended to audit per district × crop |
| [backend/tests/test_phaseA2_crops.py](backend/tests/test_phaseA2_crops.py) | 35 tests |

### Still to do

- **Run the tests.** All 35 need Postgres; none has been executed since the config grew
  from 1 crop to 13. The "no crop has `max_hold_days > shelf_life_days`" rule is asserted
  in the test file, so it is written but unconfirmed.
- Re-run the audit so the per-crop-per-district coverage table exists for the new config.
- The plan's caveat still stands: expect 8–14 crops to actually survive the data. Right now
  13 are *configured*; how many are *supported* is unknown until A1 delivers.

---

## 🟡 Phase A3 — The baseline forecaster (the borrowed engine)

**In simple words:** something that can answer "what will onion cost next week" today,
without being clever — and which quotes a truthful error bar by looking up how badly that
same guess has missed in the past.

### Built

| File | What it does |
|---|---|
| [backend/ml/baselines.py](backend/ml/baselines.py) | naive, seasonal-naive, drift, MA-7 |
| [backend/ml/baseline_provider.py](backend/ml/baseline_provider.py) | wraps them as a real `ForecastProvider` with empirical bands |
| [backend/ml/metrics.py](backend/ml/metrics.py) | pinball loss, PICP, MAPE, directional accuracy |
| [scripts/evaluate_baseline.py](scripts/evaluate_baseline.py) | scores the baseline and writes it to `model_registry` |
| `config/model.yaml` → `baseline:` block | seasonal period, MA window, `switch_margin`, `min_history_days`, `min_residuals`, `fallback_band_pct`, `tail_confidence_z`, `min_band_pct` |
| [backend/tests/test_phaseA3_baseline.py](backend/tests/test_phaseA3_baseline.py) | 54 tests |

### Proven — and this is the strongest part of the codebase

- ✅ Passes every A0 contract test **unmodified**
- ✅ Thin-history crops get visibly wider bands, by construction (`tail_confidence_z` widens
  the tail when there are few residuals)
- ✅ Below `min_history_days: 30` it raises `InsufficientData` rather than inventing a number
- ✅ The config comments record a real measured finding: naively picking the best of four
  near-tied baselines made things *worse* at two of four horizons, so a challenger must now
  clear a 2% margin. That is honest engineering.

### Still to do

- **`model_registry` has never been written.** `make evaluate-baseline` needs Postgres and
  needs A1's data. Until it runs there is **no recorded floor**, which means **Track B's
  gate (B3) has nothing to compare against.** This is a small job with a large consequence —
  do it as soon as the DB is up.
- PICP on held-out data has not been measured on real data.

---

## 🟡 Phase A4 — Feature builder, serving path

**In simple words:** the machine that paints the picture the model looks at. Half of it is
built.

### Built

| Piece | State |
|---|---|
| `build_serving_row()` in [backend/ml/port.py:183](backend/ml/port.py#L183) | ✅ Done — and it *asserts* the column order matches the registry, raising `ForecastContractError` on drift. Exactly the guard the plan asked for. |
| `FEATURE_NAMES` in [backend/features/registry.py:107](backend/features/registry.py#L107) | ✅ Frozen, with duplicate detection and a categorical-features check at import time |
| [backend/features/builder.py](backend/features/builder.py) | 🟡 Exists from Phase 3 — price, arrival, cross-mandi, calendar, weather, shock, entity and guard features, plus `_finalise()` which guarantees exact registry order and never emits ±inf |

### Not done

- **The arrivals fix this phase was specifically about.** `arrival_features()` at
  [backend/features/builder.py:298](backend/features/builder.py#L298) still returns `NaN`
  for all six arrival features when a crop has no arrival data, **with no flag set**. The
  plan's requirement — *"degrades cleanly … no silent NaNs"* — is not met. With 13 crops now
  configured and arrival data sparse, this will hit most of them.
- There is **no `test_phaseA4` file**. The phase inherits `test_phase3_features.py`, which
  cannot run without Postgres, so the leakage test is unverified against the new crop set.
- The "serving row builds in under 100ms" target has never been measured.

---

## ❌ Phase A5 — Net In-Hand economics, in Python

**In simple words:** the heart of the product — turning the ₹2,010 board price into the
₹1,842 that actually reaches the farmer's hand. It needs no forecast at all, so it could
have been built on day one. It has not been built at all.

`backend/economics/` contains one file: `.gitkeep`.

| Needed | State |
|---|---|
| `backend/economics/spoilage.py` | ❌ missing |
| `backend/economics/net_realisation.py` | ❌ missing |
| `backend/economics/compare.py` | ❌ missing |
| `backend/tests/test_phase5_economics.py` | ❌ missing (so `make check-phase5` fails) |
| `config/cost_model.yaml` real sources | ❌ **8 `SOURCE: <fill in>` placeholders remain** — hamali, weighing, packing, transport/km, commission %, cess %, other fees % |

The logic *does* exist, in TypeScript, at
[frontend/lib/mock/economics.ts](frontend/lib/mock/economics.ts). A5 is a port, not an
invention — including the detail that `net_per_qtl` divides by the **original** quantity so
spoilage shows as a lower rate rather than hiding in the total.

**Also required and missing:** the rank-flip test (a case where the highest-price mandi is
not the best mandi). That is the demo moment, and the plan wants it guaranteed by a test.

---

## ❌ Phase A6 — Decision engine, in Python

**In simple words:** where the system stops describing and starts deciding.

`backend/decision/` contains one file: `.gitkeep`.

| Needed | State |
|---|---|
| `backend/decision/engine.py` (grid search over sell-fraction × hold-days × mandi) | ❌ missing |
| `backend/decision/constraints.py` (the six hard rules) | ❌ missing |
| `backend/decision/confidence.py` | ❌ missing |
| `backend/decision/explain.py` | ❌ missing |
| `backend/tests/test_phase6_decision.py` | ❌ missing |

[config/decision.yaml](config/decision.yaml) **is** ready: sell fractions, hold horizons,
`risk_lambda` per profile, constraints, confidence weights and explanation templates are all
filled in. The config is waiting for the code.

**Two things carried forward that must not be lost when this is written:**

1. **The convexity fix.** Scoring must be `e_net - risk_lambda * downside * exposure`, where
   `exposure = later_qty / lot.qty_qtl`. A flat `e_net - λ × downside` is linear, so the
   optimum always lands on a corner and the split recommendation — the thing the whole
   product is built on — becomes mathematically impossible. *This passed 47 tests before it
   was caught last round.*
2. **Test 7, the provider-swap test.** Run the same lot through two different stub providers;
   the recommendation must change. If it does not, the engine is ignoring the forecast, and a
   real model would hide that failure rather than reveal it. It is easy to write now while
   the stub exists and hard to retrofit later.

---

## ❌ Phase A7 — FastAPI backend

`backend/api/` and `backend/api/routers/` contain only `.gitkeep`. There is no `main.py`, no
`schemas.py`, and **zero of the twelve routers**: mandis, prices, forecast, recommend,
compare, history, community, accuracy, sale_reports, chat, auth, whatsapp.

`make api` will fail — `uvicorn api.main:app` has nothing to import.

The one design note to carry in: **the accuracy endpoint must return the provider name and
version alongside the metrics** (`baseline-v1` today, `lgbm-vN` later). That is what lets
the accuracy page stay honest without a single edit on swap day.

---

## ❌ Phase A8 — Connect the website to the real backend

**The website itself is genuinely finished.** 15 pages, real components, a real design.

| | | |
|---|---|---|
| `/` home | `/dashboard` | `/advisor` |
| `/compare` | `/accuracy` | `/transparency` |
| `/community` | `/chat` | `/lots` |
| `/history` | `/reports` | `/about` |
| `/help` | `/login` | `/signup` |

Plus 16 components (ForecastChart, MandiMap, CostWaterfall, RecommendationCard,
ConfidenceMeter, NetComparisonTable, ChatWindow, LotForm, CropPicker …) and a 95-line
route-test script.

**But every number on every page is invented in the browser.**

- `frontend/lib/mock/` still has **9 mock modules** (mandis, prices, economics,
  recommendation, accuracy, transparency, community, chat, crops)
- **20 import lines** across pages and components still pull from `@/lib/mock/`
- [frontend/lib/api.ts](frontend/lib/api.ts) is written for this day — every function is a
  one-line `settle(mockValue)` waiting to become a `fetch` — but not one has been converted
- ⚠️ **`USING_MOCK_DATA` is set to `false` while the data is still 100% mock.** That flag is
  lying right now. Either flip it to `true` until A8 lands, or delete it — a false "we're on
  real data" signal is exactly the kind of thing that gets believed on stage.

---

## ❌ Phase A9 — Backtest harness

`backend/backtest/` contains only `.gitkeep`. `scripts/backtest.py` does not exist, so
`make backtest` fails.

Missing: `scenarios.py`, `runner.py`, `report.py`, and the `--provider` CLI flag.

**Why this one matters more than its position suggests:** running it against the baseline
answers an uncomfortable and genuinely useful question — *how much of our uplift comes from
the economics and decision rules rather than from the forecast?* If the baseline already
produces positive uplift, the product has value before the AI arrives. If it is negative,
there is a bug in the decision engine, and it is far cheaper to find now.

---

## ❌ Phase A10 — Real accounts

No `backend/auth/` directory at all. No `otp.py`, no `session.py`, no auth router.

[frontend/lib/auth.tsx](frontend/lib/auth.tsx) exists but is localStorage demo auth — type
any number, get in.

---

## ❌ Phase A11 — The WhatsApp agent ⭐

**The flagship feature. Nothing exists.**

No `backend/agent/` directory (no `tools.py`, `agent.py`, `prompts.py`, `session.py`). No
`backend/whatsapp/` directory (no `client.py`, `webhook.py`). No `routers/whatsapp.py`.
`backend/bot/` and `backend/bot/locales/` are empty `.gitkeep` placeholders.

[frontend/components/ChatWindow.tsx](frontend/components/ChatWindow.tsx) runs on
`lib/mock/chat.ts` — scripted replies.

The six tools still to write: `get_price`, `get_forecast`, `get_recommendation`,
`compare_mandis`, `find_transport_pool`, `record_sale`.

**The guardrail to build in from the first line, not bolt on later:** every number in every
reply must come from a tool result. The model may translate, summarise and choose which tool
to call — it may never invent a price. The honesty test (ask about a crop with no data; it
must say it doesn't know) is a release gate, because a judge will test it.

**Schedule warning from the plan:** Meta approval and tunnel setup eat a day on their own.
**Apply for WhatsApp Cloud API access now**, before the code is ready — the `.env` slots for
`WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_APP_SECRET` and
`WHATSAPP_VERIFY_TOKEN` are already there and waiting.

---

## ❌ Phase A12 — Community pooling

No `backend/community/` directory. No `transport_pools` or `pool_members` tables in
[db/schema.sql](db/schema.sql). [frontend/app/community/page.tsx](frontend/app/community/page.tsx)
runs entirely on `lib/mock/community.ts`.

---

## ❌ Phase A13 — Deploy, seed and harden

| Needed | State |
|---|---|
| `docker-compose.prod.yml` | ❌ missing (only the dev `docker-compose.yml` exists) |
| `scripts/daily_job.py` (APScheduler) | ❌ missing |
| `scripts/seed_demo_data.py` | ❌ missing — so `make seed` fails |
| `routers/admin.py` → `POST /reset-demo` | ❌ missing |
| `docs/RUNBOOK.md` | ❌ missing |

`docs/` currently holds `architecture.md`, `demo-script.md`, `diagrams-ppt.md` and
`user-flow.md` — presentation material, not operations material.

---

# TRACK B — after the model lands

**All four phases are untouched, and the model has not been trained.**

## ❌ B1 — Build the training set

[backend/ml/dataset.py](backend/ml/dataset.py) exists (218 lines, written back in Phase 3)
but `scripts/build_dataset.py` does not.

`data/artifacts/train_matrix.parquet` exists — but it is **23 KB, dated 14 August**, built
from the Round 1 onion-only data. The gate is **≥ 20,000 rows**, zero infinities, no all-NaN
columns, leakage test green per crop. A 23 KB parquet is nowhere near that.

**This phase is gated on Phase A1 having run for weeks.** That is the whole reason it was
deferred — and the whole reason the collector needs to start today.

## ❌ B2 — Conform the model to the port

`backend/ml/lgbm_provider.py` does not exist. `config/model.yaml` already names it in the
`providers:` map, and `test_phaseA0_port.py` already has a test that **skips** because of it
— so the moment the file appears, the contract suite starts checking it automatically. That
is the port working as designed.

Three rules the tests will enforce: sort p10/p50/p90 before returning (quantile models
cross), build the feature row through `build_serving_row()`, and raise `InsufficientData`
rather than extrapolating.

## ❌ B3 — The gate: beat the baseline, or don't ship

**Cannot run, and not only because the model is missing.** The baseline's scores have never
been written to `model_registry` (see A3), so **there is no floor to compare against**. Two
things must happen before this gate is even meaningful:

1. `make evaluate-baseline` → writes `baseline-v1` metrics
2. `python scripts/backtest.py --provider baseline` → writes the baseline uplift

Neither is possible today. **Fixing this is a prerequisite, not a follow-up.**

Promotion thresholds when it does run: beats naive pinball loss at all four horizons,
`0.72 ≤ PICP ≤ 0.88`, 7-day directional accuracy > 0.60, h=1 MAPE under ~8%, h=7 under ~15%,
and backtest uplift above the baseline's.

## ❌ B4 — Absorb the model

Missing: `backend/ml/explain.py` (SHAP), `backend/ml/registry.py`, `scripts/train.py` (so
`make train` fails), and the weekly retrain step in `daily_job.py`.

Per the plan, `routers/accuracy.py` and the entire `frontend/` need **zero changes** on swap
day. That promise still holds — because neither of them has been built yet in a way that
could break it.

---

# Things that will bite you, found while reading the code

| # | Finding | Why it matters |
|---|---|---|
| 1 | **Docker is down** | Every DB test hangs instead of failing. You cannot currently prove phases 0–3 or A1–A2 work at all. |
| 2 | **`USING_MOCK_DATA = false` while all data is mock** | A false signal in the one place someone would check. Flip it or delete it. |
| 3 | **`model_registry` is empty** | Track B's gate has no floor. A3 looks done but its most important output was never produced. |
| 4 | **`data_audit.md` is 12 days stale and says 0/5 mandis usable** | The config grew from 1 crop to 13 and from 5 mandis to 17; the evidence did not follow. |
| 5 | **8 `SOURCE: <fill in>` in `cost_model.yaml`** | These numbers drive every rupee figure the product shows. Unsourced fees are the fastest way to lose a judge's trust. |
| 6 | **Arrival features go all-NaN with no flag** | The exact A4 requirement that was skipped. Silent NaNs across 13 sparse crops. |
| 7 | **9 of 13 Makefile `check-phase*` targets point at test files that don't exist** | `check-phase4` … `check-phase12` all fail immediately. Harmless, but it makes the Makefile a misleading map of progress. |
| 8 | **20+ mandi names fail to resolve in ingestion** | Pune, Solapur, Jalgaon, Kalyan and more — rows are being fetched and then discarded. Free data, currently thrown away. |

---

# What to do next, in order

**Today**

1. `make up` — get Postgres and Redis running
2. Run the full suite and find out what actually passes: `make test`
3. `make collect` and put it on a schedule. **Every day this slips is a day B1 slips.**
4. `make evaluate-baseline` — record `baseline-v1` in `model_registry`

**This week**

5. Regenerate `data_audit.md` for 13 crops × 4 districts; fix the unresolved mandi names
6. Fill the 8 `SOURCE:` placeholders in `cost_model.yaml`
7. Finish A4 — the arrivals degrade + a `has_arrivals` flag + an A4 test
8. **A5 economics.** Pure arithmetic, zero dependencies, ported from TypeScript that already
   works. The highest-value-per-day item on the board.

**Then, in plan order**

9. A6 decision engine — with the convexity fix and the provider-swap test written first
10. A7 API → A8 frontend wiring → A9 backtest
11. **Start the Meta WhatsApp application now, in parallel with all of the above**

---

# The honest summary

The foundations are better than the progress bar suggests. The port is genuinely well
designed — the contract suite, the column-order assertion in `build_serving_row()`, the
`switch_margin` that came out of a real measurement, and the skipping LightGBM test that
will arm itself the moment the model lands are all signs of someone building for swap day
rather than for a demo.

But **nine and a half of fourteen Track A phases are empty folders**, the two things that
turn data into advice — economics and the decision engine — exist only as browser
JavaScript, and the flagship WhatsApp agent has not been started. The forecasting model has
not been trained, and its training set cannot be built until the collector has been running
for weeks.

**One line, if you only read one:** the plumbing is right, the data tap is barely on, and the
middle of the product is missing. Turn the tap on today; build the economics next.
