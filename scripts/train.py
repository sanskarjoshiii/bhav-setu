"""Phase B2/B3 — train the quantile model, score it, and run the promotion gate.

    python scripts/train.py --from 2022-01-01              # train and report only
    python scripts/train.py --from 2022-01-01 --promote    # ...then gate, maybe promote
    python scripts/train.py --from 2022-01-01 --dry-run    # pipeline check, no artifacts

Promotion is not automatic and not a formality. `--promote` runs the gate in
`ml/registry.check_gate()` against the recorded `baseline-v1` row and refuses if
the model does not clear every line. If it fails, `provider: baseline` stays in
config and the product keeps working — which is the entire payoff of having
built the baseline first.

⚠️ Run `scripts/evaluate_baseline.py` before this, ever. Without a recorded
baseline there is nothing to beat, and a benchmark written down after seeing the
challenger's score is not a benchmark. The gate refuses rather than waving the
model through.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime

import _bootstrap  # noqa: F401  (sys.path side effect)

from core.config import settings
from core.errors import BhavSetuError, InsufficientData
from ml import registry
from ml.dataset import load_or_build
from ml.trainer import render_report, train

ALGO: str = "lightgbm"


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _next_version() -> str:
    """lgbm-v1, lgbm-v2, … — never reuse, so a rollback target always exists."""
    try:
        existing = [r["version"] for r in registry.list_versions()]
    except Exception:                                    # noqa: BLE001 — DB may be down
        existing = []
    numbers = [
        int(v.rsplit("v", 1)[-1]) for v in existing
        if str(v).startswith("lgbm-v") and str(v).rsplit("v", 1)[-1].isdigit()
    ]
    return f"lgbm-v{max(numbers, default=0) + 1}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train the LightGBM quantile model.")
    parser.add_argument("--from", dest="start", type=_parse_date, required=True)
    parser.add_argument("--to", dest="end", type=_parse_date, default=date.today())
    parser.add_argument("--horizons", type=int, nargs="+", default=None)
    parser.add_argument("--version", default=None, help="override the version name")
    parser.add_argument("--promote", action="store_true",
                        help="run the gate and promote if it passes")
    parser.add_argument("--force", action="store_true",
                        help="promote even if the gate fails (says so loudly in the log)")
    parser.add_argument("--refresh", action="store_true",
                        help="rebuild the training matrix instead of reusing the cache")
    parser.add_argument("--dry-run", action="store_true",
                        help="train and print, but write no artifacts and no registry row")
    args = parser.parse_args(argv)

    horizons = args.horizons or [int(h) for h in settings.app.horizons]

    print(f"\nTraining  {args.start} → {args.end}   horizons {horizons}")
    try:
        matrix = load_or_build(args.start, args.end, horizons, refresh=args.refresh)
    except InsufficientData as exc:
        print(f"\n⛔ {exc}\n")
        print("   Build it first:  python scripts/build_dataset.py "
              f"--from {args.start}")
        return 1

    if matrix.empty:
        print("\n⛔ the training matrix is empty.")
        print("   Diagnose it:  python scripts/check_data_readiness.py")
        return 1

    print(f"  matrix    {len(matrix):,} rows")
    print(f"  fitting   {len(horizons)} horizons x 3 quantiles "
          f"= {len(horizons) * 3} boosters\n")

    try:
        boosters, report = train(matrix, horizons)
    except InsufficientData as exc:
        print(f"\n⛔ {exc}")
        return 1

    if not boosters:
        print("\n⛔ no booster could be fitted — every fold was too small.")
        for note in report.fold_notes:
            print(f"     {note}")
        return 1

    print(render_report(report))
    print("\n  folds")
    print("  " + "─" * 62)
    for note in report.fold_notes:
        print(f"  {note}")

    if args.dry_run:
        print("\n  --dry-run: nothing written.\n")
        return 0

    version = args.version or _next_version()
    path = registry.save_artifacts(
        version, boosters, algo=ALGO,
        params=settings.model.lightgbm.to_dict(),
        train_start=report.train_start, train_end=report.train_end,
    )
    print(f"\n  saved     {len(boosters)} boosters → {path}")

    try:
        registry.record(
            version, algo=ALGO, metrics=report.to_metrics(),
            params=settings.model.lightgbm.to_dict(),
            train_start=report.train_start, train_end=report.train_end,
            artifact_path=str(path),
        )
        print(f"  recorded  model_registry.version = {version}")
    except Exception as exc:                              # noqa: BLE001
        print(f"\n  ⚠️  could not write model_registry: {type(exc).__name__}: {exc}")
        print("     Artifacts are on disk; re-record once Postgres is up.")
        return 1

    if not args.promote:
        print(f"\n  Not promoted (no --promote). To serve it:\n"
              f"    python scripts/train.py --from {args.start} --promote\n")
        return 0

    print("\n  the gate (Phase B3)")
    print("  " + "─" * 62)
    result = registry.promote_if_better(
        version, report.model_metrics, horizons, force=args.force
    )
    print(result.render())

    if result.passed:
        print(f"\n  ✅ PROMOTED — {version} is now active.")
        print("     Finish the swap:  set  provider: lightgbm  in config/model.yaml,")
        print("     then restart the API.\n")
        return 0
    if args.force:
        print(f"\n  ⚠️  PROMOTED OVER A FAILED GATE — {version} is active because "
              f"--force was passed.\n")
        return 0

    print(f"\n  ⛔ NOT PROMOTED. {version} is recorded but not active;")
    print("     provider: baseline stays live and the product keeps working.")
    print("     That is the design, not a failure of it.\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
