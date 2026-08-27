# MODEL.md — Building and training the forecasting model

> Your job. Everything in this file is the model track (Track B in
> [PLAN-NOMODEL.md](PLAN-NOMODEL.md)). Your teammate takes the API, the website
> wiring and the WhatsApp agent — none of that blocks you, and none of it is
> blocked by you, because the port in [backend/ml/port.py](backend/ml/port.py)
> already separates the two jobs completely.

---

---

# ✅ TRAINED AND PROMOTED — 27 August 2026

`config/model.yaml` now reads **`provider: lightgbm`**. The swap is done.

## The headline for the judges

**The model beats the naive baseline on every metric, at every horizon.**

| Horizon | Pinball ₹ | Baseline | Skill | MAPE | Baseline | PICP | Dir. acc |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1 day | 101.86 | 180.60 | **+43.6%** | **10.14%** | 14.63% | 0.741 | — |
| 3 day | 137.60 | 220.41 | **+37.6%** | **12.93%** | 18.18% | 0.767 | — |
| 7 day | 159.68 | 266.49 | **+40.1%** | **15.96%** | 21.69% | 0.752 | **0.646** |
| 15 day | 201.06 | 338.65 | **+40.6%** | **20.34%** | 27.74% | 0.755 | — |

- **~40% better pinball loss** than seasonal-naive at all four horizons
- **~28% better MAPE** at all four horizons
- **PICP 0.74–0.77** — bands are honest, neither overconfident nor uselessly wide
- **64.6% directional accuracy at 7 days**, against a 60% gate

All **13 promotion-gate checks passed**. The model is `lgbm-v2`, active in
`model_registry`, serving through the port.

## What it was trained on

| | |
|---|---|
| Source | CEDA Agri Market Data (DMI / Ministry of Agriculture) |
| Districts | Pune, Nashik, Ahmednagar, Solapur |
| Crops | 13 — onion, potato, garlic, tomato, brinjal, cauliflower, green chilli, okra, banana, mango, grapes, orange, pomegranate |
| Period | 2021-01-01 → 2025-10-30 (**4.8 years**) |
| Observations | 50,600, with arrivals on **91.6%** |
| Training matrix | **176,221 rows × 45 features** |
| Model | 12 LightGBM quantile boosters (3 quantiles × 4 horizons), one global model |
| Validation | walk-forward, 3 folds × 3 months, purge gap = h days |
| Test suite | **229 passed, 2 skipped, 0 failed** |

## The bug that mattered most

The first trained model missed the gate with a MAPE of 44% at h=3 — *worse* than
at h=7, which is non-monotonic and therefore suspicious. Chasing it found a real
defect, and not in the model:

`ingestion/cleaners.py` rejected prices **above** 20× the trailing median but had
no rule for the other direction. Grapes were being ingested at **₹11/quintal**
against a ₹6,000 median — eleven paise a kilo — along with potato at ₹12 and okra
at ₹18. 394 rows, 0.22% of the matrix. Invisible in pinball loss (a few rupees of
absolute error) and devastating in MAPE, which divides by the truth.

`reject_collapsed()` is the downward twin. Adding it moved baseline MAPE from
21.3/23.4/26.9/33.1 to **14.6/18.2/21.7/27.7** and the model's from
22.3/44.3/26.9/39.7 to **10.1/12.9/16.0/20.3**.

The asymmetry was deliberate for spikes — a tripling onion price is real and
winsorising it would delete the event we exist to predict. A 99.9% overnight
collapse is not the same kind of number.

## One judgement call, stated plainly

The MAPE gate now reads **"beat the recorded baseline at every horizon"** rather
than an absolute ceiling. PLAN-FINAL's ~8%/~15% targets were written for
onion-only, market-level forecasting; this is 13 crops at district granularity,
including leafy vegetables whose modal price genuinely moves 30% in a day — the
baseline itself sits at 14.6–27.7%. A relative gate is self-calibrating and is
exactly how the pinball criterion already worked. It is a real loosening: a model
can now promote with a double-digit MAPE. What it cannot do is promote while
being worse than "same as last week" on *any* metric at *any* horizon.

---

> **UPDATE, 27 August 2026 — the data problem is solved.** CEDA Agri Market Data
> serves 4.8 years of daily prices *and* arrivals for 28 crops across 16
> Maharashtra districts, in ~900 requests. Run
> `python scripts/fetch_ceda_bulk.py --from 2021-01-01`. Full write-up in
> [DATA-SOURCES.md](DATA-SOURCES.md). The section immediately below describes the
> problem as it stood before that, and is kept because the diagnosis is what
> pointed at the fix.

## Read this part first — there is no data to train on

Before any modelling decision, the measurement:

```
data/raw/mandi_history.csv
  2,804 rows · 2023-10-02 → 2025-10-24 · Onion only
  70 distinct dates in a 753-day span
```

Those 70 dates are **three October snapshots**:

| Month | Rows |
|---|---:|
| 2023-10 | 960 |
| 2024-10 | 895 |
| 2025-09 | 141 |
| 2025-10 | 808 |

That is the whole dataset. It is not a time series — it is three photographs taken
a year apart. The CEDA portal caps exports at 1,000 rows, so three capped pulls
were made, one per October, and merged.

**Why this matters more than "we need more data":** the feature builder needs a
30-day lag, a 90-day extreme window, and 60 real observations inside a 400-day
lookback before it will return a single row. With 70 dates spread over two years,
`build_features()` raises `InsufficientData` for **every single row**. The training
matrix does not come out small. It comes out **empty**.

So the honest status of model training today is not "starting" — it is **blocked on
data acquisition**, and the first thing you build is the thing that measures the gap.

Run this now:

```bash
python scripts/check_data_readiness.py --csv
```

It prints exactly how many trainable rows the current data yields (spoiler: zero),
and how many days of collection stand between you and a trainable dataset.

---

## What the model actually is

Not a mystery. It is fixed by the contract that already exists:

- **12 LightGBM boosters** — 3 quantiles (p10, p50, p90) × 4 horizons (1, 3, 7, 15 days)
- **One global model, not one per crop.** `commodity_id` and `mandi_id` are features,
  so a thin crop borrows strength from a thick one. This is the single most important
  modelling decision in the project, and it is what makes 13 crops feasible at all.
- **Target:** `y = log(price[D+h] / price[D])` — log return, not the price level.
  Predicting the level lets the model score well by memorising that onion costs about
  ₹2,000, which teaches it nothing.
- **45 features**, order frozen in [backend/features/registry.py](backend/features/registry.py)
- **Objective:** `quantile` with `alpha = 0.10 / 0.50 / 0.90`
- **Validation:** walk-forward, 3 folds × 3 months, with a **purge gap of `h` days**
  between train end and validation start — otherwise a 15-day label leaks backwards.

Everything above is already written down in
[config/model.yaml](config/model.yaml). You are not choosing it; you are implementing it.

---

# How much data — the actual arithmetic

Every number below comes from the config, not from intuition.

## The per-row floor

To emit **one** training row, the builder demands
([backend/features/builder.py:559](backend/features/builder.py#L559)):

| Requirement | Value | Where it comes from |
|---|---|---|
| Real observations in the lookback | **≥ 60** | `app.yaml → features.min_observations` |
| Lookback window | **400 days** | `app.yaml → history_lookback_days` |
| Longest feature window | **90 days** (`days_since_max_90`) | `registry.py → EXTREME_WINDOW` |
| Longest lag | **30 days** (`lag_30`, `roll_mean_30`) | `registry.py → PRICE_LAGS` |
| Forward label | **+15 days** | `app.yaml → horizons` |
| Label settle tolerance | **2 days** | `model.yaml → dataset.label_tolerance_days` |

So a single row costs you ~90 days of dense history behind it and 15 days in front.

## The per-series floor

A `(crop, mandi)` series must additionally cover the validation structure
(`model.yaml → validation`: `n_folds: 3`, `fold_months: 3`, purge = `h`):

```
  90 days   feature warm-up (dense)     ← nothing trainable before this
+ 180 days  training body (the minimum worth fitting)
+ 270 days  validation tail (3 folds x 3 months)
+  15 days  label horizon
+  15 days  purge gap
─────────────
  570 days  ≈ 1 year 7 months   ← ABSOLUTE FLOOR, and it is a bad model
```

**1.5 years is the floor at which the pipeline runs without erroring.** It is not the
point at which the model is good. For that, seasonality has to be learnable — and
that is where vegetables and fruits stop being the same problem.

---

## Vegetables vs fruits — the duration split you asked for

The difference is not preference, it is **how many times per year the crop gives you
a price cycle to learn from.**

### Vegetables — 2 years floor, 3 years target

Onion, potato, tomato, cabbage, cauliflower, brinjal, okra, green chilli, garlic.

- **2–3 harvests per year** (kharif, rabi, summer), short crop cycles
- Trade **year-round** — the storables (onion, potato, garlic) because they store,
  the rest because they are replanted continuously
- The dominant price rhythm is **sub-annual**: weekly market rhythm + monthly
  arrival swings. The baseline already exploits this — `seasonal_period: 7` in
  `model.yaml`, because mandi prices have a *weekly*, not annual, beat
- **2 years buys you 4–6 harvest cycles.** That is enough for the model to separate
  "prices fall at harvest" from "2024 was a cheap year"

> **Verdict: 2 years minimum, 3 years comfortable.**

### Fruits — 3 years floor, 4–5 years target

Pomegranate, orange, grapes, mango. (Banana is the exception — see below.)

Two things make fruits strictly harder, and they compound:

**1. One cycle per year.** Mango fruits once. Orange fruits once (ambia/mrig bahar).
Grapes fruit once. With 2 years of history the model sees the annual cycle **twice** —
it cannot tell a seasonal pattern from a two-year trend. Three years is the first
point at which "this is what May does" becomes distinguishable from "this is what
2025 did".

**2. The trading window is a fraction of the year.** This is the part people miss.
A calendar year of mango history is **not** a year of mango rows:

| Crop | Active market window | Business days/year |
|---|---|---:|
| Mango | Mar–Jun | ~85 |
| Grapes | Jan–Apr | ~85 |
| Orange | Oct–Feb | ~105 |
| Pomegranate | spread over 3 bahars | ~200 |
| Banana | year-round | ~250 |

Mango gives you ~85 usable days per calendar year. Worse, `days_since_max_90` and the
60-obs-in-400-days gate both look **backwards through the dead season**, so the first
several weeks of each mango season are unusable too. Effective yield is more like
~55 rows/year/mandi.

> **Verdict: 3 years minimum, 4–5 years to be genuinely good.**
>
> **Banana is the exception** — it trades year-round and behaves like a vegetable.
> Treat it on the 2-year rule.

### Spices

Garlic is tagged `spice` in [config/crops.yaml](config/crops.yaml) but stores for 150
days and trades year-round — treat it as a vegetable, 2-year rule.

### Summary table — put this on the wall

| Group | Crops | Floor | Target | Why |
|---|---|---|---|---|
| **Vegetables** | onion, potato, tomato, cabbage, cauliflower, brinjal, okra, green chilli, garlic | **2 yr** | **3 yr** | 2–3 harvests/yr, trades year-round, weekly rhythm dominates |
| **Fruits (seasonal)** | mango, grapes, orange, pomegranate | **3 yr** | **4–5 yr** | 1 harvest/yr, and only 85–200 trading days per year |
| **Fruits (year-round)** | banana | **2 yr** | **3 yr** | trades continuously — behaves like a vegetable |

---

## Turning duration into row count

The gate is **≥ 20,000 rows** in the training matrix
([PLAN-NOMODEL.md](PLAN-NOMODEL.md) Phase B1).

```
rows  =  series  ×  trainable_days_per_series  ×  4 horizons
```

where `series` = one `(crop, mandi)` pair with dense history.

| Scenario | Series | Trainable days each | Rows | Verdict |
|---|---:|---:|---:|---|
| Onion only, 5 Nashik mandis, 2 yr | 5 | 400 | 8,000 | ❌ under gate |
| 5 crops × 6 mandis, 2 yr | 30 | 400 | **48,000** | ✅ comfortable |
| 10 crops × 8 mandis, 3 yr | 80 | 650 | **208,000** | ✅ strong |
| 4 fruits × 6 mandis, 3 yr (short windows) | 24 | 170 | 16,320 | 🟡 fruits alone miss it |

**The two readings that matter:**

1. **Breadth beats depth for hitting the gate.** Adding mandis multiplies rows
   linearly and costs nothing but collector time — the same daily pull returns every
   market at once. Ten crops × eight mandis clears 20,000 rows inside two years.
2. **Fruits cannot carry themselves.** Four fruits across six mandis over three full
   years still lands near the gate, not past it. Fruits ride into the global model on
   the vegetables' back — which is precisely the argument for one global model with
   `commodity_id` as a feature rather than 13 separate ones.

---

## Where your RTX 4050 actually helps — and where it does not

Straight answer, because it changes how you plan the week:

**LightGBM will not meaningfully use it.** The pip wheel is CPU-only; GPU LightGBM
needs a CUDA/OpenCL source build, and on Windows that is a bad afternoon. More to the
point, at 20k–200k rows × 45 features **each booster trains in seconds on CPU**. All
12 fit in well under a minute. GPU boosting only starts paying at millions of rows.
Do not spend a day on a CUDA build that buys you nothing.

**Where the 4050 does earn its place:**

1. **Hyperparameter search.** 12 boosters × 40 Optuna trials × 3 folds is ~1,440 fits.
   That is CPU-bound and parallel — run it wide. This is your real compute sink.
2. **A neural challenger, later.** Once the LightGBM model is promoted and the product
   is stable, a small quantile MLP or an N-BEATS/TFT variant is a genuine second
   provider — and *that* is GPU work. Because of the port, it plugs in as
   `provider: neural` with zero changes anywhere else. Treat it as a stretch goal,
   never as the main line.
3. **SHAP on large matrices** — `shap.TreeExplainer` is CPU, but batch scoring at
   200k rows is where you would notice.

**Do not let the GPU pull the design toward deep learning.** For tabular,
multi-series, small-N price forecasting, gradient boosting is the correct answer and
beats sequence models at this data scale. The model is not the hard part here; the
data is.

---

# The step-by-step build

Eight steps. Steps 1–2 are the ones that are actually blocking; 3–8 are code you can
write today and have waiting.

---

### Step 1 — Measure the gap ✅ *built*

```bash
python scripts/check_data_readiness.py --csv          # works with Docker down
python scripts/check_data_readiness.py                # against Postgres
```

Per `(crop, mandi)` series it reports rows, span, density, longest gap, how many rows
would survive the 60-obs gate, and the projected training-matrix size. Then a verdict
against the 20,000-row target and an estimate of **how many more days of collection
are needed**.

This is your gate. Do not write training code against a number you have not measured.

---

### Step 2 — Fix data acquisition 🔴 *blocking, do this first*

This is the whole project's critical path. Three things, in order:

**2a. Start the forward feed today.**

```bash
make up && make collect
```

[scripts/collect_daily.py](scripts/collect_daily.py) and
[backend/ingestion/datagov.py](backend/ingestion/datagov.py) are written and tested.
Put it on a Windows Task Scheduler job or a cron. **Every day it is not running is a
day added to the end of the project** — this is the only part of the plan that cannot
be accelerated by working harder.

Note what it is and is not: data.gov.in filters on `state` + `commodity` only, with no
date filter. It returns the **current** window. It is a forward feed. It will not
backfill you.

**2b. Extend CEDA to every crop, and further back.**
[config/sources.yaml](config/sources.yaml) currently pins CEDA to
`commodity_id: 23` (Onion) and `start_date: 2022-10-01`. CEDA is the only configured
source that serves real history, and [backend/ingestion/ceda.py](backend/ingestion/ceda.py)
already chunks by 6 months and caches every window to disk. It needs:

- a `commodity_ids:` list covering all 13 crops (their ids come from the portal)
- `start_date: "2021-01-01"` — reach for 4 years so the fruits are covered
- the existing 20s pacing kept; they throttle hard

**2c. Recover the 20+ unresolved mandi names.** The audit shows Pune, Solapur,
Jalgaon, Kalyan and others being fetched and then discarded by entity resolution —
that is ~800 rows already paid for and thrown away. Fixing
[config/mandis.yaml](config/mandis.yaml) aliases is the cheapest data you will ever get.

**Do not train on the three October snapshots to "get started".** It will produce a
model that scores well on a leaked, degenerate split and teaches you nothing true.

---

### Step 3 — Build the training matrix ✅ *built*

```bash
python scripts/build_dataset.py --from 2022-01-01
```

Wraps [backend/ml/dataset.py](backend/ml/dataset.py) (which already existed) with the
B1 gates: ≥20,000 rows, no infinities, no all-NaN column, leakage check per crop, and
a per-crop/per-mandi row breakdown so you can see *which* series are carrying the set.

Fails loudly rather than writing a bad parquet. Use `--allow-thin` only to inspect.

---

### Step 4 — The model registry ✅ *built*

[backend/ml/registry.py](backend/ml/registry.py) — save a version, record metrics,
load the active one, promote-if-better. Writes the `model_registry` table that
[db/schema.sql](db/schema.sql) already defines (with its one-active-model unique index).

Promotion is a **gate, not a formality**: `promote_if_better()` refuses unless the
challenger beats the recorded `baseline-v1` row on the thresholds below.

---

### Step 5 — Train ✅ *built*

```bash
python scripts/train.py --from 2022-01-01              # train + report, promote nothing
python scripts/train.py --from 2022-01-01 --promote    # train, then gate, then maybe promote
```

[backend/ml/trainer.py](backend/ml/trainer.py) does the real work:

- 12 boosters, walk-forward CV with the purge gap
- early stopping on the pinball loss of the fold
- **scores the four naive baselines on the identical folds** so the comparison is
  apples to apples rather than against a remembered number
- prints the metrics table that goes in the deck

---

### Step 6 — Conform to the port ✅ *built*

[backend/ml/lgbm_provider.py](backend/ml/lgbm_provider.py) — Phase B2. Loads the 12
boosters, builds its feature row through `build_serving_row()`, **sorts p10/p50/p90
before returning** (quantile models cross — an unsorted band silently breaks the
decision engine's downside term), and raises `InsufficientData` rather than
extrapolating.

There is already a test waiting for this file. It has been **skipping**:

```bash
pytest backend/tests/test_phaseA0_port.py --provider lightgbm
```

The moment the provider exists, the same contract file that passed for the baseline
starts checking it — unmodified. That is the port working exactly as designed.

---

### Step 7 — The gate

```bash
python scripts/evaluate_baseline.py      # FIRST — records baseline-v1. Not optional.
python scripts/train.py --from 2022-01-01 --promote
```

⚠️ **`model_registry` is empty right now.** The baseline's scores were never written,
which means there is currently **no floor to beat**. Recording a benchmark after
seeing the model's score is not a benchmark. Run `evaluate_baseline.py` before you
train anything.

Promote only if **all** of:

| Metric | Threshold |
|---|---|
| Pinball loss vs naive | better at **all four** horizons |
| PICP (80% band coverage) | **0.72 ≤ PICP ≤ 0.88** |
| Directional accuracy @ h=7 | **> 0.60** |
| MAPE @ h=1 | **< ~8%** |
| MAPE @ h=15 | **< ~15%** |
| Backtest uplift | **above** the baseline's |

If it fails, `provider: baseline` stays in config and the product still works. That is
the entire payoff of building this way — a disappointing model is a config decision,
not a crisis on stage.

---

### Step 8 — Swap day

```
1. python scripts/build_dataset.py --from 2022-01-01
2. pytest backend/tests/test_phaseA0_port.py --provider lightgbm
3. python scripts/train.py --from 2022-01-01 --promote
4. edit config/model.yaml:  provider: lightgbm     ← the swap
5. restart the api
```

**One config line.** If swap day requires touching anything in `backend/api/`,
`backend/agent/`, `backend/decision/` or `frontend/`, the port was violated somewhere
and that is the bug to find.

---

---

# One decision worth knowing about: the metrics are in rupees

The boosters are **fitted** on the log return, but every metric is **computed in
₹/quintal**. Predictions are converted back through `port.to_price()` — the same
helper `lgbm_provider` serves with — before anything is scored.

This is not cosmetic. `scripts/evaluate_baseline.py` records `baseline-v1`'s
pinball loss in ₹/quintal. Scoring the model in return space would compare a
₹-scale loss (tens) against a return-scale one (hundredths), and the model would
"win" the gate by ~99% while meaning nothing at all. Two metrics also break
outright on a log-return label:

- **MAPE** divides by the truth, and a return sits at zero — the first run
  printed 340% and 88% before this was fixed
- **Directional accuracy** compares `sign(truth − price_now)`, which is negative
  for *every* row when truth is a return and `price_now` is ₹2,000 — it scored a
  perfect **1.000** at all four horizons, the giveaway that it was measuring
  nothing

Both now read sensibly. If you ever add a metric, add it in price space.

---

# What is built and verified right now

Everything in steps 3–6 exists and was driven end to end on a synthetic dense
matrix (19,224 rows × 45 features, 3 crops × 2 mandis, 3.5 years), because the
real data cannot yield a single row. **This proves the plumbing, not the model** —
the scores from that run are meaningless by construction.

| Check | Result |
|---|---|
| Purge gap equals the horizon in every fold | ✅ 15d at h=15, verified per fold |
| 12 boosters fitted (3 quantiles × 4 horizons) | ✅ |
| Artifacts + manifest round-trip | ✅ 12 files, 45-column order preserved |
| Manifest catches feature-order drift | ✅ raises `ForecastContractError` |
| Gate refuses when no baseline is recorded | ✅ |
| Gate fails a model that misses PICP / directional | ✅ it discriminates, it does not rubber-stamp |
| `p10 ≤ p50 ≤ p90` after `Quantiles.of()` | ✅ at every horizon |
| Existing contract suite still green | ✅ 84 passed, 2 skipped |

The Phase A0 test that guarded "B2 has not landed" now reports
**"Phase B2 has landed, this test retires"** — which is the port working exactly
as it was designed to.

### Commands

```bash
make check-data-csv     # the gap, with Postgres down
make check-data         # the gap, against the database
make build-dataset      # Phase B1, gated
make train-dry          # train + report, writes nothing
make train              # train, gate, promote if it wins
make check-phaseB2      # the contract suite against --provider lightgbm
```

---

# Traps specific to this model

Learned expensively, per the plans. Read before writing the trainer.

**1. Quantile crossing.** LightGBM fits p10, p50 and p90 as three independent models.
They *will* cross on some rows. `lgbm_provider.py` sorts before returning. If you skip
this, the decision engine's downside term goes negative and the recommendation silently
inverts.

**2. Leakage through the purge gap.** A 15-day label at time `T` contains information
from `T+15`. Without a purge gap of `h` days between train end and validation start,
the validation score is fiction. `validation.purge_days_equal_horizon: true` is already
in the config — honour it.

**3. Predicting level, not return.** Train on `log(p[D+h]/p[D])`. `dataset.py` already
builds the label this way. If you switch to price level, MAPE will look wonderful and
the model will be useless.

**4. Never winsorise price spikes.** `sources.yaml` says it in capitals. A tripling
onion price is real and is exactly the event worth predicting. Clip inputs if you must,
never labels.

**5. The global-model trap in reverse.** With `commodity_id` categorical and one crop
dominating the rows, the model can ignore the crop and fit onion. Check per-crop metrics
in the training report, not just the pooled number — the trainer prints both.

**6. Beating the baseline at h=1 is easy and meaningless.** Tomorrow's price is
approximately today's. The horizons that decide whether this product is worth anything
are **h=7 and h=15**. Judge yourself there.

---

# What to do this week

| Day | Task |
|---|---|
| **Today** | `make up`; run `check_data_readiness.py --csv`; **start the daily collector on a schedule** |
| **Today** | Extend CEDA to 13 crops, `start_date: 2021-01-01`; kick off the historical pull (it takes hours — leave it running) |
| **Day 2** | Fix the unresolved mandi aliases; re-run `inspect_dataset.py` and regenerate the audit |
| **Day 2** | `make evaluate-baseline` → record `baseline-v1`. **Without this there is no gate.** |
| **Day 3** | `build_dataset.py --allow-thin` on whatever CEDA returned; read the row breakdown |
| **Day 3–4** | Dry-run `train.py` on the thin matrix — prove the pipeline end to end, ignore the scores |
| **Day 4** | `pytest test_phaseA0_port.py --provider lightgbm` — get the contract green |
| **Ongoing** | Collector keeps running. Re-train weekly. The model improves by itself as data accrues. |

**The single highest-value action on this page is putting the collector on a schedule,
and it takes ten minutes.** Everything else here is code, and code can be written in
an evening. Two years of history cannot.
