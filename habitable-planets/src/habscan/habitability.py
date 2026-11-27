"""Monte Carlo habitability engine.

For every planet we draw ``n_samples`` joint realisations of the star and the
planet from the catalogue uncertainties and evaluate, per sample,

    w = w_rocky * w_hz * w_atm * w_star

where
    w_rocky  probability that the planet is a rocky (volatile-poor) world
    w_hz     membership in the habitable zone, with HZ-edge uncertainty
             (Kopparapu 2014, mass-dependent inner edge)
    w_atm    probability of keeping an atmosphere (XUV cosmic shoreline)
    w_star   1 for main-sequence hosts, 0 for evolved stars (log g < 3.5)

and P(habitable) = E_samples[w], with importance weights enforcing catalogue
mass limits. Because everything is evaluated per joint sample, correlations
(e.g. a hotter star → brighter star → both more flux *and* a different HZ
edge) are propagated correctly instead of multiplying marginal probabilities.

Planet cases
------------
A  radius and mass measured  rocky ⇔ R ≤ R_silicate(M) (composition test)
B  radius only               w_rocky from the learned P(rocky | R, S);
                             conditional on rocky, M = Zeng(R, CMF),
                             CMF ~ U(0.15, 0.45)
C  mass only (true mass)     w_rocky from P(rocky | M, S); R = Zeng(M, CMF)
D  M sin i only              true mass = M sin i / sin i, isotropic orbits; then C
Upper/lower mass limits are treated as case B with a constraint weight.

All quantities in C/D/B are *conditional on rocky*: non-rocky realisations
have w_rocky = 0 and drop out, so P(hab) = P(rocky) · P(HZ, atm | rocky).
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from .physics import atmosphere as atm
from .physics import habitable_zone as hz
from .physics import planet as pl
from .physics.mass_radius import MassFromRadiusSampler, ck_radius_from_mass, is_rocky_composition, rocky_mass, rocky_radius
from .ml.rocky import composition_offset_samples, summarise_offset
from .sampling import isotropic_sin_inclination, positive_split_lognormal, split_normal, uniform

log = logging.getLogger(__name__)


@dataclass
class HabitabilityConfig:
    n_samples: int = 2000
    seed: int = 20261127
    chunk_size: int = 400
    hz_mode: str = "probabilistic"  # 'probabilistic' | 'conservative' | 'optimistic'
    use_atmosphere: bool = True
    exclude_evolved: bool = True
    evolved_logg: float = 3.5
    point_estimate: bool = False  # ablation: no uncertainty propagation
    shoreline_width_dex: float = 0.25
    shoreline_log10_k: float = atm.SHORELINE_LOG10_K  # calibrated so Mars sits on the shoreline
    cmf_range: tuple = (0.15, 0.45)
    age_prior_gyr: tuple = (0.5, 10.0)
    albedo: float = 0.3
    default_rel_err: dict = field(default_factory=lambda: {
        "st_teff": 0.02, "st_rad": 0.08, "st_mass": 0.10, "st_lum": 0.15, "st_logg": 0.02,
        "st_age": 0.5, "period": 1e-4, "a_au": 0.05, "insol": 0.2, "radius": 0.08, "mass": 0.3,
    })
    default_ecc_abs_err: float = 0.05

    def to_dict(self):
        return asdict(self)


OUTPUT_COLUMNS = [
    "p_habitable", "p_rocky", "p_hz", "p_hz_conservative", "p_hz_optimistic", "p_atm_retention", "p_main_sequence",
    "p_tidally_locked", "s_eff_med", "s_eff_p16", "s_eff_p84", "teq_med", "radius_med", "mass_med",
    "mass_forecast_med", "radius_forecast_med", "esi_med", "esi_p16", "esi_p84", "shoreline_log_ratio_med",
    "xuv_fluence_rel_med", "hz_con_inner_au", "hz_con_outer_au", "case", "flux_source", "teff_extrapolated",
    "evaluable",
]


class HabitabilityEngine:
    def __init__(self, config: HabitabilityConfig, rocky_model):
        self.cfg = config
        self.rocky = rocky_model
        self._m_from_r = MassFromRadiusSampler()

    # -- samplers that honour point-estimate mode -----------------------------
    def _pos(self, df, col, rng, n):
        v = df[col].to_numpy(float)
        if self.cfg.point_estimate:
            return np.repeat(v[:, None], n, axis=1)
        rel = self.cfg.default_rel_err.get(col, 0.1)
        return positive_split_lognormal(v, df[f"{col}_e1"].to_numpy(float), df[f"{col}_e2"].to_numpy(float), n, rng,
                                        default_rel=rel)

    def _lin(self, df, col, rng, n, absolute_default=None):
        v = df[col].to_numpy(float)
        if self.cfg.point_estimate:
            return np.repeat(v[:, None], n, axis=1)
        rel = self.cfg.default_rel_err.get(col, 0.1)
        return split_normal(v, df[f"{col}_e1"].to_numpy(float), df[f"{col}_e2"].to_numpy(float), n, rng,
                            default_rel=rel, absolute_default=absolute_default)

    # -------------------------------------------------------------------------
    def evaluate(self, planets: pd.DataFrame) -> pd.DataFrame:
        out = []
        n = len(planets)
        for start in range(0, n, self.cfg.chunk_size):
            chunk = planets.iloc[start:start + self.cfg.chunk_size]
            # independent, reproducible stream per chunk
            rng = np.random.default_rng([self.cfg.seed, start])
            with warnings.catch_warnings(), np.errstate(all="ignore"):
                # all-NaN rows (planets lacking data) are expected and flagged via `evaluable`
                warnings.simplefilter("ignore", RuntimeWarning)
                out.append(self._evaluate_chunk(chunk, rng))
            if (start // self.cfg.chunk_size) % 10 == 0:
                log.info("habitability: %d / %d", min(start + self.cfg.chunk_size, n), n)
        res = pd.concat(out, axis=0)
        res.index = planets.index
        return res

    def _evaluate_chunk(self, df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
        cfg = self.cfg
        n = 1 if cfg.point_estimate else cfg.n_samples
        k = len(df)

        # ---------------- star ----------------
        teff = self._lin(df, "st_teff", rng, n)
        rstar = self._pos(df, "st_rad", rng, n)
        mstar = self._pos(df, "st_mass", rng, n)
        logg = self._lin(df, "st_logg", rng, n)
        # stellar mass fallbacks: log g + R, then dwarf relation
        m_logg = pl.mass_from_logg_radius(logg, rstar)
        m_ms = pl.main_sequence_mass_from_radius(rstar)
        mstar = np.where(np.isfinite(mstar), mstar, np.where(np.isfinite(m_logg), m_logg, m_ms))
        logg = np.where(np.isfinite(logg), logg,
                        np.log10(np.maximum(mstar, 1e-6)) - 2 * np.log10(np.maximum(rstar, 1e-6)) + 4.438)
        lum = self._pos(df, "st_lum", rng, n)
        lum = np.where(np.isfinite(lum), lum, pl.luminosity_from_radius_teff(rstar, teff))

        age = self._pos(df, "st_age", rng, n)
        t_ms = pl.main_sequence_lifetime_gyr(np.nanmedian(mstar, axis=1) if n > 1 else mstar[:, 0])
        hi = np.clip(np.where(np.isfinite(t_ms), t_ms, cfg.age_prior_gyr[1]), cfg.age_prior_gyr[0] + 0.1,
                     cfg.age_prior_gyr[1])
        if cfg.point_estimate:
            age_prior = np.repeat(((cfg.age_prior_gyr[0] + hi) / 2)[:, None], n, axis=1)
        else:
            age_prior = uniform(np.full(k, cfg.age_prior_gyr[0]), hi, n, rng)
        age = np.where(np.isfinite(age), age, age_prior)

        # ---------------- orbit & irradiation ----------------
        period = self._pos(df, "period", rng, n)
        a = self._pos(df, "a_au", rng, n)
        a = np.where(np.isfinite(a), a, pl.semi_major_axis_au(period, mstar))
        s_phys = pl.insolation(lum, a)
        s_cat = self._pos(df, "insol", rng, n)
        use_phys = np.isfinite(s_phys).all(axis=1)
        s = np.where(use_phys[:, None], s_phys, s_cat)
        flux_source = np.where(use_phys, "stellar", np.where(np.isfinite(s_cat).all(axis=1), "catalogue", "none"))

        ecc_v = df["ecc"].to_numpy(float)
        has_ecc = np.isfinite(ecc_v)
        if cfg.point_estimate:
            ecc = np.repeat(np.where(has_ecc, ecc_v, 0.0)[:, None], n, axis=1)
        else:
            ecc = split_normal(np.where(has_ecc, ecc_v, 0.0), df["ecc_e1"].to_numpy(float),
                               df["ecc_e2"].to_numpy(float), n, rng, default_rel=0.0,
                               absolute_default=cfg.default_ecc_abs_err)
            ecc = np.where(has_ecc[:, None], ecc, 0.0)
        ecc = np.clip(ecc, 0.0, 0.95)
        s_eff = hz.orbit_averaged_flux(s, ecc)

        # ---------------- planet ----------------
        r_meas = self._pos(df, "radius", rng, n)
        m_meas = self._pos(df, "mass", rng, n)
        kind = df["mass_kind"].to_numpy(str)
        rad_ok = df["radius_measured"].to_numpy(bool) & np.isfinite(df["radius"].to_numpy(float))
        mass_val = kind == "measured"
        if cfg.point_estimate:
            sini = np.ones((k, n))
            cmf = np.full((k, n), np.mean(cfg.cmf_range))
        else:
            sini = isotropic_sin_inclination((k, n), rng)
            cmf = rng.uniform(*cfg.cmf_range, size=(k, n))
        m_true = np.where((kind == "msini")[:, None], m_meas / sini, m_meas)

        case = np.full(k, "none", dtype=object)
        case[rad_ok & mass_val] = "A"
        case[rad_ok & ~mass_val] = "B"
        case[~rad_ok & (mass_val)] = "C"
        case[~rad_ok & (kind == "msini")] = "D"

        caseA = (case == "A")[:, None]
        caseB = (case == "B")[:, None]
        caseCD = np.isin(case, ["C", "D"])[:, None]

        # rocky weights
        w_rocky = np.zeros((k, n))
        # case A: posterior of the composition mixture (deconvolves measurement error)
        ia = np.flatnonzero(case == "A")
        if ia.size:
            if cfg.point_estimate:
                p_a = is_rocky_composition(m_meas[ia], r_meas[ia]).astype(float)[:, 0]
            else:
                d_med, d_sig = summarise_offset(composition_offset_samples(m_meas[ia], r_meas[ia]))
                s_med = np.nanmedian(s_eff[ia], axis=1)
                p_a = self.rocky.posterior_measured(d_med, d_sig, np.nanmedian(r_meas[ia], axis=1), s_med)
            w_rocky[ia] = np.nan_to_num(p_a)[:, None]
        p_r = self.rocky.p_given_radius(np.where(caseB, r_meas, np.nan), s_eff)
        w_rocky = np.where(caseB, np.nan_to_num(p_r), w_rocky)
        p_m = self.rocky.p_given_mass(np.where(caseCD, m_true, np.nan), s_eff)
        w_rocky = np.where(caseCD, np.nan_to_num(p_m), w_rocky)

        # rocky-conditional physical size
        radius = np.where(caseA | caseB, r_meas, np.where(caseCD, rocky_radius(m_true, cmf), np.nan))
        mass = np.where(caseA, m_meas, np.where(caseB, rocky_mass(r_meas, cmf), np.where(caseCD, m_true, np.nan)))

        # constraint weights from mass limits (case B with limits)
        w_c = np.ones((k, n))
        upper = (kind == "upper")[:, None] & caseB
        lower = (kind == "lower")[:, None] & caseB
        lim = df["mass"].to_numpy(float)[:, None]
        w_c = np.where(upper, (mass <= lim).astype(float), w_c)
        w_c = np.where(lower, (mass >= lim).astype(float), w_c)
        bad = w_c.sum(axis=1) == 0  # limit incompatible with a rocky body: ignore the constraint
        w_c[bad] = 1.0

        # forecasts of the *unconditional* missing quantity (informational)
        mass_fc = np.where(caseB, self._m_from_r.sample(np.where(caseB, r_meas, 1.0), rng), np.nan)
        radius_fc = np.where(caseCD, ck_radius_from_mass(np.where(caseCD, m_true, 1.0),
                                                         None if cfg.point_estimate else rng), np.nan)

        # ---------------- habitable zone ----------------
        p_hz_cons = hz.in_conservative_hz(s_eff, teff, mass).astype(float)
        p_hz_opt = hz.in_optimistic_hz(s_eff, teff).astype(float)
        if cfg.hz_mode == "probabilistic":
            w_hz = hz.hz_membership(s_eff, teff, mass)
        elif cfg.hz_mode == "conservative":
            w_hz = p_hz_cons
        elif cfg.hz_mode == "optimistic":
            w_hz = p_hz_opt
        else:
            raise ValueError(cfg.hz_mode)

        # ---------------- atmosphere ----------------
        v_rel = atm.escape_velocity_rel(mass, radius)
        f_xuv = atm.relative_xuv_fluence(s_eff, mstar, age)
        ratio = atm.shoreline_ratio(f_xuv, v_rel)
        w_atm = atm.retention_probability(ratio, log10_k=cfg.shoreline_log10_k, width_dex=cfg.shoreline_width_dex)
        w_atm = np.where(np.isfinite(w_atm), w_atm, 0.0)

        # ---------------- star ----------------
        w_star = (logg >= cfg.evolved_logg).astype(float) if cfg.exclude_evolved else np.ones((k, n))

        # ---------------- combine ----------------
        w_total = w_rocky * w_hz * w_star * (w_atm if cfg.use_atmosphere else 1.0)
        valid = np.isfinite(s_eff) & np.isfinite(teff) & np.isfinite(w_total)
        wc = np.where(valid, w_c, 0.0)
        norm = wc.sum(axis=1)
        evaluable = (norm > 0) & (case != "none")
        norm_safe = np.where(norm > 0, norm, 1.0)

        def wmean(x):
            x = np.where(valid, np.nan_to_num(x), 0.0)
            return np.where(evaluable, (wc * x).sum(axis=1) / norm_safe, np.nan)

        def q(x, p):
            x = np.where(valid, x, np.nan)
            with np.errstate(all="ignore"):
                r = np.nanpercentile(x, p, axis=1) if n > 1 else x[:, 0]
            return np.where(evaluable, r, np.nan)

        t_lock = pl.tidal_locking_time_gyr(a, mstar, mass, radius)
        locked = (t_lock < age).astype(float)
        esi = pl.earth_similarity_index(radius, s_eff)
        teq = pl.equilibrium_temperature(s_eff, albedo=cfg.albedo)

        teff_med = q(teff, 50)
        lum_med = q(lum, 50)
        res = pd.DataFrame({
            "p_habitable": wmean(w_total),
            "p_rocky": wmean(w_rocky),
            "p_hz": wmean(w_hz),
            "p_hz_conservative": wmean(p_hz_cons),
            "p_hz_optimistic": wmean(p_hz_opt),
            "p_atm_retention": wmean(w_atm),
            "p_main_sequence": wmean(w_star),
            "p_tidally_locked": wmean(locked),
            "s_eff_med": q(s_eff, 50), "s_eff_p16": q(s_eff, 16), "s_eff_p84": q(s_eff, 84),
            "teq_med": q(teq, 50),
            "radius_med": q(radius, 50), "mass_med": q(mass, 50),
            "mass_forecast_med": q(mass_fc, 50), "radius_forecast_med": q(radius_fc, 50),
            "esi_med": q(esi, 50), "esi_p16": q(esi, 16), "esi_p84": q(esi, 84),
            "shoreline_log_ratio_med": q(np.log10(ratio), 50),
            "xuv_fluence_rel_med": q(f_xuv, 50),
            "hz_con_inner_au": hz.hz_distance_au(lum_med, hz.seff_boundary(teff_med, "runaway_greenhouse")),
            "hz_con_outer_au": hz.hz_distance_au(lum_med, hz.seff_boundary(teff_med, "maximum_greenhouse")),
            "case": case,
            "flux_source": flux_source,
            "teff_extrapolated": hz.teff_out_of_range(teff_med),
            "evaluable": evaluable,
        }, index=df.index)
        return res[OUTPUT_COLUMNS]


def evaluate(planets: pd.DataFrame, rocky_model, config: HabitabilityConfig | None = None) -> pd.DataFrame:
    return HabitabilityEngine(config or HabitabilityConfig(), rocky_model).evaluate(planets)
