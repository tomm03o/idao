"""Validated pharmacokinetics / pharmacometrics, backed by numpy + scipy.

* Analytical one- and two-compartment models with first-order oral absorption.
* Non-compartmental analysis (NCA): Cmax, Tmax, AUC (linear-up/log-down
  trapezoid), terminal half-life from log-linear regression, CL/F, Vz/F.
* Four-parameter logistic (Hill) dose-response fitting by nonlinear least
  squares -> IC50/EC50 with a standard error.

References
----------
* Gabrielsson & Weiner, *Pharmacokinetic and Pharmacodynamic Data Analysis*.
* FDA/EMA non-compartmental analysis conventions (linear-up/log-down AUC).
"""

from __future__ import annotations

import math
from typing import Dict, List, Sequence, Tuple

import numpy as np
from scipy.optimize import curve_fit


# --------------------------------------------------------------------------- #
# Structural PK models
# --------------------------------------------------------------------------- #
def conc_one_compartment_oral(
    t: np.ndarray, dose: float, F: float, ka: float, ke: float, V: float
) -> np.ndarray:
    """Plasma concentration for one-compartment first-order oral absorption."""
    t = np.asarray(t, dtype=float)
    if abs(ka - ke) < 1e-9:  # flip-flop guard
        ka = ke + 1e-6
    coef = (F * dose * ka) / (V * (ka - ke))
    return coef * (np.exp(-ke * t) - np.exp(-ka * t))


def conc_two_compartment_iv(
    t: np.ndarray, dose: float, V1: float, k10: float, k12: float, k21: float
) -> np.ndarray:
    """Bi-exponential disposition after an IV bolus (two-compartment)."""
    t = np.asarray(t, dtype=float)
    s = k10 + k12 + k21
    disc = math.sqrt(max(s * s - 4 * k10 * k21, 0.0))
    alpha = 0.5 * (s + disc)
    beta = 0.5 * (s - disc)
    c0 = dose / V1
    a = c0 * (alpha - k21) / (alpha - beta)
    b = c0 * (k21 - beta) / (alpha - beta)
    return a * np.exp(-alpha * t) + b * np.exp(-beta * t)


# --------------------------------------------------------------------------- #
# Non-compartmental analysis
# --------------------------------------------------------------------------- #
def nca(times: Sequence[float], concs: Sequence[float], dose: float | None = None
        ) -> Dict[str, float]:
    """Derive PK parameters from a concentration-time profile, no model assumed."""
    t = np.asarray(times, dtype=float)
    c = np.asarray(concs, dtype=float)
    order = np.argsort(t)
    t, c = t[order], c[order]

    imax = int(np.argmax(c))
    cmax, tmax = float(c[imax]), float(t[imax])

    # AUC(0->last): linear up, log down (regulatory convention)
    auc = 0.0
    for i in range(1, len(t)):
        dt = t[i] - t[i - 1]
        c0, c1 = c[i - 1], c[i]
        if c1 > 0 and c0 > 0 and c1 < c0:
            auc += dt * (c0 - c1) / math.log(c0 / c1)  # log-trapezoid
        else:
            auc += dt * (c0 + c1) / 2.0                # linear-trapezoid

    # terminal half-life: log-linear regression over the tail
    lam_z, half_life = _terminal_slope(t, c)
    auc_inf = auc + (c[-1] / lam_z if lam_z and lam_z > 0 else 0.0)

    out = {
        "cmax": round(cmax, 4),
        "tmax": round(tmax, 4),
        "auc_last": round(auc, 4),
        "auc_inf": round(auc_inf, 4),
        "half_life": round(half_life, 4) if half_life else None,
        "lambda_z": round(lam_z, 5) if lam_z else None,
    }
    if dose:
        out["cl_f"] = round(dose / auc_inf, 5) if auc_inf > 0 else None  # CL/F
        out["vz_f"] = (
            round(dose / (auc_inf * lam_z), 4)
            if auc_inf > 0 and lam_z else None
        )
    return out


def _terminal_slope(t: np.ndarray, c: np.ndarray) -> Tuple[float | None, float | None]:
    imax = int(np.argmax(c))
    tail_t, tail_c = t[imax:], c[imax:]
    mask = tail_c > 0
    tail_t, tail_c = tail_t[mask], tail_c[mask]
    if len(tail_t) < 3:
        return None, None
    slope, _ = np.polyfit(tail_t, np.log(tail_c), 1)
    lam_z = -slope
    if lam_z <= 0:
        return None, None
    return float(lam_z), float(math.log(2) / lam_z)


# --------------------------------------------------------------------------- #
# Dose-response (4-parameter logistic / Hill)
# --------------------------------------------------------------------------- #
def four_pl(x: np.ndarray, bottom: float, top: float, ic50: float, hill: float
            ) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    return bottom + (top - bottom) / (1.0 + (ic50 / np.maximum(x, 1e-12)) ** hill)


def fit_dose_response(
    concentrations: Sequence[float], responses: Sequence[float]
) -> Dict[str, float]:
    """Fit a 4PL curve; return IC50/EC50 and parameter estimates with SE."""
    x = np.asarray(concentrations, dtype=float)
    y = np.asarray(responses, dtype=float)
    if len(x) < 4:
        raise ValueError("need at least 4 points to fit a 4-parameter model")
    p0 = [float(min(y)), float(max(y)), float(np.median(x)), 1.0]
    bounds = ([-50, 0, x.min() * 1e-3, 0.2], [50, 150, x.max() * 1e3, 5.0])
    popt, pcov = curve_fit(four_pl, x, y, p0=p0, bounds=bounds, maxfev=20000)
    perr = np.sqrt(np.diag(pcov))
    resid = y - four_pl(x, *popt)
    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2)) or 1e-12
    return {
        "bottom": round(float(popt[0]), 3),
        "top": round(float(popt[1]), 3),
        "ic50": round(float(popt[2]), 4),
        "ic50_se": round(float(perr[2]), 4),
        "hill_slope": round(float(popt[3]), 3),
        "r_squared": round(1 - ss_res / ss_tot, 4),
    }
