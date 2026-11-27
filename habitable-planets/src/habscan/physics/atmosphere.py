"""Atmospheric retention: the "cosmic shoreline" with stellar XUV history.

Zahnle & Catling (2017, ApJ 843, 122) showed that Solar System bodies with
and without atmospheres are separated by a line I ∝ v_esc^4, where I is the
(cumulative XUV) irradiation and v_esc the escape velocity. Energy-limited
escape gives exactly this scaling: mass-loss ∝ F_XUV R^3 / (G M), while the
atmospheric inventory scales with surface gravity, so loss/inventory ∝
F_XUV / v_esc^4 at fixed bulk density.

Cumulative XUV fluence
----------------------
Low-mass stars stay in the saturated activity regime (L_XUV/L_bol ~ 1e-3)
for much longer than the Sun, which is the dominant reason M-dwarf planets
are expected to lose atmospheres even when they sit inside the HZ. We model

    f(t) = f_sat                       t <= t_sat
    f(t) = f_sat (t / t_sat)^(-beta)   t >  t_sat

with beta = 1.23 (Ribas et al. 2005, XUV decay of solar analogues) and
t_sat = 0.1 Gyr (M*/M_sun)^-2 (Jackson et al. 2012 give ~0.1 Gyr for
solar-type stars; M dwarfs stay active for Gyr, West et al. 2008), clipped to
[0.01, 10] Gyr. The XUV fluence received by the planet, relative to Earth, is

    F_rel = S_rel * (∫_0^age f dt)_star / (∫_0^4.57 Gyr f dt)_sun

so f_sat cancels. Known simplifications (documented, not hidden): the
pre-main-sequence super-luminous phase of M dwarfs (Luger & Barnes 2015) and
the spread in initial rotation (Johnstone et al. 2021) are not modelled; both
would make M-dwarf planets *less* likely to retain atmospheres.

Calibration
-----------
The boundary constant is calibrated on the Solar System so that Mars, which
retained only a 6 mbar remnant atmosphere, sits on the shoreline (retention
probability 0.5). The transition width is a free parameter (default 0.25 dex).
"""

from __future__ import annotations

import numpy as np

from ..constants import AGE_SUN_GYR, V_ESC_EARTH_KMS

XUV_DECAY_BETA = 1.23
T_SAT_SUN_GYR = 0.1
T_SAT_MASS_EXPONENT = -2.0

# (insolation relative to Earth, escape velocity km/s, retains substantial atmosphere?)
# Insolation = 1 / a[AU]^2. Escape velocities from NASA planetary fact sheets.
SOLAR_SYSTEM_BODIES = {
    "Mercury": (6.673, 4.25, False),
    "Venus": (1.911, 10.36, True),
    "Earth": (1.000, 11.186, True),
    "Moon": (1.000, 2.38, False),
    "Mars": (0.431, 5.03, None),  # on the shoreline: thin remnant atmosphere
    "Io": (0.0369, 2.56, False),
    "Europa": (0.0369, 2.025, False),
    "Ganymede": (0.0369, 2.74, False),
    "Callisto": (0.0369, 2.44, False),
    "Titan": (0.0110, 2.64, True),
    "Triton": (0.00111, 1.455, True),
    "Pluto": (0.00064, 1.21, True),
}


def saturation_time_gyr(stellar_mass_msun) -> np.ndarray:
    m = np.clip(np.asarray(stellar_mass_msun, dtype=float), 0.05, 3.0)
    return np.clip(T_SAT_SUN_GYR * m**T_SAT_MASS_EXPONENT, 0.01, 10.0)


def cumulative_activity(age_gyr, t_sat_gyr, beta=XUV_DECAY_BETA) -> np.ndarray:
    """∫_0^age f(t)/f_sat dt in Gyr for the saturated + power-law decay model."""
    age = np.maximum(np.asarray(age_gyr, dtype=float), 1e-4)
    ts = np.asarray(t_sat_gyr, dtype=float)
    decay = ts / (beta - 1.0) * (1.0 - (np.maximum(age, ts) / ts) ** (1.0 - beta))
    return np.minimum(age, ts) + np.where(age > ts, decay, 0.0)


_SUN_CUMULATIVE = float(cumulative_activity(AGE_SUN_GYR, saturation_time_gyr(1.0)))


def relative_xuv_fluence(insolation_rel, stellar_mass_msun, age_gyr) -> np.ndarray:
    """Lifetime XUV fluence relative to Earth's."""
    cum = cumulative_activity(age_gyr, saturation_time_gyr(stellar_mass_msun))
    return np.asarray(insolation_rel, dtype=float) * cum / _SUN_CUMULATIVE


def escape_velocity_rel(mass_me, radius_re) -> np.ndarray:
    """Escape velocity relative to Earth's: sqrt(M/R) in Earth units."""
    return np.sqrt(np.asarray(mass_me, dtype=float) / np.asarray(radius_re, dtype=float))


def shoreline_ratio(xuv_fluence_rel, v_esc_rel) -> np.ndarray:
    return np.asarray(xuv_fluence_rel, dtype=float) / np.asarray(v_esc_rel, dtype=float) ** 4


def _mars_log_ratio() -> float:
    s, v, _ = SOLAR_SYSTEM_BODIES["Mars"]
    return float(np.log10(s / (v / V_ESC_EARTH_KMS) ** 4))


SHORELINE_LOG10_K = _mars_log_ratio()


def retention_probability(ratio, log10_k=SHORELINE_LOG10_K, width_dex=0.25) -> np.ndarray:
    """Smooth probability that a body keeps a substantial atmosphere."""
    x = (np.log10(np.asarray(ratio, dtype=float)) - log10_k) / width_dex
    return 1.0 / (1.0 + np.exp(np.clip(x, -50, 50)))


def solar_system_table(width_dex=0.25):
    """Rows (name, ratio, P_retain, observed) for validation and reporting."""
    rows = []
    for name, (s, v, obs) in SOLAR_SYSTEM_BODIES.items():
        r = float(shoreline_ratio(s, v / V_ESC_EARTH_KMS))
        rows.append((name, r, float(retention_probability(r, width_dex=width_dex)), obs))
    return rows
