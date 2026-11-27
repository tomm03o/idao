"""Planet-level derived quantities: flux, temperature, ESI, tidal locking, stellar helpers."""

from __future__ import annotations

import numpy as np

from ..constants import AU, DAY, G, GYR, LOGG_SUN, M_EARTH, M_SUN, R_EARTH, T_SUN, TEQ_EARTH_ZERO_ALBEDO, YEAR_DAYS


# --- stellar helpers ---------------------------------------------------------
def luminosity_from_radius_teff(radius_rsun, teff_k) -> np.ndarray:
    """Stefan-Boltzmann: L/L_sun = (R/R_sun)^2 (Teff/T_sun)^4."""
    return np.asarray(radius_rsun, dtype=float) ** 2 * (np.asarray(teff_k, dtype=float) / T_SUN) ** 4


def mass_from_logg_radius(logg_cgs, radius_rsun) -> np.ndarray:
    """M/M_sun = 10^(logg - logg_sun) (R/R_sun)^2."""
    return 10.0 ** (np.asarray(logg_cgs, dtype=float) - LOGG_SUN) * np.asarray(radius_rsun, dtype=float) ** 2


def main_sequence_mass_from_radius(radius_rsun) -> np.ndarray:
    """Rough dwarf-star mass-radius inversion (R ∝ M^0.8 for M > 1, R ≈ M below).

    Only used as a last resort when neither a mass nor log g is available.
    """
    r = np.asarray(radius_rsun, dtype=float)
    return np.where(r > 1.0, r ** (1.0 / 0.8), r)


def main_sequence_lifetime_gyr(stellar_mass_msun) -> np.ndarray:
    return 10.0 * np.asarray(stellar_mass_msun, dtype=float) ** -2.5


# --- orbit and irradiation ---------------------------------------------------
def semi_major_axis_au(period_days, stellar_mass_msun) -> np.ndarray:
    """Kepler's third law, planet mass neglected."""
    p_yr = np.asarray(period_days, dtype=float) / YEAR_DAYS
    return np.cbrt(np.asarray(stellar_mass_msun, dtype=float) * p_yr**2)


def insolation(luminosity_lsun, a_au) -> np.ndarray:
    """Bolometric flux relative to Earth's."""
    return np.asarray(luminosity_lsun, dtype=float) / np.asarray(a_au, dtype=float) ** 2


def equilibrium_temperature(insolation_rel, albedo=0.0, redistribution=0.25) -> np.ndarray:
    """T_eq for given flux (Earth units). redistribution = 1/4 full, 2/3 dayside only."""
    s = np.asarray(insolation_rel, dtype=float)
    return TEQ_EARTH_ZERO_ALBEDO * (s * (1.0 - albedo) * redistribution / 0.25) ** 0.25


# --- similarity index --------------------------------------------------------
def earth_similarity_index(radius_re, insolation_rel) -> np.ndarray:
    """ESI from radius and stellar flux, as used by the PHL Habitable Worlds Catalog."""
    r = np.asarray(radius_re, dtype=float)
    s = np.asarray(insolation_rel, dtype=float)
    return 1.0 - np.sqrt(0.5 * (((s - 1.0) / (s + 1.0)) ** 2 + ((r - 1.0) / (r + 1.0)) ** 2))


# --- tides -------------------------------------------------------------------
def tidal_locking_time_gyr(
    a_au,
    stellar_mass_msun,
    planet_mass_me,
    planet_radius_re,
    initial_period_hours=12.0,
    q_factor=100.0,
    k2=0.3,
    inertia_factor=0.33,
) -> np.ndarray:
    """Spin-down time to synchronous rotation (Gladman et al. 1996, Icarus 122, 166).

    t = w a^6 I Q / (3 G M*^2 k2 R^5), I = alpha m R^2.
    Q ~ 100 and k2 ~ 0.3 are Earth-like; uncertainties are orders of magnitude,
    so use the result as an order-of-magnitude indicator.
    """
    a = np.asarray(a_au, dtype=float) * AU
    ms = np.asarray(stellar_mass_msun, dtype=float) * M_SUN
    mp = np.asarray(planet_mass_me, dtype=float) * M_EARTH
    rp = np.asarray(planet_radius_re, dtype=float) * R_EARTH
    omega = 2.0 * np.pi / (initial_period_hours * 3600.0)
    inertia = inertia_factor * mp * rp**2
    t = omega * a**6 * inertia * q_factor / (3.0 * G * ms**2 * k2 * rp**5)
    return t / GYR


def transit_duration_circular_hours(period_days, stellar_radius_rsun, stellar_mass_msun) -> np.ndarray:
    """Central-transit duration for a circular orbit: T ≈ P R* / (π a)."""
    a = semi_major_axis_au(period_days, stellar_mass_msun) * AU
    rs = np.asarray(stellar_radius_rsun, dtype=float) * 6.957e8
    return np.asarray(period_days, dtype=float) * DAY * rs / (np.pi * a) / 3600.0
