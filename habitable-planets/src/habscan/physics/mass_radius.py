"""Mass-radius relations.

* Chen & Kipping (2017, ApJ 834, 17) probabilistic broken power law
  ("Forecaster"): log10 R = C_i + S_i log10 M with intrinsic Gaussian scatter
  sigma_i (dex in radius) in four regimes (Terran, Neptunian, Jovian, stellar).
  Used to forecast radius from mass and, through a full Bayesian inversion on
  a grid, mass from radius.

* Zeng, Sasselov & Jacobsen (2016, ApJ 819, 127) two-layer rocky planets:
  R = (1.07 - 0.21 CMF) M^(1/3.7) (Earth units), CMF = core mass fraction.
  CMF = 0 is the pure-silicate (MgSiO3) curve: a planet larger than that at
  its mass needs volatiles (water and/or H/He) and is not a bare rocky world.
"""

from __future__ import annotations

import numpy as np

from ..constants import M_JUP_IN_EARTH, M_SUN, M_EARTH

# --- Chen & Kipping 2017 (posterior medians, Table 1) ------------------------
CK_SLOPES = np.array([0.2790, 0.589, -0.044, 0.881])
CK_SCATTER_DEX = np.array([0.0403, 0.146, 0.0737, 0.0447])
CK_C_TERRAN = 0.00346
# Transition masses: 2.04 M_E, 0.414 M_J, 0.0800 M_sun -> log10(M/M_E)
CK_TRANSITIONS = np.log10(np.array([2.04, 0.414 * M_JUP_IN_EARTH, 0.0800 * M_SUN / M_EARTH]))


def _ck_offsets() -> np.ndarray:
    c = np.empty(4)
    c[0] = CK_C_TERRAN
    for i in range(1, 4):
        # continuity at transition i-1
        c[i] = c[i - 1] + (CK_SLOPES[i - 1] - CK_SLOPES[i]) * CK_TRANSITIONS[i - 1]
    return c


CK_OFFSETS = _ck_offsets()


def _ck_regime(log_m: np.ndarray) -> np.ndarray:
    return np.searchsorted(CK_TRANSITIONS, log_m, side="right")


def ck_mean_log_radius(log_mass_me) -> np.ndarray:
    """Mean log10 R (R_E) given log10 M (M_E) for Chen & Kipping 2017."""
    lm = np.asarray(log_mass_me, dtype=float)
    k = _ck_regime(lm)
    return CK_OFFSETS[k] + CK_SLOPES[k] * lm


def ck_scatter(log_mass_me) -> np.ndarray:
    return CK_SCATTER_DEX[_ck_regime(np.asarray(log_mass_me, dtype=float))]


def ck_radius_from_mass(mass_me, rng: np.random.Generator | None = None) -> np.ndarray:
    """Radius (R_E) from mass; with ``rng`` draws the intrinsic scatter, else the mean relation."""
    lm = np.log10(np.asarray(mass_me, dtype=float))
    mu = ck_mean_log_radius(lm)
    if rng is None:
        return 10.0**mu
    return 10.0 ** (mu + ck_scatter(lm) * rng.standard_normal(lm.shape))


class MassFromRadiusSampler:
    """Draw M | R under the Chen & Kipping relation by exact grid inversion.

    p(log M | log R) ∝ N(log R; mu(log M), sigma(log M)) * prior(log M),
    with a log-uniform prior on [10^log_m_min, 10^log_m_max] M_E.

    For speed, the posterior CDF is tabulated on a grid of log R values; each
    radius sample is snapped to the nearest log R node (node spacing is much
    smaller than the relation's intrinsic scatter, so the error is negligible)
    and inverted with a single global ``searchsorted`` by offsetting each row's
    CDF by its row index (rows become one monotone sequence).
    """

    def __init__(self, log_m_min=-2.0, log_m_max=5.0, n_mass=1400, log_r_min=-0.7, log_r_max=1.8, n_radius=600):
        self.log_m = np.linspace(log_m_min, log_m_max, n_mass)
        self.log_r = np.linspace(log_r_min, log_r_max, n_radius)
        self.dlog_r = self.log_r[1] - self.log_r[0]
        mu = ck_mean_log_radius(self.log_m)[None, :]
        sig = ck_scatter(self.log_m)[None, :]
        z = (self.log_r[:, None] - mu) / sig
        like = np.exp(-0.5 * z**2) / sig
        cdf = np.cumsum(like, axis=1)
        cdf /= cdf[:, -1:]
        self._n_mass = n_mass
        self._flat = (cdf + np.arange(n_radius)[:, None]).ravel()
        self._dlm = self.log_m[1] - self.log_m[0]

    def sample(self, radius_re, rng: np.random.Generator) -> np.ndarray:
        r = np.asarray(radius_re, dtype=float)
        lr = np.log10(np.clip(r, 10**self.log_r[0], 10**self.log_r[-1]))
        row = np.rint((lr - self.log_r[0]) / self.dlog_r).astype(np.int64)
        u = rng.random(r.shape)
        idx = np.searchsorted(self._flat, (row + u).ravel()).reshape(r.shape)
        col = np.clip(idx - row * self._n_mass, 0, self._n_mass - 1)
        # jitter within the grid cell to avoid discreteness
        lm = self.log_m[col] + (rng.random(r.shape) - 0.5) * self._dlm
        return 10.0**lm


# --- Zeng et al. 2016 rocky planets -----------------------------------------
EARTH_CMF = 0.325


def rocky_radius(mass_me, cmf=EARTH_CMF) -> np.ndarray:
    return (1.07 - 0.21 * np.asarray(cmf, dtype=float)) * np.asarray(mass_me, dtype=float) ** (1.0 / 3.7)


def rocky_mass(radius_re, cmf=EARTH_CMF) -> np.ndarray:
    return (np.asarray(radius_re, dtype=float) / (1.07 - 0.21 * np.asarray(cmf, dtype=float))) ** 3.7


def pure_silicate_radius(mass_me) -> np.ndarray:
    """Upper radius envelope for a volatile-free planet (CMF = 0)."""
    return rocky_radius(mass_me, 0.0)


def is_rocky_composition(mass_me, radius_re, tolerance=0.0) -> np.ndarray:
    """True where radius does not exceed the pure-silicate radius at that mass."""
    return np.asarray(radius_re, dtype=float) <= pure_silicate_radius(mass_me) * (1.0 + tolerance)
