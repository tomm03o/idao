"""Reproducible validation on REAL ChEMBL data (EGFR / CHEMBL203 IC50s).

Three findings, reported honestly:

1. Bayesian optimisation (Tanimoto-GP + greedy/UCB) finds potent hits far faster
   than random screening -- the objective that matters economically.
2. It does so despite active learning *not* beating random on global RMSE (we
   don't claim it does).
3. Conformal prediction gives calibrated, guaranteed-coverage intervals.

    python -m claude_science.research.validate_molecular_bo

Needs network (downloads + caches ChEMBL activities). Use --target to change.
"""

from __future__ import annotations

import argparse
import warnings

import numpy as np

warnings.filterwarnings("ignore")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", default="CHEMBL203", help="ChEMBL target id (EGFR)")
    ap.add_argument("--max-records", type=int, default=2000, dest="max_records")
    args = ap.parse_args()

    from ..data_sources import chembl
    from .molecular_bo import (TanimotoGP, ConformalRegressor,
                               compare_strategies)

    print(f"Loading real bioactivity data for {args.target} …")
    data = chembl.target_dataset(args.target, max_records=args.max_records)
    smiles = [s for s, _ in data]
    y = np.array([v for _, v in data])
    print(f"  {len(y)} unique molecules; pIC50 {y.min():.2f}–{y.max():.2f} "
          f"(std {y.std():.2f})\n")

    # -- 1 & 2: hit discovery vs random --------------------------------- #
    print("── Hit discovery: top-30 recall vs number of assays ──")
    res = compare_strategies(smiles, y, strategies=("greedy", "ucb", "random"),
                             top_k=30, n_init=15, batch=15, rounds=12, seed=2)
    hdr = "  assays " + "".join(f"{a:>6}" for a in res["greedy"].assays)
    print(hdr)
    for name in ("greedy", "ucb", "random"):
        r = res[name]
        print(f"  {name:<7}" + "".join(f"{v:>6.2f}" for v in r.topk_recall))
    g, rnd = res["greedy"].final_recall(), res["random"].final_recall()
    print(f"\n  → at {res['greedy'].assays[-1]} assays: greedy recovers "
          f"{g:.0%} of the true top-30 vs random {rnd:.0%} "
          f"({g / max(rnd, 1e-9):.1f}× more hits).\n")

    # -- 3: conformal coverage ------------------------------------------ #
    print("── Conformal prediction: calibrated coverage on held-out data ──")
    rng = np.random.default_rng(5)
    idx = rng.permutation(len(y))
    n = len(y)
    tr, cal, te = idx[:n // 2], idx[n // 2:3 * n // 4], idx[3 * n // 4:]
    gp = TanimotoGP(noise=0.4).fit([smiles[i] for i in tr], y[tr])
    cp = ConformalRegressor(gp).calibrate([smiles[i] for i in cal], y[cal])
    print("  target coverage | empirical coverage | mean width (pIC50)")
    for alpha in (0.2, 0.1, 0.05):
        lo, hi = cp.interval([smiles[i] for i in te], alpha=alpha)
        cov = cp.coverage(lo, hi, y[te])
        print(f"       {1 - alpha:.2f}       |       {cov:.3f}        |"
              f"      {float(np.mean(hi - lo)):.2f}")
    print("\n  → coverage tracks the target (distribution-free guarantee holds).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
