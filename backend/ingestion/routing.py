"""Phase 2.7 — road distance between two points, cached forever.

OSRM's public demo server is rate-limited, so every pair is called at most once
and stored in `distance_cache`. If OSRM is down or slow we fall back to haversine
x 1.3 and log a warning — a routing call must never crash the demo.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.engine import Connection

from core import logging as log
from core.config import settings
from core.db import get_conn
from ingestion import RunCounters

_CFG = settings.sources.routing
OSRM_URL: str = str(_CFG.osrm_url).rstrip("/")
FALLBACK_FACTOR: float = float(_CFG.haversine_fallback_factor)
PRECISION: int = int(_CFG.coord_precision)
TIMEOUT: float = float(settings.sources.ingestion.http_timeout_seconds)
EARTH_RADIUS_KM: float = 6371.0088


@dataclass(frozen=True)
class Route:
    road_km: float
    duration_min: float | None
    source: str            # cache | osrm | haversine_fallback


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance. Used for the fallback and for sanity checks."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _round(value: float) -> float:
    return round(float(value), PRECISION)


def _lookup(conn: Connection, coords: tuple[float, float, float, float]) -> Route | None:
    row = conn.execute(
        text(
            "SELECT road_km, duration_min, source FROM distance_cache "
            "WHERE from_lat = :a AND from_lon = :b AND to_lat = :c AND to_lon = :d"
        ),
        dict(zip(("a", "b", "c", "d"), coords)),
    ).mappings().first()
    if row is None:
        return None
    return Route(float(row["road_km"]),
                 None if row["duration_min"] is None else float(row["duration_min"]),
                 "cache")


def _store(conn: Connection, coords: tuple[float, float, float, float], route: Route) -> None:
    conn.execute(
        text(
            """
            INSERT INTO distance_cache
                (from_lat, from_lon, to_lat, to_lon, road_km, duration_min, source)
            VALUES (:a, :b, :c, :d, :km, :mins, :source)
            ON CONFLICT (from_lat, from_lon, to_lat, to_lon) DO UPDATE SET
                road_km      = EXCLUDED.road_km,
                duration_min = EXCLUDED.duration_min,
                source       = EXCLUDED.source,
                cached_at    = now()
            """
        ),
        {**dict(zip(("a", "b", "c", "d"), coords)),
         "km": route.road_km, "mins": route.duration_min, "source": route.source},
    )


def _call_osrm(from_lat: float, from_lon: float, to_lat: float, to_lon: float) -> Route:
    url = f"{OSRM_URL}/{from_lon},{from_lat};{to_lon},{to_lat}"
    try:
        with httpx.Client(follow_redirects=True) as client:
            response = client.get(url, params={"overview": "false"}, timeout=TIMEOUT)
        payload = response.json() if response.status_code == 200 else {}
        routes = payload.get("routes") or []
        log.external_call(url, response.status_code, rows=len(routes))
        if response.status_code == 200 and routes:
            return Route(
                road_km=round(float(routes[0]["distance"]) / 1000.0, 2),
                duration_min=round(float(routes[0]["duration"]) / 60.0, 1),
                source="osrm",
            )
        log.warn("osrm_no_route", url=url, status=response.status_code)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        log.warn("osrm_failed", url=url, error=f"{type(exc).__name__}: {exc}")

    straight = haversine_km(from_lat, from_lon, to_lat, to_lon)
    fallback = round(straight * FALLBACK_FACTOR, 2)
    log.warn("osrm_fallback_used", haversine_km=round(straight, 2),
             road_km=fallback, factor=FALLBACK_FACTOR)
    return Route(road_km=fallback, duration_min=None, source="haversine_fallback")


def road_distance_km(from_lat: float, from_lon: float,
                     to_lat: float, to_lon: float) -> float:
    """Cached road distance in km. Never raises."""
    return route(from_lat, from_lon, to_lat, to_lon).road_km


def route(from_lat: float, from_lon: float, to_lat: float, to_lon: float) -> Route:
    """Full result including duration and where the number came from."""
    coords = (_round(from_lat), _round(from_lon), _round(to_lat), _round(to_lon))
    with get_conn() as conn:
        cached = _lookup(conn, coords)
        if cached is not None:
            return cached
    result = _call_osrm(from_lat, from_lon, to_lat, to_lon)
    with get_conn() as conn:
        _store(conn, coords, result)
    return result


def warm_cache(counters: RunCounters | None = None) -> dict[str, Any]:
    """Pre-compute village->mandi and mandi->mandi distances once, up front.

    Doing this during backfill means the live API never waits on OSRM, and the
    demo cannot be embarrassed by a rate limit.
    """
    village = settings.mandis.reference_village
    with get_conn() as conn:
        mandis = [
            dict(r)
            for r in conn.execute(
                text("SELECT id, name, lat, lon FROM mandis WHERE active ORDER BY id")
            ).mappings()
        ]

    pairs: list[tuple[float, float, float, float]] = [
        (float(village["lat"]), float(village["lon"]), float(m["lat"]), float(m["lon"]))
        for m in mandis
    ]
    pairs += [
        (float(a["lat"]), float(a["lon"]), float(b["lat"]), float(b["lon"]))
        for a in mandis
        for b in mandis
        if a["id"] != b["id"]
    ]

    sources: dict[str, int] = {}
    for from_lat, from_lon, to_lat, to_lon in pairs:
        result = route(from_lat, from_lon, to_lat, to_lon)
        sources[result.source] = sources.get(result.source, 0) + 1

    if counters is not None:
        counters.rows_in = len(pairs)
        counters.rows_kept = len(pairs)
        counters.detail.update(sources)

    log.info("routing_cache_warm", pairs=len(pairs), by_source=sources)
    return {"pairs": len(pairs), "by_source": sources}
