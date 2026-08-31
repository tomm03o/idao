"""Reproducible validation of the adaptive IC50 design.

Runs the Monte-Carlo head-to-head across regimes and prints a table. This is the
evidence behind the claim in ``adaptive_design`` -- run it yourself:

    python -m claude_science.research.validate_adaptive_design
"""

from __future__ import annotations

import warnings

from .adaptive_design import compare

warnings.filterwarnings("ignore")  # scipy covariance warnings on sparse fits


def main() -> None:
    print("Adaptive vs fixed log-spaced IC50 design "
          "(median |log10-fold| error, lower is better)\n")
    print(f"{'range':>12} {'n':>3} {'fixed':>8} {'adaptive':>9} {'reduction':>10}")
    regimes = [
        ("4 decades", 1.0, 1e4),
        ("7 decades", 0.1, 1e6),
        ("10 decades", 1e-2, 1e8),
    ]
    for label, lo, hi in regimes:
        for n in (6, 8):
            r = compare(n=n, trials=400, noise=5.0, c_lo=lo, c_hi=hi, seed=7)
            print(f"{label:>12} {n:>3} "
                  f"{r['fixed_median_logfold']:>8.3f} "
                  f"{r['adaptive_median_logfold']:>9.3f} "
                  f"{r['median_error_reduction_pct']:>9.0f}%")
    print("\nTakeaway: adaptivity pays off in the wide-range / small-budget "
          "regime; a fixed grid is fine when the range is narrow.")


if __name__ == "__main__":
    main()
