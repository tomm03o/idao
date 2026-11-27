"""Monte Carlo sampling of catalogue measurements with asymmetric errors.

Catalogues report value (+err1, err2) with err2 <= 0. We draw from a split
(two-piece) normal. Strictly positive quantities are sampled in log space with
log-errors log(1 + err1/v) and -log(1 - |err2|/v), which keeps samples
positive and reduces to the split normal for small relative errors.

All samplers are vectorised: inputs are shape (n,), outputs (n, n_samples).
Rows with a NaN value produce NaN samples.
"""

from __future__ import annotations

import numpy as np


def _clean_errors(value, err_plus, err_minus, default_rel):
    v = np.asarray(value, dtype=float)
    ep = np.abs(np.asarray(err_plus, dtype=float)) if err_plus is not None else np.full_like(v, np.nan)
    em = np.abs(np.asarray(err_minus, dtype=float)) if err_minus is not None else np.full_like(v, np.nan)
    # symmetric fallback when only one side is reported
    ep = np.where(np.isfinite(ep), ep, em)
    em = np.where(np.isfinite(em), em, ep)
    default = np.abs(v) * default_rel
    ep = np.where(np.isfinite(ep) & (ep > 0), ep, default)
    em = np.where(np.isfinite(em) & (em > 0), em, default)
    return v, ep, em


def split_normal(value, err_plus, err_minus, n_samples, rng, default_rel=0.1, absolute_default=None):
    """Two-piece normal around ``value``. Each side gets probability mass 1/2."""
    v, ep, em = _clean_errors(value, err_plus, err_minus, default_rel)
    if absolute_default is not None:
        ep = np.where(ep > 0, ep, absolute_default)
        em = np.where(em > 0, em, absolute_default)
    z = np.abs(rng.standard_normal((v.size, n_samples)))
    side = rng.random((v.size, n_samples)) < 0.5
    out = np.where(side, v[:, None] + z * ep[:, None], v[:, None] - z * em[:, None])
    return out


def positive_split_lognormal(value, err_plus, err_minus, n_samples, rng, default_rel=0.1, max_log_sigma=2.0):
    """Split normal in ln-space for strictly positive quantities."""
    v, ep, em = _clean_errors(value, err_plus, err_minus, default_rel)
    with np.errstate(divide="ignore", invalid="ignore"):
        sp = np.log1p(ep / v)
        frac = np.clip(em / v, 0.0, 0.999)
        sm = -np.log1p(-frac)
    sp = np.clip(np.where(np.isfinite(sp), sp, default_rel), 1e-6, max_log_sigma)
    sm = np.clip(np.where(np.isfinite(sm), sm, default_rel), 1e-6, max_log_sigma)
    z = np.abs(rng.standard_normal((v.size, n_samples)))
    side = rng.random((v.size, n_samples)) < 0.5
    with np.errstate(divide="ignore", invalid="ignore"):
        lv = np.log(v)[:, None]
    out = np.exp(np.where(side, lv + z * sp[:, None], lv - z * sm[:, None]))
    out[~(v > 0)] = np.nan
    return out


def isotropic_sin_inclination(shape, rng, min_sin=0.05):
    """sin(i) for isotropically oriented orbits (cos i ~ U(0,1)).

    The tail sin i -> 0 corresponds to arbitrarily massive companions; it is
    truncated at ``min_sin`` (true mass <= 20 × M sin i), which removes
    stellar-mass companions that would not be in a planet catalogue.
    """
    cos_i = rng.random(shape) * np.sqrt(1.0 - min_sin**2)
    return np.sqrt(1.0 - cos_i**2)


def uniform(low, high, n_samples, rng):
    low = np.asarray(low, dtype=float)
    high = np.asarray(high, dtype=float)
    u = rng.random((low.size, n_samples))
    return low[:, None] + u * (high - low)[:, None]
