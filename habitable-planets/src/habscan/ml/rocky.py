"""Data-driven probability that a planet is rocky, learned from planets with both mass and radius.

Why learn this?
---------------
Most small planets have a radius *or* a mass, not both. Habitability needs to
know whether the planet is a rocky world, not a mini-Neptune with an H/He or
water envelope. The usual shortcut is a fixed radius cut (1.6 R_E,
Rogers 2015). It ignores that envelopes are stripped more easily on strongly
irradiated orbits (photo-evaporation, core-powered mass loss: the radius
valley).

Why a deconvolution mixture and not a classifier on "is it below the silicate line"?
------------------------------------------------------------------------------------
For one planet the composition offset

    delta = log10( R / R_earthlike(M) ),   R_earthlike = Zeng et al. 2016 with CMF = 0.325

is measured with an error sigma that is often as large as the whole rocky
range (CMF 0 → 0.7 spans delta ≈ +0.03 → -0.03 dex). Labelling each planet
with P(R <= R_silicate) under flat priors mistakes measurement noise for
composition: a perfect Earth twin measured at 5 % in R and 20 % in M would get
only ≈ 0.8. The fix is a two-component mixture in delta, convolved with every
planet's own error:

    p(delta_i | x_i) = pi(x_i) N(delta_i; mu_r, tau_r^2 + sigma_i^2)
                     + (1 - pi(x_i)) N(delta_i; mu_g, tau_g^2 + sigma_i^2)

* rocky component fixed by physics: mu_r = 0, tau_r = 0.02 dex
  (CMF 0.1 - 0.5 plus Zeng-model systematics);
* volatile-rich component (mu_g, tau_g) learned;
* gate pi(x) = P(rocky | x) is a logistic model on x = (log size[, log S]):
  this gate *is* the population-level probability we want.

It is fitted by EM (E-step responsibilities, M-step weighted logistic
regression on the gate and weighted heteroscedastic Gaussian MLE for the
volatile component). Candidate gates are compared on grouped cross-validated
held-out log-likelihood of delta, a proper score that needs no labels.

Extrapolation guard
-------------------
Training planets are mostly hot (median S ~ 70), HZ planets have S ~ 0.2 - 2.
Only gates that are monotone decreasing in size over S in [0.05, 50] are
eligible. The flux slope is extrapolated linearly in log S, in the direction
predicted by mass-loss physics (less stripping at low S); this is stated in
the report.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import PolynomialFeatures, StandardScaler

from ..physics.mass_radius import EARTH_CMF, ck_radius_from_mass, rocky_radius
from ..sampling import positive_split_lognormal

log = logging.getLogger(__name__)

MU_ROCKY = 0.0
TAU_ROCKY = 0.02
_SQRT2PI = np.sqrt(2 * np.pi)


def _npdf(x, mu, sd):
    return np.exp(-0.5 * ((x - mu) / sd) ** 2) / (sd * _SQRT2PI)


def composition_offset_samples(mass_samples, radius_samples) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.log10(radius_samples / rocky_radius(mass_samples, EARTH_CMF))


def summarise_offset(delta_samples) -> tuple[np.ndarray, np.ndarray]:
    p16, p50, p84 = np.nanpercentile(delta_samples, [16, 50, 84], axis=1)
    return p50, np.maximum(0.5 * (p84 - p16), 1e-3)


def composition_offsets(df: pd.DataFrame, n_samples=4000, seed=0):
    rng = np.random.default_rng(seed)
    r = positive_split_lognormal(df["radius"], df["radius_e1"], df["radius_e2"], n_samples, rng)
    m = positive_split_lognormal(df["mass"], df["mass_e1"], df["mass_e2"], n_samples, rng)
    return summarise_offset(composition_offset_samples(m, r))


def select_training_planets(df: pd.DataFrame, max_rel_radius_err=0.15, max_rel_mass_err=0.35,
                            radius_range=(0.3, 4.5), max_mass=60.0, exclude_ttv=False) -> pd.DataFrame:
    """Confirmed transiting planets with measured mass at >~3 sigma and radius at <= 15 %.

    ``exclude_ttv`` drops planets in systems with transit-timing variations: TTV masses are known to be
    systematically lower-density than RV masses at the same radius (e.g. Steffen 2016; Mills & Mazeh
    2017), so including or excluding them brackets that selection effect.
    """
    d = df[(df["source"] == "confirmed") & df["radius_measured"] & (df["mass_kind"] == "measured")].copy()
    rel_r = np.maximum(d["radius_e1"].abs(), d["radius_e2"].abs()) / d["radius"]
    rel_m = np.maximum(d["mass_e1"].abs(), d["mass_e2"].abs()) / d["mass"]
    keep = (rel_r <= max_rel_radius_err) & (rel_m <= max_rel_mass_err)
    keep &= d["radius"].between(*radius_range) & (d["mass"] <= max_mass)
    keep &= ~d["controversial"]
    if exclude_ttv and "ttv_flag" in d:
        keep &= ~d["ttv_flag"].astype(bool)
    d = d[keep]
    s = d["insol"].copy()
    fill = s.isna() & d["st_lum"].notna() & d["a_au"].notna()
    s[fill] = d.loc[fill, "st_lum"] / d.loc[fill, "a_au"] ** 2
    d["insol_used"] = s
    return d[d["insol_used"] > 0]


# ---------------------------------------------------------------------------
def _features(size, flux, use_flux):
    x = np.log10(np.asarray(size, dtype=float)).reshape(-1, 1)
    if use_flux:
        x = np.hstack([x, np.log10(np.asarray(flux, dtype=float)).reshape(-1, 1)])
    return x


def _fit_soft(est, x, p):
    """Weighted logistic fit on soft labels by row duplication."""
    xx = np.vstack([x, x])
    yy = np.r_[np.ones(len(x)), np.zeros(len(x))]
    ww = np.r_[p, 1 - p] + 1e-9
    est.fit(xx, yy, **{f"{est.steps[-1][0]}__sample_weight": ww})
    return est


@dataclass
class GateSpec:
    name: str
    kind: str  # 'rogers' | 'logistic'
    use_flux: bool = False
    degree: int = 1
    clamp_flux: bool = False  # True: no extrapolation of the flux trend beyond the training support

    def make(self):
        steps = [StandardScaler()]
        if self.degree > 1:
            steps = [PolynomialFeatures(self.degree, include_bias=False), StandardScaler()]
        return make_pipeline(*steps, LogisticRegression(C=10.0, max_iter=5000))


GATES = [
    GateSpec("rogers2015_fixed", "rogers"),
    GateSpec("logistic_size", "logistic"),
    GateSpec("logistic_size_flux", "logistic", use_flux=True),
    GateSpec("logistic_size_flux_clamped", "logistic", use_flux=True, clamp_flux=True),
    GateSpec("logistic_size_flux_quadratic", "logistic", use_flux=True, degree=2),
    GateSpec("logistic_size_flux_quadratic_clamped", "logistic", use_flux=True, degree=2, clamp_flux=True),
]
FLUX_SUPPORT_PERCENTILES = (5.0, 95.0)
LOW_FLUX_SCORE_THRESHOLD = 3.0  # S below which held-out log-likelihood is also reported separately


@dataclass
class RockyRegressor:
    """Population P(rocky | size, flux) plus the volatile-component parameters."""

    variable: str  # 'radius' | 'mass'
    spec: GateSpec = field(default_factory=lambda: GATES[0])
    gate: object = None
    mu_g: float = 0.2
    tau_g: float = 0.1
    rogers_center: float = 1.6
    rogers_width: float = 0.08
    cv_scores: dict = field(default_factory=dict)
    n_train: int = 0
    n_em_iter: int = 0
    flux_bounds: tuple | None = None

    @property
    def chosen(self) -> str:
        return self.spec.name

    def _rogers(self, size):
        r = size if self.variable == "radius" else ck_radius_from_mass(size)
        return 1.0 / (1.0 + np.exp(np.clip((r - self.rogers_center) / self.rogers_width, -50, 50)))

    def predict(self, size, flux) -> np.ndarray:
        size = np.asarray(size, dtype=float)
        if self.gate is None:
            return self._rogers(size)
        shape = size.shape
        flux = np.broadcast_to(np.asarray(flux, dtype=float), shape)
        if self.spec.clamp_flux and self.flux_bounds is not None:
            flux = np.clip(flux, *self.flux_bounds)
        ok = (np.isfinite(size) & (size > 0) & np.isfinite(flux) & (flux > 0)).ravel()
        out = np.full(size.size, np.nan)
        if ok.any():
            out[ok] = self.gate.predict_proba(_features(size.ravel()[ok], flux.ravel()[ok], self.spec.use_flux))[:, 1]
        return out.reshape(shape)

    def posterior(self, delta, sigma, size, flux) -> np.ndarray:
        """P(rocky | measured composition offset, size, flux) for planets with both M and R."""
        pi = self.predict(size, flux)
        fr = _npdf(delta, MU_ROCKY, np.sqrt(TAU_ROCKY**2 + sigma**2))
        fg = _npdf(delta, self.mu_g, np.sqrt(self.tau_g**2 + sigma**2))
        return pi * fr / np.maximum(pi * fr + (1 - pi) * fg, 1e-300)

    def loglik(self, delta, sigma, size, flux) -> np.ndarray:
        pi = np.clip(self.predict(size, flux), 1e-9, 1 - 1e-9)
        fr = _npdf(delta, MU_ROCKY, np.sqrt(TAU_ROCKY**2 + sigma**2))
        fg = _npdf(delta, self.mu_g, np.sqrt(self.tau_g**2 + sigma**2))
        return np.log(pi * fr + (1 - pi) * fg + 1e-300)

    def is_monotone(self, s_grid=np.logspace(np.log10(0.05), np.log10(50), 25)) -> bool:
        lo, hi = (0.3, 4.0) if self.variable == "radius" else (0.05, 60.0)
        sizes = np.logspace(np.log10(lo), np.log10(hi), 80)
        return all(not np.any(np.diff(self.predict(sizes, np.full_like(sizes, s))) > 1e-6) for s in s_grid)


def fit_em(variable, spec: GateSpec, size, flux, delta, sigma, max_iter=200, tol=1e-7,
           rogers_center=1.6, rogers_width=0.08) -> RockyRegressor:
    model = RockyRegressor(variable, spec, rogers_center=rogers_center, rogers_width=rogers_width)
    if spec.clamp_flux:
        model.flux_bounds = tuple(float(v) for v in np.percentile(flux, FLUX_SUPPORT_PERCENTILES))
        flux = np.clip(flux, *model.flux_bounds)
    x = _features(size, flux, spec.use_flux)
    # initialise responsibilities from the offset itself
    gamma = 1.0 / (1.0 + np.exp((delta - 0.04) / 0.02))
    prev = -np.inf
    for it in range(max_iter):
        if spec.kind == "logistic":
            model.gate = _fit_soft(spec.make(), x, gamma)
        w = 1.0 - gamma

        def nll(theta):
            mu, ltau = theta
            sd = np.sqrt(np.exp(2 * ltau) + sigma**2)
            return -np.sum(w * (-0.5 * ((delta - mu) / sd) ** 2 - np.log(sd)))

        res = minimize(nll, [model.mu_g, np.log(model.tau_g)], method="Nelder-Mead",
                       options={"xatol": 1e-6, "fatol": 1e-8})
        model.mu_g, model.tau_g = float(res.x[0]), float(np.exp(res.x[1]))
        ll = float(np.sum(model.loglik(delta, sigma, size, flux)))
        gamma = model.posterior(delta, sigma, size, flux)
        model.n_em_iter = it + 1
        if abs(ll - prev) < tol * max(1.0, abs(ll)):
            break
        prev = ll
    return model


def fit_rocky_regressor(train: pd.DataFrame, variable: str, n_splits=5, seed=0,
                        rogers_center=1.6, rogers_width=0.08) -> RockyRegressor:
    size = train[variable].to_numpy(float)
    flux = train["insol_used"].to_numpy(float)
    delta = train["delta"].to_numpy(float)
    sigma = train["delta_sigma"].to_numpy(float)
    groups = train["host"].to_numpy()
    gkf = GroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)

    scores: dict = {}
    fitted: dict = {}
    for spec in GATES:
        held = np.empty_like(delta)
        for tr, te in gkf.split(size, delta, groups):
            m = fit_em(variable, spec, size[tr], flux[tr], delta[tr], sigma[tr],
                       rogers_center=rogers_center, rogers_width=rogers_width)
            held[te] = m.loglik(delta[te], sigma[te], size[te], flux[te])
        full = fit_em(variable, spec, size, flux, delta, sigma, rogers_center=rogers_center, rogers_width=rogers_width)
        mono = full.is_monotone()
        low = flux < LOW_FLUX_SCORE_THRESHOLD
        scores[spec.name] = {
            "cv_mean_heldout_loglik": float(np.mean(held)),
            "cv_heldout_loglik_low_flux": float(np.mean(held[low])) if low.any() else float("nan"),
            "n_low_flux": int(low.sum()),
            "monotone": bool(mono),
            "eligible": bool(mono),
            "mu_volatile": full.mu_g,
            "tau_volatile": full.tau_g,
            "em_iterations": full.n_em_iter,
        }
        fitted[spec.name] = full
    eligible = [k for k, v in scores.items() if v["eligible"]]
    best_name = max(eligible, key=lambda k: scores[k]["cv_mean_heldout_loglik"])
    best = fitted[best_name]
    best.cv_scores = scores
    best.n_train = len(train)
    log.info("rocky model (%s): chose %s, held-out loglik %.4f on %d planets (volatile mu=%.3f tau=%.3f)",
             variable, best_name, scores[best_name]["cv_mean_heldout_loglik"], len(train), best.mu_g, best.tau_g)
    return best


@dataclass
class RockyModel:
    radius_model: RockyRegressor
    mass_model: RockyRegressor
    training_table: pd.DataFrame | None = None

    def p_given_radius(self, radius, flux):
        return self.radius_model.predict(radius, flux)

    def p_given_mass(self, mass, flux):
        return self.mass_model.predict(mass, flux)

    def posterior_measured(self, delta, sigma, radius, flux):
        return self.radius_model.posterior(delta, sigma, radius, flux)

    def summary(self) -> dict:
        out = {}
        for key, m in (("radius", self.radius_model), ("mass", self.mass_model)):
            out[key] = {"chosen": m.chosen, "n_train": m.n_train, "mu_volatile": m.mu_g,
                        "tau_volatile": m.tau_g, "candidates": m.cv_scores}
        return out


def fit_rocky_model(planets: pd.DataFrame, seed=0, rogers_center=1.6, rogers_width=0.08,
                    exclude_ttv=False) -> RockyModel:
    train = select_training_planets(planets, exclude_ttv=exclude_ttv)
    if len(train) < 50:
        log.warning("only %d planets with precise M and R: falling back to Rogers (2015) cut", len(train))
        return fixed_rocky_model(rogers_center, rogers_width)
    train = train.copy()
    train["delta"], train["delta_sigma"] = composition_offsets(train, seed=seed)
    rm = fit_rocky_regressor(train, "radius", seed=seed, rogers_center=rogers_center, rogers_width=rogers_width)
    mm = fit_rocky_regressor(train, "mass", seed=seed, rogers_center=rogers_center, rogers_width=rogers_width)
    train["p_rocky_posterior"] = rm.posterior(train["delta"].to_numpy(), train["delta_sigma"].to_numpy(),
                                              train["radius"].to_numpy(), train["insol_used"].to_numpy())
    return RockyModel(rm, mm, train)


def fixed_rocky_model(rogers_center=1.6, rogers_width=0.08) -> RockyModel:
    return RockyModel(RockyRegressor("radius", rogers_center=rogers_center, rogers_width=rogers_width),
                      RockyRegressor("mass", rogers_center=rogers_center, rogers_width=rogers_width))


@dataclass
class AveragedRockyModel:
    """Equal-weight model average over rocky models trained on different samples.

    Used to bracket the mass-measurement selection effect: TTV masses are biased
    to low densities, RV masses to high densities (small RV signals go
    undetected). Averaging the 'all masses' and 'no TTV masses' models carries
    that systematic uncertainty into P(rocky) instead of picking a side.
    """

    members: dict  # name -> RockyModel

    def _avg(self, fn):
        vals = [fn(m) for m in self.members.values()]
        return np.mean(np.stack(vals, axis=0), axis=0)

    def p_given_radius(self, radius, flux):
        return self._avg(lambda m: m.p_given_radius(radius, flux))

    def p_given_mass(self, mass, flux):
        return self._avg(lambda m: m.p_given_mass(mass, flux))

    def posterior_measured(self, delta, sigma, radius, flux):
        # average of member posteriors = posterior under the model-averaged prior only approximately;
        # members share nearly identical volatile components (|delta mu| < 0.02 dex), so this is accurate
        return self._avg(lambda m: m.posterior_measured(delta, sigma, radius, flux))

    @property
    def training_table(self):
        return next(iter(self.members.values())).training_table

    @property
    def radius_model(self):
        return next(iter(self.members.values())).radius_model

    def summary(self) -> dict:
        return {"type": "equal-weight average", "members": {k: m.summary() for k, m in self.members.items()}}


def fit_rocky_model_average(planets: pd.DataFrame, seed=0) -> AveragedRockyModel:
    return AveragedRockyModel({
        "all_masses": fit_rocky_model(planets, seed=seed),
        "no_ttv_masses": fit_rocky_model(planets, seed=seed, exclude_ttv=True),
    })
