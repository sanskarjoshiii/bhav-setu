"""Phase 1 acceptance: the schema exists and the reference data is seeded.

Run:  make check-phase1     (or: cd backend && pytest tests/test_phase1_schema.py)
Requires the database created by `python scripts/init_db.py --force`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text

from core.config import settings
from core.db import get_conn

pytestmark = pytest.mark.phase1

# The Round 1 subset from PLAN.md Phase 1.
EXPECTED_TABLES: set[str] = {
    "states",
    "mandis",
    "commodities",
    "commodity_aliases",
    "msp_schedule",
    "price_observations",
    "weather_daily",
    "shock_events",
    "festivals",
    "distance_cache",
    "forecasts",
    "model_registry",
    "farmers",
    "lots",
    "recommendations",
    "sale_reports",
    "transparency_scores",
    "bot_sessions",
    "ingestion_runs",
}


@pytest.fixture(scope="module")
def tables() -> set[str]:
    with get_conn() as conn:
        return set(
            conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            ).scalars().all()
        )


def scalar(sql: str, params: dict[str, Any] | None = None) -> Any:
    with get_conn() as conn:
        return conn.execute(text(sql), params or {}).scalar()


# ── schema ────────────────────────────────────────────────────────────────

def test_every_table_exists(tables: set[str]) -> None:
    missing = EXPECTED_TABLES - tables
    assert not missing, f"missing tables: {sorted(missing)}"


def test_price_observations_unique_key(tables: set[str]) -> None:
    cols = scalar(
        """
        SELECT string_agg(a.attname, ',' ORDER BY k.ord)
        FROM pg_constraint c
        JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord) ON TRUE
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
        WHERE c.conrelid = 'price_observations'::regclass AND c.contype = 'u'
        GROUP BY c.oid
        """
    )
    assert cols == "obs_date,mandi_id,commodity_id,variety,grade"


def test_price_observations_lookup_index() -> None:
    idx = scalar(
        "SELECT indexdef FROM pg_indexes "
        "WHERE tablename = 'price_observations' AND indexname = 'idx_po_lookup'"
    )
    assert idx is not None
    assert "commodity_id" in idx and "mandi_id" in idx and "obs_date DESC" in idx


def test_price_observations_has_quality_flags() -> None:
    cols = {
        row["column_name"]: row["is_nullable"]
        for row in _columns("price_observations")
    }
    for required in ("is_imputed", "suspect", "arrival_qtl", "source"):
        assert required in cols, f"price_observations.{required} missing"
    assert cols["source"] == "NO", "source must be NOT NULL"


def test_bot_sessions_shape() -> None:
    cols = {row["column_name"]: row["data_type"] for row in _columns("bot_sessions")}
    assert cols["phone_e164"] == "text"
    assert cols["state"] == "text"
    assert cols["context"] == "jsonb"
    assert "updated_at" in cols
    pk = scalar(
        "SELECT a.attname FROM pg_constraint c "
        "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey) "
        "WHERE c.conrelid = 'bot_sessions'::regclass AND c.contype = 'p'"
    )
    assert pk == "phone_e164"


def _columns(table: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        return [
            dict(row)
            for row in conn.execute(
                text(
                    "SELECT column_name, data_type, is_nullable "
                    "FROM information_schema.columns WHERE table_name = :t"
                ),
                {"t": table},
            ).mappings()
        ]


# ── seeded reference data ─────────────────────────────────────────────────

def test_five_mandis_seeded() -> None:
    configured = [m["name"] for m in settings.mandis.mandis]
    with get_conn() as conn:
        seeded = conn.execute(text("SELECT name FROM mandis ORDER BY name")).scalars().all()
    assert len(seeded) == 5, f"expected 5 mandis, found {len(seeded)}: {seeded}"
    assert sorted(seeded) == sorted(configured)


def test_mandis_have_coordinates_and_state() -> None:
    bad = scalar(
        "SELECT count(*) FROM mandis "
        "WHERE lat IS NULL OR lon IS NULL OR state_id IS NULL OR normalised_name = ''"
    )
    assert bad == 0


def test_state_fees_come_from_config() -> None:
    cfg = settings.cost_model.states["Maharashtra"]
    with get_conn() as conn:
        row = conn.execute(
            text(
                "SELECT commission_pct, apmc_cess_pct, other_fees_pct "
                "FROM states WHERE name = 'Maharashtra'"
            )
        ).mappings().one()
    assert row["commission_pct"] == Decimal(str(cfg["commission_pct"]))
    assert row["apmc_cess_pct"] == Decimal(str(cfg["apmc_cess_pct"]))
    assert row["other_fees_pct"] == Decimal(str(cfg["other_fees_pct"]))


def test_onion_seeded_with_at_least_five_aliases() -> None:
    with get_conn() as conn:
        commodity_id = conn.execute(
            text("SELECT id FROM commodities WHERE lower(name) = 'onion'")
        ).scalar_one()
        aliases = conn.execute(
            text("SELECT alias FROM commodity_aliases WHERE commodity_id = :c"),
            {"c": commodity_id},
        ).scalars().all()
    assert len(aliases) >= 5, f"onion has only {len(aliases)} aliases: {aliases}"
    assert "कांदा" in aliases, "Marathi alias missing — the CSV will use it"


def test_onion_msp_is_not_applicable_and_handled() -> None:
    """Onion has no MSP. The table must exist, stay empty, and the lookup must
    return cleanly rather than blowing up."""
    with get_conn() as conn:
        commodity_id = conn.execute(
            text("SELECT id FROM commodities WHERE lower(name) = 'onion'")
        ).scalar_one()
        msp_applicable = conn.execute(
            text("SELECT msp_applicable FROM commodities WHERE id = :c"), {"c": commodity_id}
        ).scalar_one()
        msp = conn.execute(
            text("SELECT msp_per_qtl FROM msp_schedule WHERE commodity_id = :c"),
            {"c": commodity_id},
        ).scalar_one_or_none()
    assert msp_applicable is False
    assert msp is None


def test_festivals_non_empty_and_cover_the_data_window() -> None:
    with get_conn() as conn:
        row = conn.execute(
            text("SELECT count(*) AS n, min(fest_date) AS lo, max(fest_date) AS hi FROM festivals")
        ).mappings().one()
    assert row["n"] >= 40, f"only {row['n']} festivals seeded"
    assert row["lo"].year <= 2022 and row["hi"].year >= 2026
    diwali = scalar("SELECT name FROM festivals WHERE fest_date = DATE '2024-11-01'")
    assert diwali == "Diwali"
    effect = scalar(
        "SELECT demand_effect->>'vegetable' FROM festivals WHERE fest_date = DATE '2024-11-01'"
    )
    assert effect == "1"


# ── writable tables ───────────────────────────────────────────────────────

def test_distance_cache_accepts_an_insert() -> None:
    """Coordinates are deliberately fake (0.0001, ...).

    Using the real Vinchur->Lasalgaon pair here would make this test's cleanup
    DELETE a genuine cached OSRM route, and Phase 2 would silently lose it.
    """
    where = {"a": Decimal("0.0001"), "b": Decimal("0.0002"),
             "c": Decimal("0.0003"), "d": Decimal("0.0004")}
    try:
        with get_conn() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO distance_cache
                        (from_lat, from_lon, to_lat, to_lon, road_km, duration_min, source)
                    VALUES (:a, :b, :c, :d, 12.40, 21.5, 'osrm')
                    ON CONFLICT (from_lat, from_lon, to_lat, to_lon) DO UPDATE
                        SET road_km = EXCLUDED.road_km
                    """
                ),
                where,
            )
            km = conn.execute(
                text(
                    "SELECT road_km FROM distance_cache "
                    "WHERE from_lat = :a AND from_lon = :b AND to_lat = :c AND to_lon = :d"
                ),
                where,
            ).scalar_one()
    finally:
        with get_conn() as conn:
            conn.execute(
                text(
                    "DELETE FROM distance_cache "
                    "WHERE from_lat = :a AND from_lon = :b AND to_lat = :c AND to_lon = :d"
                ),
                where,
            )
    assert km == Decimal("12.40")


def test_price_observations_rejects_duplicate_key() -> None:
    """The UNIQUE key is what makes Phase 2's upsert idempotent — prove it bites.

    The first insert must be committed before the second is attempted: an
    uncommitted duplicate would block on the index instead of raising.
    """
    from sqlalchemy.exc import IntegrityError

    insert = text(
        """
        INSERT INTO price_observations
            (obs_date, mandi_id, commodity_id, variety, grade, modal_price, source)
        VALUES (DATE '2019-01-01', :m, :c, '', '', 1500, 'test_phase1')
        """
    )
    with get_conn() as conn:
        params = {
            "m": conn.execute(text("SELECT id FROM mandis ORDER BY id LIMIT 1")).scalar_one(),
            "c": conn.execute(text("SELECT id FROM commodities ORDER BY id LIMIT 1")).scalar_one(),
        }

    try:
        with get_conn() as conn:          # committed on exit
            conn.execute(insert, params)
        with pytest.raises(IntegrityError):
            with get_conn() as conn:
                conn.execute(insert, params)
    finally:
        with get_conn() as conn:
            conn.execute(text("DELETE FROM price_observations WHERE source = 'test_phase1'"))


def test_bot_session_roundtrip() -> None:
    with get_conn() as conn:
        conn.execute(
            text(
                """
                INSERT INTO bot_sessions (phone_e164, state, context)
                VALUES ('+910000000000', 'AWAITING_CROP_QTY', '{"crop":"onion"}'::jsonb)
                ON CONFLICT (phone_e164) DO UPDATE
                    SET state = EXCLUDED.state, context = EXCLUDED.context
                """
            )
        )
        crop = conn.execute(
            text("SELECT context->>'crop' FROM bot_sessions WHERE phone_e164 = '+910000000000'")
        ).scalar_one()
        conn.execute(text("DELETE FROM bot_sessions WHERE phone_e164 = '+910000000000'"))
    assert crop == "onion"
