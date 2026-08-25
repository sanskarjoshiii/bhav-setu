"""Phase 1 — create the schema and seed the reference data.

    python scripts/init_db.py --force     # drop everything and rebuild
    python scripts/init_db.py             # refuses to drop; seeds only if empty

Seeds, all read from config/ and data/manual/ so nothing is hardcoded here:
  states       <- config/cost_model.yaml   (fee percentages)
  mandis       <- config/mandis.yaml
  commodities  <- config/crops.yaml        (+ aliases)
  festivals    <- data/manual/festivals.csv
  msp_schedule <- nothing; onion has no MSP. The table exists and stays empty.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import _bootstrap  # noqa: F401  (sys.path side effect)

from sqlalchemy import text
from sqlalchemy.engine import Connection

from core import logging as log
from core.config import crop_specs, settings
from core.db import get_conn
from core.errors import ConfigError

# One implementation, shared with Phase 2's fuzzy matcher: what we write here is
# exactly what entity resolution compares against later.
from ingestion.entity_resolution import normalise

SCHEMA_PATH: Path = settings.path("db", "schema.sql")
FESTIVALS_PATH: Path = settings.path("data", "manual", "festivals.csv")


# ──────────────────────────────────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────────────────────────────────

def table_names(conn: Connection) -> set[str]:
    rows = conn.execute(
        text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        )
    ).scalars().all()
    return set(rows)


def read_csv_rows(path: Path) -> Iterable[dict[str, str]]:
    """CSV reader that skips leading '#' comment lines."""
    if not path.exists():
        raise ConfigError(f"missing data file: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        lines = [line for line in fh if not line.lstrip().startswith("#")]
    if not lines:
        raise ConfigError(f"data file has no rows: {path}")
    yield from csv.DictReader(lines)


# ──────────────────────────────────────────────────────────────────────────
# schema
# ──────────────────────────────────────────────────────────────────────────

def drop_all(conn: Connection) -> int:
    """Drop the public schema wholesale. Only reachable with --force."""
    existing = table_names(conn)
    conn.execute(text("DROP SCHEMA public CASCADE"))
    conn.execute(text("CREATE SCHEMA public"))
    log.info("schema_dropped", tables=len(existing))
    return len(existing)


def create_schema(conn: Connection) -> int:
    if not SCHEMA_PATH.exists():
        raise ConfigError(f"missing schema file: {SCHEMA_PATH}")
    conn.execute(text(SCHEMA_PATH.read_text(encoding="utf-8")))
    created = table_names(conn)
    log.info("schema_created", tables=len(created), file=str(SCHEMA_PATH.name))
    return len(created)


# ──────────────────────────────────────────────────────────────────────────
# seeds
# ──────────────────────────────────────────────────────────────────────────

def seed_states(conn: Connection) -> int:
    """Fee percentages come from config/cost_model.yaml, never from code."""
    states_cfg = settings.cost_model.states.to_dict()
    fallback: dict[str, Any] = dict(states_cfg.get("_default", {}))
    count = 0
    for name, fees in states_cfg.items():
        if name.startswith("_"):
            continue
        merged = {**fallback, **dict(fees)}
        conn.execute(
            text(
                """
                INSERT INTO states (name, commission_pct, apmc_cess_pct, other_fees_pct)
                VALUES (:name, :commission_pct, :apmc_cess_pct, :other_fees_pct)
                ON CONFLICT (name) DO UPDATE SET
                    commission_pct = EXCLUDED.commission_pct,
                    apmc_cess_pct  = EXCLUDED.apmc_cess_pct,
                    other_fees_pct = EXCLUDED.other_fees_pct
                """
            ),
            {
                "name": name,
                "commission_pct": merged["commission_pct"],
                "apmc_cess_pct": merged["apmc_cess_pct"],
                "other_fees_pct": merged["other_fees_pct"],
            },
        )
        count += 1
    log.info("seeded", table="states", rows=count)
    return count


def seed_mandis(conn: Connection) -> int:
    mandis = settings.mandis.mandis
    if not mandis:
        raise ConfigError("config/mandis.yaml lists no mandis")
    count = 0
    for entry in mandis:
        row = entry.to_dict() if hasattr(entry, "to_dict") else dict(entry)
        state_id = conn.execute(
            text("SELECT id FROM states WHERE name = :name"), {"name": row["state"]}
        ).scalar_one_or_none()
        if state_id is None:
            raise ConfigError(
                f"mandi '{row['name']}' references state '{row['state']}' which is not in "
                f"config/cost_model.yaml → states. Add it there first."
            )
        conn.execute(
            text(
                """
                INSERT INTO mandis (name, normalised_name, district, state_id, lat, lon)
                VALUES (:name, :normalised_name, :district, :state_id, :lat, :lon)
                ON CONFLICT (normalised_name, district, state_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    lat  = EXCLUDED.lat,
                    lon  = EXCLUDED.lon
                """
            ),
            {
                "name": row["name"],
                "normalised_name": normalise(row["name"]),
                "district": row["district"],
                "state_id": state_id,
                "lat": row["lat"],
                "lon": row["lon"],
            },
        )
        count += 1
    log.info("seeded", table="mandis", rows=count)
    return count


def seed_commodities(conn: Connection) -> tuple[int, int]:
    """One row per crop in config/crops.yaml, plus its aliases."""
    crops = crop_specs()
    n_commodities = 0
    n_aliases = 0
    for crop_name, spec in crops.items():
        # "green_chilli" -> "Green Chilli". The display name reaches the audit
        # report, the API and a farmer's screen, so it may not carry our
        # internal key's underscore.
        display_name = crop_name.replace("_", " ").title()
        commodity_id = conn.execute(
            text(
                """
                INSERT INTO commodities
                    (name, variety, crop_group, perishability_class, shelf_life_days, msp_applicable)
                VALUES (:name, :variety, :crop_group, :perishability_class,
                        :shelf_life_days, :msp_applicable)
                ON CONFLICT (name, variety) DO UPDATE SET
                    crop_group          = EXCLUDED.crop_group,
                    perishability_class = EXCLUDED.perishability_class,
                    shelf_life_days     = EXCLUDED.shelf_life_days,
                    msp_applicable      = EXCLUDED.msp_applicable
                RETURNING id
                """
            ),
            {
                "name": display_name,
                "variety": "",
                "crop_group": spec.get("crop_group"),
                "perishability_class": spec.get("perishability_class"),
                "shelf_life_days": spec.get("shelf_life_days"),
                "msp_applicable": bool(spec.get("msp_applicable", False)),
            },
        ).scalar_one()
        n_commodities += 1

        aliases = list(spec.get("aliases", []))
        aliases.append(display_name)
        for alias in dict.fromkeys(aliases):          # de-dupe, keep order
            conn.execute(
                text(
                    """
                    INSERT INTO commodity_aliases (alias, normalised_alias, commodity_id)
                    VALUES (:alias, :normalised_alias, :commodity_id)
                    ON CONFLICT (alias) DO UPDATE SET
                        normalised_alias = EXCLUDED.normalised_alias,
                        commodity_id     = EXCLUDED.commodity_id
                    """
                ),
                {
                    "alias": alias,
                    "normalised_alias": normalise(alias),
                    "commodity_id": commodity_id,
                },
            )
            n_aliases += 1
    log.info("seeded", table="commodities", rows=n_commodities, aliases=n_aliases)
    return n_commodities, n_aliases


def seed_festivals(conn: Connection) -> int:
    count = 0
    for row in read_csv_rows(FESTIVALS_PATH):
        fest_date = _parse_date(row["fest_date"], FESTIVALS_PATH)
        effect = int(row.get("demand_effect", 1) or 1)
        conn.execute(
            text(
                """
                INSERT INTO festivals (fest_date, name, demand_effect)
                VALUES (:fest_date, :name, CAST(:demand_effect AS jsonb))
                ON CONFLICT (fest_date) DO UPDATE SET
                    name = EXCLUDED.name,
                    demand_effect = EXCLUDED.demand_effect
                """
            ),
            {
                "fest_date": fest_date,
                "name": row["name"].strip(),
                "demand_effect": json.dumps({"vegetable": effect}),
            },
        )
        count += 1
    log.info("seeded", table="festivals", rows=count)
    return count


def seed_msp(conn: Connection) -> int:
    """Onion has no MSP. Nothing is inserted — but the caller must not treat that
    as a failure, and downstream MSP checks must handle 'not applicable' cleanly."""
    applicable = [
        name for name, spec in crop_specs().items()
        if bool(spec.get("msp_applicable", False))
    ]
    log.info("seeded", table="msp_schedule", rows=0, msp_applicable_crops=applicable or "none")
    return 0


def _parse_date(value: str, path: Path) -> date:
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ConfigError(f"bad date '{value}' in {path}; expected YYYY-MM-DD") from exc


# ──────────────────────────────────────────────────────────────────────────
# entry point
# ──────────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create and seed the Bhav Setu database.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="drop every existing table first (required if the schema already exists)",
    )
    args = parser.parse_args(argv)

    with get_conn() as conn:
        existing = table_names(conn)
        if existing and not args.force:
            print(
                f"⛔ {len(existing)} table(s) already exist. "
                f"Re-run with --force to drop and recreate:\n"
                f"   python scripts/init_db.py --force",
                file=sys.stderr,
            )
            return 1
        if existing:
            drop_all(conn)
        create_schema(conn)

        n_states = seed_states(conn)
        n_mandis = seed_mandis(conn)
        n_commodities, n_aliases = seed_commodities(conn)
        n_festivals = seed_festivals(conn)
        seed_msp(conn)

    print(
        "\n✅ database ready\n"
        f"   states       {n_states}\n"
        f"   mandis       {n_mandis}\n"
        f"   commodities  {n_commodities} (aliases {n_aliases})\n"
        f"   festivals    {n_festivals}\n"
        f"   msp_schedule 0 (onion has no MSP — expected)\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
