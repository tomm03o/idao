"""Command line interface.

    habscan fetch                # download catalogues into data/raw
    habscan run [--fetch] [--samples N] [--no-sensitivity]
    habscan planet "TRAPPIST-1 e" "Proxima Cen b"   # quick look at named planets from the last run
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="habscan", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw-dir", type=Path, default=ROOT / "data" / "raw")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "outputs")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch", help="download NASA Exoplanet Archive tables and the PHL catalogue")
    r = sub.add_parser("run", help="run the full pipeline")
    r.add_argument("--fetch", action="store_true", help="re-download catalogues first")
    r.add_argument("--samples", type=int, default=2000, help="Monte Carlo samples per planet")
    r.add_argument("--seed", type=int, default=20261127)
    r.add_argument("--no-sensitivity", action="store_true", help="skip the robustness study")
    r.add_argument("--top", type=int, default=100)
    p = sub.add_parser("planet", help="show results for named planets from outputs/ranking_all.csv.gz")
    p.add_argument("names", nargs="+")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.cmd == "fetch":
        from .data.archive import fetch_all
        for res in fetch_all(args.raw_dir):
            print(f"{res.name}: {res.rows} rows -> {res.path}")
        return 0
    if args.cmd == "run":
        from .pipeline import run
        res = run(args.raw_dir, args.out_dir, fetch=args.fetch, n_samples=args.samples, seed=args.seed,
                  sensitivity=not args.no_sensitivity, top_k=args.top)
        cols = ["rank", "name", "source", "p_real", "p_habitable", "p_habitable_and_real", "robust_top_fraction"]
        with pd.option_context("display.width", 200, "display.max_columns", 20):
            print(res.ranking[cols].head(25).to_string(index=False, float_format=lambda v: f"{v:.3f}"))
        print(f"\nreport: {res.out_dir / 'report.md'}")
        return 0
    if args.cmd == "planet":
        path = args.out_dir / "ranking_all.csv.gz"
        if not path.exists():
            print(f"{path} not found: run `habscan run` first", file=sys.stderr)
            return 1
        df = pd.read_csv(path)
        hit = df[df["name"].str.lower().isin([n.lower() for n in args.names])]
        if hit.empty:
            print("no match", file=sys.stderr)
            return 1
        with pd.option_context("display.max_rows", 200):
            print(hit.set_index("name").T.to_string())
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
