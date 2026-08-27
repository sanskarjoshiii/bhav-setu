"""Bulk-pull 3+ years of daily prices AND arrivals from CEDA, many crops, many districts.

    python scripts/fetch_ceda_bulk.py --from 2022-01-01          # the default job
    python scripts/fetch_ceda_bulk.py --districts Pune Nashik    # just two
    python scripts/fetch_ceda_bulk.py --crops onion tomato mango
    python scripts/fetch_ceda_bulk.py --dry-run                  # show the plan, fetch nothing

Why this exists rather than `ingestion/ceda.py`. That module pulls ONE commodity
(the `commodity_id` pinned in config) straight into Postgres. This one walks the
whole catalogue across every district and writes a CSV, which matters for two
practical reasons: it needs no database, so the pull can run while Postgres is
down; and its output is exactly the shape `sources.yaml → csv_backfill` already
expects, so the cleaning, entity-resolution and upsert path that is already
tested does not change at all.

**Granularity is district, not market.** CEDA aggregates a district's market
yards into one daily row. So one (district, crop) pair is one series, and the
district name is written as the mandi name. That is a real limitation and it is
better stated than hidden: the model learns district-level price dynamics, and
the compare page's market-level economics sits on top of it as arithmetic.

Everything is cached to disk per (endpoint, district, crop, window). Re-running
after a throttle, a Ctrl-C or a dropped connection costs nothing already
fetched — which is the whole reason a multi-hour pull is survivable.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence

import _bootstrap  # noqa: F401  (sys.path side effect)

import httpx
import pandas as pd

from core import logging as log
from core.config import settings

_CFG = settings.sources.ceda
BASE_URL: str = str(_CFG.base_url)
PRICES_URL: str = BASE_URL + str(_CFG.prices_path)
QUANTITIES_URL: str = BASE_URL + str(_CFG.quantities_path)
STATE_ID: str = str(_CFG.state_id)
TIMEOUT: float = float(_CFG.http_timeout_seconds)
CACHE_DIR: Path = settings.path(*str(_CFG.cache_dir).split("/"))
OUT_PATH: Path = settings.path(*str(settings.sources.csv_backfill.path).split("/"))

COMMODITIES: dict[str, int] = {k: int(v) for k, v in _CFG.commodities.to_dict().items()}
DISTRICTS: dict[str, int] = {k: int(v) for k, v in _CFG.districts.to_dict().items()}

#: Ask for the WHOLE span in one request, and bisect only if that fails.
#:
#: This is the opposite of what `ingestion/ceda.py` does, and it was worth
#: measuring rather than assuming. Timed against the live API:
#:
#:     6-month daily window   →  10–18s  (39s under concurrency)
#:     12-month daily window  →   0.3s
#:     24-month daily window  →   0.3s
#:     68-month daily window  →  15s, 1,729 rows
#:
#: Short windows are *slower*, not faster — the per-request overhead dominates
#: and chunking multiplies it. Chunking a 5-year pull into six-month windows
#: turned 896 requests into 8,960 and a 40-minute job into a 16-hour one.
#: So: one window, and `_bisect_on_failure` handles the rare 504.
MAX_BISECT_DEPTH: int = 4

#: Concurrency. Probing showed 8 workers sustained without a throttle, but this
#: is someone else's public research server — 5 is fast enough and polite.
DEFAULT_WORKERS: int = 5
PAUSE_SECONDS: float = 0.25

CANONICAL_COLUMNS: list[str] = [
    "obs_date", "state", "district", "mandi", "commodity", "variety", "grade",
    "min_price", "max_price", "modal_price", "arrival_qtl",
]


@dataclass
class Stats:
    requests: int = 0
    cache_hits: int = 0
    failures: int = 0
    price_rows: int = 0
    qty_rows: int = 0
    merged_rows: int = 0
    per_series: dict[str, int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def bump(self, **kwargs: int) -> None:
        with self._lock:
            for key, value in kwargs.items():
                setattr(self, key, getattr(self, key) + value)


def _fetch_window(client: httpx.Client, url: str, kind: str, district_id: int,
                  commodity_id: int, start: date, end: date, stats: Stats,
                  depth: int = 0) -> list[dict[str, Any]]:
    """One window, bisecting if the server refuses the span.

    A 504 means "that was too much to compute", so halving is the right answer
    where a retry is not. Depth is capped so a genuinely empty series cannot
    turn into an exponential fan-out of requests.
    """
    rows, refused = _post(client, url, kind, district_id, commodity_id,
                          start, end, stats)
    if not refused or depth >= MAX_BISECT_DEPTH or (end - start).days < 60:
        return rows
    midpoint = start + (end - start) / 2
    left = _fetch_window(client, url, kind, district_id, commodity_id,
                         start, midpoint, stats, depth + 1)
    right = _fetch_window(client, url, kind, district_id, commodity_id,
                          midpoint + timedelta(days=1), end, stats, depth + 1)
    return left + right


def _cache_path(kind: str, district_id: int, commodity_id: int,
                start: date, end: date) -> Path:
    return CACHE_DIR / f"{kind}_{district_id}_{commodity_id}_{start}_{end}.json"


def _post(client: httpx.Client, url: str, kind: str, district_id: int,
          commodity_id: int, start: date, end: date,
          stats: Stats) -> tuple[list[dict[str, Any]], bool]:
    """One window from one endpoint. Returns (rows, server_refused_the_span)."""
    cached = _cache_path(kind, district_id, commodity_id, start, end)
    if cached.exists():
        try:
            stats.bump(cache_hits=1)
            return json.loads(cached.read_text(encoding="utf-8")), False
        except json.JSONDecodeError:
            cached.unlink(missing_ok=True)   # a half-written file from a Ctrl-C

    payload = {
        "state_id": STATE_ID,
        "commodity_id": str(commodity_id),
        "district_id": str(district_id),
        "calculation_type": "d",
        "start_date": str(start),
        "end_date": str(end),
    }
    backoff = [2.0, 6.0, 15.0]
    for attempt in range(len(backoff) + 1):
        try:
            response = client.post(url, json=payload, timeout=TIMEOUT)
            stats.bump(requests=1)
            if response.status_code == 200:
                body = response.json()
                rows = body if isinstance(body, list) else body.get("data", [])
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_text(json.dumps(rows), encoding="utf-8")
                time.sleep(PAUSE_SECONDS)
                return rows, False
            # 502/504 mean we asked for more than they will compute in one go.
            # A smaller window is the fix; retrying the same one is not.
            if response.status_code in (502, 504):
                log.warn("ceda_span_refused", district=district_id,
                         commodity=commodity_id, window=f"{start}..{end}",
                         status=response.status_code)
                return [], True
        except httpx.TimeoutException:
            # A client-side timeout on a long span is the same signal as a 504.
            if (end - start).days > 365:
                return [], True
        except httpx.TransportError:
            pass
        if attempt < len(backoff):
            time.sleep(backoff[attempt])
    stats.bump(failures=1)
    return [], False


def fetch_series(client: httpx.Client, district: str, district_id: int,
                 crop: str, commodity_id: int, start: date, end: date,
                 stats: Stats) -> pd.DataFrame:
    """Prices and arrivals for one (district, crop), merged on the date."""
    prices = _fetch_window(client, PRICES_URL, "prices", district_id, commodity_id,
                           start, end, stats)
    quantities = _fetch_window(client, QUANTITIES_URL, "qty", district_id, commodity_id,
                               start, end, stats)

    stats.bump(price_rows=len(prices), qty_rows=len(quantities))
    if not prices:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)

    price_frame = pd.DataFrame(prices)
    frame = price_frame[["t", "cmdty", "district", "p_min", "p_max", "p_modal"]].copy()

    if quantities:
        qty_frame = pd.DataFrame(quantities)[["t", "qty"]].drop_duplicates("t")
        frame = frame.merge(qty_frame, on="t", how="left")
    else:
        frame["qty"] = pd.NA

    out = pd.DataFrame({
        "obs_date": pd.to_datetime(frame["t"]).dt.date,
        "state": "Maharashtra",
        "district": district,
        "mandi": district,          # district granularity — see the module docstring
        "commodity": frame["cmdty"],
        "variety": "",
        "grade": "",
        "min_price": pd.to_numeric(frame["p_min"], errors="coerce"),
        "max_price": pd.to_numeric(frame["p_max"], errors="coerce"),
        "modal_price": pd.to_numeric(frame["p_modal"], errors="coerce"),
        "arrival_qtl": pd.to_numeric(frame["qty"], errors="coerce"),
    })
    out = out.dropna(subset=["modal_price"])
    out = out[out["modal_price"] > 0].drop_duplicates(subset=["obs_date"])
    stats.per_series[f"{crop}@{district}"] = len(out)
    stats.bump(merged_rows=len(out))
    return out[CANONICAL_COLUMNS]


def run(districts: dict[str, int], crops: dict[str, int], start: date, end: date,
        workers: int) -> pd.DataFrame:
    stats = Stats()
    jobs = [(d, di, c, ci) for d, di in districts.items() for c, ci in crops.items()]
    total = len(jobs)
    print(f"  {total} series x 2 endpoints = {total * 2:,} requests "
          f"(one window each; bisects only if the server refuses the span)\n")

    frames: list[pd.DataFrame] = []
    done = 0
    with httpx.Client(headers={"Content-type": "application/json"}) as client:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(fetch_series, client, d, di, c, ci, start, end, stats): (c, d)
                for d, di, c, ci in jobs
            }
            for future in as_completed(futures):
                crop, district = futures[future]
                done += 1
                try:
                    frame = future.result()
                except Exception as exc:                      # noqa: BLE001
                    log.warn("ceda_series_failed", crop=crop, district=district,
                             error=f"{type(exc).__name__}: {exc}")
                    continue
                if not frame.empty:
                    frames.append(frame)
                marker = "·" if frame.empty else "✓"
                print(f"  [{done:>4}/{total}] {marker} {crop:<18}{district:<14}"
                      f"{len(frame):>6} rows", flush=True)

    print(f"\n  requests {stats.requests:,}   cache hits {stats.cache_hits:,}   "
          f"failures {stats.failures}")
    if not frames:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)
    return pd.concat(frames, ignore_index=True)


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _select(names: Sequence[str] | None, catalogue: dict[str, int], label: str) -> dict[str, int]:
    if not names:
        return dict(catalogue)
    wanted = {n.strip().lower() for n in names}
    chosen = {k: v for k, v in catalogue.items() if k.lower() in wanted}
    unknown = wanted - {k.lower() for k in chosen}
    if unknown:
        raise SystemExit(
            f"⛔ unknown {label}: {sorted(unknown)}\n"
            f"   available: {', '.join(sorted(catalogue))}"
        )
    return chosen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bulk CEDA history pull → CSV.")
    parser.add_argument("--from", dest="start", type=_parse_date,
                        default=date.today() - timedelta(days=365 * 3 + 30))
    parser.add_argument("--to", dest="end", type=_parse_date, default=date.today())
    parser.add_argument("--districts", nargs="+", default=None)
    parser.add_argument("--crops", nargs="+", default=None)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--out", default=None, help=f"default {OUT_PATH}")
    parser.add_argument("--append", action="store_true",
                        help="merge into the existing CSV instead of replacing it")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    districts = _select(args.districts, DISTRICTS, "district")
    crops = _select(args.crops, COMMODITIES, "crop")
    out_path = Path(args.out) if args.out else OUT_PATH

    print(f"\nCEDA bulk pull   {args.start} → {args.end}   "
          f"({(args.end - args.start).days / 365.25:.1f} years)")
    print(f"  districts  {len(districts)}: {', '.join(sorted(districts))}")
    print(f"  crops      {len(crops)}: {', '.join(sorted(crops))}")
    print(f"  cache      {CACHE_DIR}")
    print(f"  output     {out_path}\n")

    if args.dry_run:
        print("  --dry-run: nothing fetched.\n")
        return 0

    matrix = run(districts, crops, args.start, args.end, args.workers)
    if matrix.empty:
        print("\n⛔ nothing came back. Check connectivity to "
              f"{BASE_URL} and re-run — the cache makes a retry cheap.")
        return 1

    if args.append and out_path.exists():
        existing = pd.read_csv(out_path, parse_dates=["obs_date"])
        existing["obs_date"] = existing["obs_date"].dt.date
        matrix = pd.concat([existing, matrix], ignore_index=True)

    matrix = (matrix
              .drop_duplicates(subset=["obs_date", "mandi", "commodity"], keep="last")
              .sort_values(["commodity", "district", "obs_date"])
              .reset_index(drop=True))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    matrix.to_csv(out_path, index=False)

    span = pd.to_datetime(matrix["obs_date"])
    print(f"\n  ✅ {len(matrix):,} rows → {out_path}")
    print(f"     {matrix['commodity'].nunique()} crops x "
          f"{matrix['district'].nunique()} districts")
    print(f"     {span.min().date()} .. {span.max().date()}")
    print(f"     arrivals present on {matrix['arrival_qtl'].notna().mean() * 100:.0f}% of rows")

    print("\n  rows per crop")
    for crop, count in matrix.groupby("commodity").size().sort_values(ascending=False).items():
        print(f"     {crop:<34}{count:>7,}")

    print(f"\n  Next:  python scripts/check_data_readiness.py --csv\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
