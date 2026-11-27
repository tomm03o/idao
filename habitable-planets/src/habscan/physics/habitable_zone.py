"""Circumstellar habitable zone (HZ) boundaries.

Implements Kopparapu et al. (2014, ApJL 787, L29), which supersedes Kopparapu
et al. (2013) and adds a planet-mass dependence to the runaway-greenhouse
(inner, conservative) edge.

Effective stellar flux at a boundary:

    S_eff = S_eff_sun + a*T + b*T^2 + c*T^3 + d*T^4,   T = Teff - 5780 K

valid for 2600 K <= Teff <= 7200 K. Outside that range the polynomial is
evaluated at the clamped temperature and the caller is told via a flag.

Boundary uncertainty as a probability
-------------------------------------
Climate models do not agree on where the true edges are: the conservative
limits (runaway / maximum greenhouse) and the empirical optimistic limits
(recent Venus / early Mars) bracket the plausible range. If the true inner
edge is taken to be log-uniformly distributed between S_RG and S_RV (and the
outer edge between S_EM and S_MG), the probability that a planet with flux S
lies inside the true HZ is piecewise-linear in log S:

    1                                   S_MG <= S <= S_RG
    log(S_RV/S) / log(S_RV/S_RG)        S_RG <  S <  S_RV
    log(S/S_EM) / log(S_MG/S_EM)        S_EM <  S <  S_MG
    0                                   otherwise

This is :func:`hz_membership`. It replaces the hard 0/1 cut used by
catalogues with a quantity that reflects our actual ignorance.
"""

from __future__ import annotations

import numpy as np

TEFF_MIN = 2600.0
TEFF_MAX = 7200.0
TEFF_REF = 5780.0

# Kopparapu et al. 2014, Table 1: (S_eff_sun, a, b, c, d)
KOPPARAPU_2014 = {
    "recent_venus": (1.776, 2.136e-4, 2.533e-8, -1.332e-11, -3.097e-15),
    "runaway_greenhouse": (1.107, 1.332e-4, 1.580e-8, -8.308e-12, -1.931e-15),
    "maximum_greenhouse": (0.356, 6.171e-5, 1.698e-9, -3.198e-12, -5.575e-16),
    "early_mars": (0.320, 5.547e-5, 1.526e-9, -2.874e-12, -5.011e-16),
    "runaway_greenhouse_5me": (1.188, 1.433e-4, 1.707e-8, -8.968e-12, -2.084e-15),
    "runaway_greenhouse_0.1me": (0.99, 1.209e-4, 1.404e-8, -7.418e-12, -1.713e-15),
}

# Planet masses (Earth masses) at which the runaway-greenhouse limit is tabulated.
_RG_MASSES = np.array([0.1, 1.0, 5.0])
_RG_KEYS = ("runaway_greenhouse_0.1me", "runaway_greenhouse", "runaway_greenhouse_5me")


def teff_out_of_range(teff) -> np.ndarray:
    teff = np.asarray(teff, dtype=float)
    return (teff < TEFF_MIN) | (teff > TEFF_MAX)


def seff_boundary(teff, limit: str) -> np.ndarray:
    """Effective flux (Earth units) at an HZ boundary for stellar Teff (K)."""
    if limit not in KOPPARAPU_2014:
        raise KeyError(f"unknown HZ limit {limit!r}; choose from {sorted(KOPPARAPU_2014)}")
    s0, a, b, c, d = KOPPARAPU_2014[limit]
    t = np.clip(np.asarray(teff, dtype=float), TEFF_MIN, TEFF_MAX) - TEFF_REF
    return s0 + a * t + b * t**2 + c * t**3 + d * t**4


def runaway_greenhouse_seff(teff, planet_mass_me=None) -> np.ndarray:
    """Mass-dependent runaway-greenhouse flux (Kopparapu 2014).

    Linear interpolation in log10(mass) between the 0.1, 1 and 5 M_E fits;
    masses outside [0.1, 5] are clamped (the paper gives no fits beyond).
    """
    teff = np.asarray(teff, dtype=float)
    if planet_mass_me is None:
        return seff_boundary(teff, "runaway_greenhouse")
    m = np.clip(np.asarray(planet_mass_me, dtype=float), _RG_MASSES[0], _RG_MASSES[-1])
    teff, m = np.broadcast_arrays(teff, m)
    s = np.stack([seff_boundary(teff, k) for k in _RG_KEYS], axis=0)
    logm = np.log10(m)
    lm = np.log10(_RG_MASSES)
    # piecewise linear in log mass
    w_hi = logm >= lm[1]
    f_lo = (logm - lm[0]) / (lm[1] - lm[0])
    f_hi = (logm - lm[1]) / (lm[2] - lm[1])
    low_branch = s[0] + f_lo * (s[1] - s[0])
    high_branch = s[1] + f_hi * (s[2] - s[1])
    return np.where(w_hi, high_branch, low_branch)


def hz_limits(teff, planet_mass_me=None) -> dict[str, np.ndarray]:
    """All four boundaries (fluxes in Earth units) for given Teff (and mass)."""
    return {
        "recent_venus": seff_boundary(teff, "recent_venus"),
        "runaway_greenhouse": runaway_greenhouse_seff(teff, planet_mass_me),
        "maximum_greenhouse": seff_boundary(teff, "maximum_greenhouse"),
        "early_mars": seff_boundary(teff, "early_mars"),
    }


def hz_distance_au(luminosity_lsun, seff) -> np.ndarray:
    """Orbital distance (AU) that receives flux ``seff`` from a star of luminosity L."""
    return np.sqrt(np.asarray(luminosity_lsun, dtype=float) / np.asarray(seff, dtype=float))


def in_conservative_hz(s_eff, teff, planet_mass_me=None) -> np.ndarray:
    lim = hz_limits(teff, planet_mass_me)
    s = np.asarray(s_eff, dtype=float)
    return (s <= lim["runaway_greenhouse"]) & (s >= lim["maximum_greenhouse"])


def in_optimistic_hz(s_eff, teff) -> np.ndarray:
    s = np.asarray(s_eff, dtype=float)
    return (s <= seff_boundary(teff, "recent_venus")) & (s >= seff_boundary(teff, "early_mars"))


def hz_membership(s_eff, teff, planet_mass_me=None) -> np.ndarray:
    """Probability of lying inside the true HZ given boundary uncertainty (see module doc)."""
    s = np.asarray(s_eff, dtype=float)
    lim = hz_limits(teff, planet_mass_me)
    s_rv, s_rg = lim["recent_venus"], lim["runaway_greenhouse"]
    s_mg, s_em = lim["maximum_greenhouse"], lim["early_mars"]
    with np.errstate(divide="ignore", invalid="ignore"):
        logs = np.log(s)
        inner = (np.log(s_rv) - logs) / (np.log(s_rv) - np.log(s_rg))
        outer = (logs - np.log(s_em)) / (np.log(s_mg) - np.log(s_em))
    p = np.minimum(np.clip(inner, 0.0, 1.0), np.clip(outer, 0.0, 1.0))
    return np.where(np.isfinite(p), p, 0.0)


def orbit_averaged_flux(s_circular, eccentricity) -> np.ndarray:
    """Time-averaged flux on an eccentric orbit: S / sqrt(1 - e^2) (Williams & Pollard 2002)."""
    e = np.clip(np.asarray(eccentricity, dtype=float), 0.0, 0.99)
    return np.asarray(s_circular, dtype=float) / np.sqrt(1.0 - e**2)
