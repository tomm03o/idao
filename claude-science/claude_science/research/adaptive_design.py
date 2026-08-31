"""Sequential D-optimal experimental design for IC50 estimation.

Problem. A dose-response (4-parameter logistic / Hill) assay has a fixed, costly
budget of ``n`` measurements. The parameter we care about is log10(IC50), but
IC50 is unknown a priori and may lie anywhere across several orders of magnitude.
A fixed log-spaced grid wastes most of its points on the plateaus (which are
uninformative about IC50) whenever the true IC50 sits near an edge of the tested
range.

Idea. For the Hill model the sensitivity of the response to log10(IC50) is
maximal exactly at the inflection point c = IC50, and decays as a bell curve in
log-concentration with a width set by the Hill slope. So the information-optimal
plan is: pin the two plateaus with a couple of anchor points, then spend the
remaining budget clustered around the *current estimate* of IC50, refining that
estimate as data arrives. This is a sequential (adaptive) D-optimal design.

Algorithm ``adaptive_ic50_design``:
  1. Seed with 3 log-spaced anchors across the allowed range; fit 4PL.
  2. Repeat until budget spent: place the next concentration at the current
     IC50 estimate, offset by +/- a step scaled to the estimated Hill slope
     (this maximises the Fisher information for log-IC50); measure; refit.
  3. Return the final IC50 estimate.

This module also provides ``fixed_logspaced_design`` (the standard baseline) and
``compare`` for a Monte-Carlo head-to-head.

Empirically validated regime (see ``research/validate_adaptive_design.py``).
The advantage is real but *conditional*, and we report it honestly:

* When potency is unknown across a **wide dynamic range** (~10 log-decades)
  and the **budget is small** (n <= 6-8) -- the realistic primary-screening
  regime -- the adaptive design cuts median |log10-fold| IC50 error by ~25-30%
  at equal cost, because it first locates the active decade then refines there.
* When the range is narrow (~4 decades), a fixed log-spaced grid already
  brackets the curve well and adaptivity gives **no** benefit (and can slightly
  hurt by under-sampling the plateaus). Use the fixed design there. The
  crossover sits near ~7-8 decades for these budgets.

The knob that matters is ``log10(c_hi/c_lo) / n`` -- adaptivity pays off once a
fixed grid can no longer place a point within ~1 Hill-width of the inflection.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Sequence, Tuple

import numpy as np

from ..science import pk

Measure = Callable[[float], float]  # concentration -> noisy % inhibition


def _fit_ic50(concs: List[float], resps: List[float], fallback: float) -> Tuple[float, float]:
    try:
        fit = pk.fit_dose_response(concs, resps)
        ic50 = float(fit["ic50"])
        hill = float(fit["hill_slope"])
        if not (math.isfinite(ic50) and ic50 > 0):
            return fallback, 1.0
        return ic50, max(0.3, min(hill, 4.0))
    except Exception:
        return fallback, 1.0


def fixed_logspaced_design(measure: Measure, n: int,
                           c_lo: float, c_hi: float) -> Dict[str, object]:
    """Baseline: n evenly log-spaced concentrations, single 4PL fit."""
    concs = list(np.logspace(math.log10(c_lo), math.log10(c_hi), n))
    resps = [measure(c) for c in concs]
    ic50, _ = _fit_ic50(concs, resps, math.sqrt(c_lo * c_hi))
    return {"ic50": ic50, "concentrations": concs, "responses": resps}


def adaptive_ic50_design(measure: Measure, n: int,
                         c_lo: float, c_hi: float,
                         n_anchor: int = 3) -> Dict[str, object]:
    """Sequential D-optimal design that concentrates samples near IC50."""
    n_anchor = min(n_anchor, n)
    concs = list(np.logspace(math.log10(c_lo), math.log10(c_hi), n_anchor))
    resps = [measure(c) for c in concs]
    ic50, hill = _fit_ic50(concs, resps, math.sqrt(c_lo * c_hi))

    lo, hi = math.log10(c_lo), math.log10(c_hi)
    toggle = 1
    for k in range(n - n_anchor):
        # optimal offset from the inflection for log-IC50 information ~ 1/hill
        step = (1.0 / hill) * (0.7 if k % 2 == 0 else 1.4)
        center = math.log10(min(max(ic50, c_lo), c_hi))
        next_log = min(hi, max(lo, center + toggle * step))
        toggle *= -1
        c = float(10 ** next_log)
        concs.append(c)
        resps.append(measure(c))
        ic50, hill = _fit_ic50(concs, resps, ic50)

    return {"ic50": ic50, "concentrations": concs, "responses": resps}


def _make_measure(true_ic50: float, hill: float, noise: float,
                  rng: np.random.Generator) -> Measure:
    def measure(c: float) -> float:
        r = float(pk.four_pl(c, 0.0, 100.0, true_ic50, hill))
        return r + rng.normal(0.0, noise)
    return measure


def compare(n: int = 6, trials: int = 300, noise: float = 5.0,
            c_lo: float = 0.1, c_hi: float = 1_000_000.0,
            seed: int = 0) -> Dict[str, float]:
    """Monte-Carlo head-to-head; returns median/mean |log10 fold| error each.

    Defaults are the wide-range / small-budget regime where the adaptive design
    is expected to win; pass a narrower ``(c_lo, c_hi)`` to see the crossover.
    """
    rng = np.random.default_rng(seed)
    err_fixed: List[float] = []
    err_adapt: List[float] = []
    for _ in range(trials):
        true_ic50 = float(10 ** rng.uniform(math.log10(c_lo), math.log10(c_hi)))
        hill = float(rng.uniform(0.8, 1.8))
        m1 = _make_measure(true_ic50, hill, noise, rng)
        m2 = _make_measure(true_ic50, hill, noise, rng)
        f = fixed_logspaced_design(m1, n, c_lo, c_hi)["ic50"]
        a = adaptive_ic50_design(m2, n, c_lo, c_hi)["ic50"]
        err_fixed.append(abs(math.log10(max(f, 1e-9) / true_ic50)))
        err_adapt.append(abs(math.log10(max(a, 1e-9) / true_ic50)))
    ef, ea = np.array(err_fixed), np.array(err_adapt)
    return {
        "n_measurements": n, "trials": trials, "noise": noise,
        "fixed_median_logfold": round(float(np.median(ef)), 4),
        "adaptive_median_logfold": round(float(np.median(ea)), 4),
        "fixed_mean_logfold": round(float(ef.mean()), 4),
        "adaptive_mean_logfold": round(float(ea.mean()), 4),
        "median_error_reduction_pct": round(
            100 * (np.median(ef) - np.median(ea)) / (np.median(ef) + 1e-9), 1),
    }
