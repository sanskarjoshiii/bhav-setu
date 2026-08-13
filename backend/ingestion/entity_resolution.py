"""Phase 2.4 — map raw source names ("LASALGAON(VINCHUR)", "Onion(Big)") to ids.

Thresholds (config/sources.yaml -> entity_resolution):
    score >= auto_threshold    -> map silently
    review_threshold .. auto-1 -> map, but write the pair to fuzzy_review.csv
    score <  review_threshold  -> unmatched, counted, row dropped

Matching is RapidFuzz `token_sort_ratio` over `mandis.normalised_name`, with one
deterministic pre-rule: a raw name whose leading tokens *are* a known mandi name
("lasalgaon vinchur" -> "lasalgaon") is an exact map. Agmarknet spells sub-yards
that way constantly and plain fuzzy scoring drops them.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz, process
from sqlalchemy import text
from sqlalchemy.engine import Connection

from core import logging as log
from core.config import settings

_CFG = settings.sources.entity_resolution
AUTO_THRESHOLD: float = float(_CFG.auto_threshold)
REVIEW_THRESHOLD: float = float(_CFG.review_threshold)
MIN_PREFIX_CHARS: int = int(_CFG.min_prefix_tokens_chars)
REVIEW_PATH: Path = settings.path(*str(_CFG.review_csv).split("/"))


def normalise(name: str) -> str:
    """Lowercase, strip accents and punctuation, collapse whitespace.

    The single implementation: `mandis.normalised_name` and
    `commodity_aliases.normalised_alias` are written with it in Phase 1, and every
    lookup here compares against it, so both sides always agree.
    """
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_ish = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    lowered = ascii_ish.lower()
    cleaned = re.sub(r"[^\w\s]", " ", lowered, flags=re.UNICODE)
    return re.sub(r"\s+", " ", cleaned).strip()


@dataclass(frozen=True)
class Resolution:
    """Outcome of one lookup. `entity_id is None` means unmatched."""

    raw: str
    entity_id: int | None
    matched_name: str | None
    score: float
    method: str                    # exact | prefix | fuzzy | none
    needs_review: bool

    @property
    def matched(self) -> bool:
        return self.entity_id is not None


@dataclass(frozen=True)
class _Candidate:
    entity_id: int
    name: str
    normalised: str
    district: str | None


class Resolver:
    """Loads the reference tables once, then answers lookups from memory.

    A CSV backfill asks the same 40 distinct questions a million times, so every
    answer is cached.
    """

    def __init__(self, conn: Connection) -> None:
        self._mandis: list[_Candidate] = [
            _Candidate(row["id"], row["name"], row["normalised_name"], row["district"])
            for row in conn.execute(
                text(
                    "SELECT m.id, m.name, m.normalised_name, m.district "
                    "FROM mandis m WHERE m.active"
                )
            ).mappings()
        ]
        self._commodities: list[_Candidate] = [
            _Candidate(row["commodity_id"], row["alias"], row["normalised_alias"], None)
            for row in conn.execute(
                text("SELECT commodity_id, alias, normalised_alias FROM commodity_aliases")
            ).mappings()
        ]
        if not self._mandis:
            raise ValueError("no mandis in the database — run scripts/init_db.py first")
        if not self._commodities:
            raise ValueError("no commodity aliases in the database — run scripts/init_db.py")

        self._mandi_cache: dict[tuple[str, str], Resolution] = {}
        self._commodity_cache: dict[str, Resolution] = {}
        self.unmatched_mandis: Counter[str] = Counter()
        self.unmatched_commodities: Counter[str] = Counter()
        self._review: dict[tuple[str, str, str], dict[str, Any]] = {}

    # ── public API ────────────────────────────────────────────────────────

    def resolve_mandi(
        self, raw_name: str, district: str | None = None, state: str | None = None
    ) -> Resolution:
        key = (str(raw_name or "").strip().lower(), str(district or "").strip().lower())
        cached = self._mandi_cache.get(key)
        if cached is not None:
            if not cached.matched:
                self.unmatched_mandis[str(raw_name)] += 1
            return cached

        pool = self._mandis
        if district:
            same_district = [c for c in pool if _same(c.district, district)]
            if same_district:
                pool = same_district

        resolution = self._match(str(raw_name or ""), pool, kind="mandi")
        self._mandi_cache[key] = resolution
        if not resolution.matched:
            self.unmatched_mandis[str(raw_name)] += 1
        elif resolution.needs_review:
            self._queue_review("mandi", raw_name, resolution, district=district, state=state)
        return resolution

    def resolve_commodity(self, raw_name: str) -> Resolution:
        key = str(raw_name or "").strip().lower()
        cached = self._commodity_cache.get(key)
        if cached is not None:
            if not cached.matched:
                self.unmatched_commodities[str(raw_name)] += 1
            return cached

        resolution = self._match(str(raw_name or ""), self._commodities, kind="commodity")
        self._commodity_cache[key] = resolution
        if not resolution.matched:
            self.unmatched_commodities[str(raw_name)] += 1
        elif resolution.needs_review:
            self._queue_review("commodity", raw_name, resolution)
        return resolution

    def flush_review(self) -> Path | None:
        """Write the 90–94 band to data/artifacts/fuzzy_review.csv for a human."""
        if not self._review:
            return None
        REVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
        fields = ["kind", "raw_name", "district", "state", "matched_name", "score", "method"]
        with REVIEW_PATH.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for row in sorted(self._review.values(), key=lambda r: r["score"]):
                writer.writerow(row)
        log.info("fuzzy_review_written", path=str(REVIEW_PATH), rows=len(self._review))
        return REVIEW_PATH

    def review_count(self) -> int:
        return len(self._review)

    # ── internals ─────────────────────────────────────────────────────────

    def _match(self, raw: str, pool: list[_Candidate], kind: str) -> Resolution:
        needle = normalise(raw)
        if not needle:
            return Resolution(raw, None, None, 0.0, "none", False)

        by_norm = {c.normalised: c for c in pool}
        exact = by_norm.get(needle)
        if exact is not None:
            return Resolution(raw, exact.entity_id, exact.name, 100.0, "exact", False)

        prefix = _prefix_match(needle, pool)
        if prefix is not None:
            return Resolution(raw, prefix.entity_id, prefix.name, 100.0, "prefix", False)

        best = process.extractOne(needle, list(by_norm.keys()), scorer=fuzz.token_sort_ratio)
        if best is None:
            return Resolution(raw, None, None, 0.0, "none", False)
        matched_norm, score, _ = best
        candidate = by_norm[matched_norm]

        if score >= AUTO_THRESHOLD:
            return Resolution(raw, candidate.entity_id, candidate.name, float(score), "fuzzy", False)
        if score >= REVIEW_THRESHOLD:
            return Resolution(raw, candidate.entity_id, candidate.name, float(score), "fuzzy", True)
        log.info("unmatched_entity", kind=kind, raw=raw, best=candidate.name, score=round(float(score), 1))
        return Resolution(raw, None, candidate.name, float(score), "none", False)

    def _queue_review(
        self,
        kind: str,
        raw_name: str,
        resolution: Resolution,
        district: str | None = None,
        state: str | None = None,
    ) -> None:
        key = (kind, str(raw_name), str(district or ""))
        self._review[key] = {
            "kind": kind,
            "raw_name": raw_name,
            "district": district or "",
            "state": state or "",
            "matched_name": resolution.matched_name or "",
            "score": round(resolution.score, 1),
            "method": resolution.method,
        }


def _prefix_match(needle: str, pool: list[_Candidate]) -> _Candidate | None:
    """"lasalgaon vinchur" -> Lasalgaon. Whole leading tokens only, never substrings."""
    tokens = needle.split()
    for candidate in pool:
        cand_tokens = candidate.normalised.split()
        if not cand_tokens or len(candidate.normalised) < MIN_PREFIX_CHARS:
            continue
        if len(cand_tokens) < len(tokens) and tokens[: len(cand_tokens)] == cand_tokens:
            return candidate
    return None


def _same(a: str | None, b: str | None) -> bool:
    return bool(a) and bool(b) and normalise(str(a)) == normalise(str(b))
