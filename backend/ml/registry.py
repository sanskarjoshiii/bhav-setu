"""Phase B4 — model versions, their scores, and the gate that decides shipping.

Two jobs, deliberately kept together:

  * **Artifacts.** Save and load the 12 boosters plus a manifest that records the
    feature order they were trained on. The manifest is not bookkeeping — it is
    what lets `lgbm_provider` refuse to serve a model whose columns have drifted
    away from `features/registry.py`. A model served on the wrong column order
    does not crash; it just gets quietly, unfixably worse.

  * **The gate.** `promote_if_better()` compares a challenger against the
    recorded `baseline-v1` row and refuses unless it clears every threshold in
    `config/model.yaml → promotion`. This is the whole payoff of Track A: a
    disappointing model is a config decision, not a crisis on stage.

The one rule about promotion: a benchmark written down *after* seeing the
challenger's score is not a benchmark. `evaluate_baseline.py` must have run
first. If `baseline-v1` is missing, promotion refuses rather than waving the
model through — an ungated promotion is the failure this whole design exists to
prevent.
"""

from __future__ import annotations

import json
import math
import shutil
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from sqlalchemy import text

from core import logging as log
from core.config import settings
from core.db import get_conn
from core.errors import ModelNotFound
from features.registry import FEATURE_NAMES

ARTIFACTS_DIR: Path = settings.path(*str(settings.model.artifacts_dir).split("/"))
BASELINE_VERSION: str = str(settings.model.baseline.version)
MANIFEST_NAME: str = "manifest.json"

#: Quantiles we fit, from app.yaml, so training and serving cannot disagree.
QUANTILES: dict[str, float] = {
    name: float(value) for name, value in settings.app.quantiles.to_dict().items()
}


def booster_name(horizon: int, quantile_key: str) -> str:
    """One booster per (horizon, quantile). 4 x 3 = the 12 files."""
    return f"h{int(horizon)}_{quantile_key}.txt"


def _json_safe(value: Any) -> Any:
    """Make a metrics tree storable as Postgres JSONB.

    Two conversions, both load-bearing:

    * **NaN and ±Inf become null.** Python's `json.dumps` writes them as bare
      `NaN`/`Infinity`, which is valid JavaScript and invalid JSON — Postgres
      rejects the whole insert. And NaN is not a bug here: the naive baseline's
      directional accuracy is genuinely NaN, because a method that predicts "no
      change" never calls a direction, and `metrics.directional_accuracy`
      deliberately reports that rather than scoring it 0%.
    * **numpy scalars become Python floats**, since `json` cannot serialise
      `np.float64` and every metric arrives as one.
    """
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (bool, str)) or value is None:
        return value
    if hasattr(value, "item") and not isinstance(value, (int, float)):
        try:
            value = value.item()          # numpy scalar -> Python scalar
        except (AttributeError, ValueError):
            return str(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, int):
        return value
    return str(value)


# ══════════════════════════════════════════════════════════════════════════
# artifacts on disk
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class Manifest:
    """What a saved model needs to know about itself to be served safely."""

    version: str
    algo: str
    horizons: list[int]
    quantiles: dict[str, float]
    feature_names: list[str]
    params: dict[str, Any] = field(default_factory=dict)
    trained_at: str = ""
    train_start: str | None = None
    train_end: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "algo": self.algo,
            "horizons": self.horizons,
            "quantiles": self.quantiles,
            "feature_names": self.feature_names,
            "params": self.params,
            "trained_at": self.trained_at,
            "train_start": self.train_start,
            "train_end": self.train_end,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Manifest":
        return cls(
            version=str(raw["version"]),
            algo=str(raw.get("algo", "lightgbm")),
            horizons=[int(h) for h in raw["horizons"]],
            quantiles={k: float(v) for k, v in raw["quantiles"].items()},
            feature_names=[str(n) for n in raw["feature_names"]],
            params=dict(raw.get("params", {})),
            trained_at=str(raw.get("trained_at", "")),
            train_start=raw.get("train_start"),
            train_end=raw.get("train_end"),
        )


def version_dir(version: str) -> Path:
    return ARTIFACTS_DIR / version


def save_artifacts(
    version: str,
    boosters: Mapping[tuple[int, str], Any],
    *,
    algo: str = "lightgbm",
    params: Mapping[str, Any] | None = None,
    train_start: date | None = None,
    train_end: date | None = None,
) -> Path:
    """Write the boosters and the manifest. Returns the directory."""
    target = version_dir(version)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)

    horizons = sorted({int(h) for h, _ in boosters})
    for (horizon, quantile_key), booster in boosters.items():
        booster.save_model(str(target / booster_name(horizon, quantile_key)))

    manifest = Manifest(
        version=version,
        algo=algo,
        horizons=horizons,
        quantiles=dict(QUANTILES),
        feature_names=list(FEATURE_NAMES),
        params=dict(params or {}),
        trained_at=datetime.now(timezone.utc).isoformat(),
        train_start=str(train_start) if train_start else None,
        train_end=str(train_end) if train_end else None,
    )
    (target / MANIFEST_NAME).write_text(
        json.dumps(manifest.to_dict(), indent=2), encoding="utf-8"
    )
    log.info("model_artifacts_saved", version=version, path=str(target),
             boosters=len(boosters))
    return target


def load_manifest(version: str) -> Manifest:
    path = version_dir(version) / MANIFEST_NAME
    if not path.exists():
        raise ModelNotFound(f"no manifest at {path} — was version {version!r} ever trained?")
    return Manifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


# ══════════════════════════════════════════════════════════════════════════
# the model_registry table
# ══════════════════════════════════════════════════════════════════════════

_UPSERT = text(
    """
    INSERT INTO model_registry
        (version, trained_at, train_start, train_end, algo, params, metrics,
         is_active, artifact_path)
    VALUES
        (:version, :trained_at, :train_start, :train_end, :algo,
         CAST(:params AS JSONB), CAST(:metrics AS JSONB), FALSE, :artifact_path)
    ON CONFLICT (version) DO UPDATE SET
        trained_at    = EXCLUDED.trained_at,
        train_start   = EXCLUDED.train_start,
        train_end     = EXCLUDED.train_end,
        algo          = EXCLUDED.algo,
        params        = EXCLUDED.params,
        metrics       = EXCLUDED.metrics,
        artifact_path = EXCLUDED.artifact_path
    """
)


def record(
    version: str,
    *,
    algo: str,
    metrics: Mapping[str, Any],
    params: Mapping[str, Any] | None = None,
    train_start: date | None = None,
    train_end: date | None = None,
    artifact_path: str | Path | None = None,
) -> None:
    """Write (or refresh) a version's row. Never touches `is_active`."""
    with get_conn() as conn:
        conn.execute(
            _UPSERT,
            {
                "version": version,
                "trained_at": datetime.now(timezone.utc),
                "train_start": train_start,
                "train_end": train_end,
                "algo": algo,
                "params": json.dumps(_json_safe(dict(params or {}))),
                "metrics": json.dumps(_json_safe(dict(metrics))),
                "artifact_path": str(artifact_path) if artifact_path else None,
            },
        )
    log.info("model_registry_recorded", version=version, algo=algo)


def get(version: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            text("SELECT * FROM model_registry WHERE version = :v"), {"v": version}
        ).mappings().first()
    return dict(row) if row else None


def active() -> dict[str, Any] | None:
    """The version currently marked active, if any. `routers/accuracy.py` reads this."""
    with get_conn() as conn:
        row = conn.execute(
            text("SELECT * FROM model_registry WHERE is_active ORDER BY trained_at DESC")
        ).mappings().first()
    return dict(row) if row else None


def list_versions() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            text("SELECT * FROM model_registry ORDER BY trained_at DESC NULLS LAST")
        ).mappings().all()
    return [dict(r) for r in rows]


def promote(version: str) -> None:
    """Mark one version active, clearing any other.

    The schema carries `idx_model_one_active`, a unique index on `is_active`
    where true, so the clear must happen in the same transaction as the set.
    """
    with get_conn() as conn:
        if conn.execute(
            text("SELECT 1 FROM model_registry WHERE version = :v"), {"v": version}
        ).first() is None:
            raise ModelNotFound(f"cannot promote {version!r}: it is not in model_registry")
        conn.execute(text("UPDATE model_registry SET is_active = FALSE WHERE is_active"))
        conn.execute(
            text("UPDATE model_registry SET is_active = TRUE WHERE version = :v"),
            {"v": version},
        )
    log.info("model_promoted", version=version)


# ══════════════════════════════════════════════════════════════════════════
# the gate
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class GateResult:
    """Why a model was or was not promoted. Printed in full — never just a verdict."""

    passed: bool
    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str) -> None:
        self.checks.append((name, bool(ok), detail))
        if not ok:
            self.passed = False

    def render(self) -> str:
        lines = [f"  {'✅' if ok else '❌'} {name:<34} {detail}"
                 for name, ok, detail in self.checks]
        return "\n".join(lines)


def _thresholds() -> Mapping[str, Any]:
    """Promotion thresholds from config/model.yaml, so the gate is not in code."""
    promotion = settings.model.get("promotion")
    return promotion.to_dict() if promotion is not None else {}


def check_gate(
    candidate_metrics: Mapping[str, Any],
    baseline_metrics: Mapping[str, Any] | None,
    horizons: Sequence[int],
) -> GateResult:
    """Phase B3. Every threshold, evaluated and reported — pass or fail.

    `candidate_metrics` and `baseline_metrics` are the nested
    `{"h7": {"pinball_mean": ..., "picp": ...}}` shape the trainer produces.
    """
    limits = _thresholds()
    result = GateResult(passed=True)

    if baseline_metrics is None:
        result.add(
            "baseline recorded", False,
            f"{BASELINE_VERSION} is not in model_registry — "
            f"run scripts/evaluate_baseline.py before promoting anything",
        )
        return result

    # 1. Beat the benchmark's pinball loss at every horizon. The benchmark is
    #    plain naive, not the tuned baseline — "beats the dumbest thing that
    #    works" is the claim we want to make without an asterisk.
    for horizon in horizons:
        key = f"h{horizon}"
        mine = float(candidate_metrics.get(key, {}).get("pinball_mean", float("nan")))
        theirs = float(baseline_metrics.get(key, {}).get("pinball_mean", float("nan")))
        ok = mine == mine and theirs == theirs and mine < theirs
        gain = (theirs - mine) / abs(theirs) * 100 if theirs else float("nan")
        result.add(f"pinball better @ h={horizon}", ok,
                   f"{mine:.5f} vs baseline {theirs:.5f}  ({gain:+.1f}%)")

    # 2. Bands honest, not just narrow. Too low means overconfident; too high
    #    means we widened them until they were useless.
    picp_min = float(limits.get("picp_min", 0.72))
    picp_max = float(limits.get("picp_max", 0.88))
    for horizon in horizons:
        value = float(candidate_metrics.get(f"h{horizon}", {}).get("picp", float("nan")))
        ok = picp_min <= value <= picp_max
        result.add(f"PICP in range @ h={horizon}", ok,
                   f"{value:.3f}  (want {picp_min:.2f}–{picp_max:.2f})")

    # 3. Direction at the horizon the product actually sells on.
    da_horizon = int(limits.get("directional_horizon", 7))
    da_min = float(limits.get("directional_accuracy_min", 0.60))
    da = float(candidate_metrics.get(f"h{da_horizon}", {})
               .get("directional_accuracy", float("nan")))
    result.add(f"directional acc @ h={da_horizon}", da >= da_min,
               f"{da:.3f}  (want ≥ {da_min:.2f})")

    # 4. Sanity on the level error.
    # 4. Level error. Two ways to configure it, and only one should be set.
    #
    #    `mape_beats_baseline: true` is the live one — beat the recorded
    #    baseline's MAPE at every horizon. Self-calibrating, and the same shape
    #    as the pinball test above. `mape_max` is kept for a project that wants
    #    a hard absolute ceiling instead; see the note in config/model.yaml for
    #    why this one does not.
    if limits.get("mape_beats_baseline"):
        for horizon in horizons:
            key = f"h{horizon}"
            mine = float(candidate_metrics.get(key, {}).get("mape", float("nan")))
            theirs = float(baseline_metrics.get(key, {}).get("mape", float("nan")))
            ok = mine == mine and theirs == theirs and mine < theirs
            gain = (theirs - mine) / abs(theirs) * 100 if theirs else float("nan")
            result.add(f"MAPE better @ h={horizon}", ok,
                       f"{mine:.2f}% vs baseline {theirs:.2f}%  ({gain:+.1f}%)")

    # `mape_max` is keyed "h1"/"h7" already — do NOT re-prefix it.
    for key, cap in (limits.get("mape_max") or {}).items():
        value = float(candidate_metrics.get(str(key), {}).get("mape", float("nan")))
        ok = value == value and value <= float(cap)
        result.add(f"MAPE @ {key}", ok, f"{value:.2f}%  (want ≤ {float(cap):.1f}%)")

    return result


def promote_if_better(
    version: str,
    candidate_metrics: Mapping[str, Any],
    horizons: Sequence[int],
    *,
    baseline_version: str = BASELINE_VERSION,
    force: bool = False,
) -> GateResult:
    """Run the gate; promote only if it passes (or `force`, which says so loudly)."""
    baseline = get(baseline_version)
    baseline_metrics = (baseline or {}).get("metrics") if baseline else None
    if isinstance(baseline_metrics, str):
        baseline_metrics = json.loads(baseline_metrics)

    result = check_gate(candidate_metrics, baseline_metrics, horizons)

    if result.passed:
        promote(version)
    elif force:
        log.warn("model_promoted_over_failed_gate", version=version,
                 failed=[n for n, ok, _ in result.checks if not ok])
        promote(version)
    else:
        log.warn("model_promotion_refused", version=version,
                 failed=[n for n, ok, _ in result.checks if not ok])
    return result
