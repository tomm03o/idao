import math
import warnings

from claude_science.research.adaptive_design import (
    adaptive_ic50_design, fixed_logspaced_design, compare,
)

warnings.filterwarnings("ignore")


def test_designs_recover_ic50():
    import numpy as np
    from claude_science.science import pk
    rng = np.random.default_rng(0)
    true = 300.0
    m = lambda c: float(pk.four_pl(c, 0, 100, true, 1.0)) + rng.normal(0, 3)
    for design in (fixed_logspaced_design, adaptive_ic50_design):
        out = design(m, 8, 0.1, 1e6)
        assert abs(math.log10(out["ic50"] / true)) < 1.0  # within 10x


def test_adaptive_wins_in_wide_range_regime():
    # 10 decades, small budget: adaptive should beat fixed (reproducible seed)
    r = compare(n=6, trials=120, noise=5.0, c_lo=1e-2, c_hi=1e8, seed=7)
    assert r["adaptive_median_logfold"] < r["fixed_median_logfold"]


def test_budget_respected():
    m = lambda c: 50.0
    out = adaptive_ic50_design(m, 7, 1.0, 1e4)
    assert len(out["concentrations"]) == 7
