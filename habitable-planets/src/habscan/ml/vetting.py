"""Candidate vetting: P(real planet) for TESS and Kepler candidates.

This is where machine learning has *real* ground truth: thousands of TOIs and
KOIs have been resolved by follow-up into confirmed planets or false
positives (eclipsing binaries, blends, systematics). We learn
P(planet | observables) and apply it to the still-open candidates.

Model search
------------
Several model families are compared, each with a small hyper-parameter grid:
regularised logistic regression, random forest, histogram gradient boosting
and LightGBM. Splits are *grouped by host star* (StratifiedGroupKFold) so
that sibling candidates in the same system never sit on both sides of a
split (multiplicity is itself a strong feature and would leak otherwise).

Protocol
    1. 20 % of host stars are held out and never touched during selection.
    2. On the remaining 80 %: 5-fold grouped CV for every configuration,
       ranked by out-of-fold log-loss (a proper scoring rule: rewards
       calibrated probabilities, not just ranking).
    3. Best configuration is refit; isotonic calibration is learned on its
       out-of-fold predictions; the held-out score is the unbiased estimate.
    4. Final model: refit on all labelled data (calibration from OOF), used
       to score open candidates.

Leakage controls
    Columns produced by the vetting pipelines themselves are excluded
    (koi_score, koi_pdisposition, koi_fpflag_*): they encode the label.

Known limitation (stated, not hidden)
    Resolved candidates are not a random sample of all candidates (bright,
    deep, short-period signals are resolved first). Probabilities for open
    candidates inherit this covariate shift; ranking is more trustworthy
    than the absolute value.
"""

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass, field

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from ..physics.planet import mass_from_logg_radius, transit_duration_circular_hours

log = logging.getLogger(__name__)

RHO_SUN_CGS = 1.41


def _num(df, c):
    return pd.to_numeric(df[c], errors="coerce").astype(float) if c in df else pd.Series(np.nan, index=df.index)


def _log(x):
    x = np.asarray(x, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(x > 0, np.log10(x), np.nan)


def _finite(f: pd.DataFrame) -> pd.DataFrame:
    """±inf (zero-valued denominators in the catalogue) -> NaN, handled as missing by every model."""
    return f.astype(float).replace([np.inf, -np.inf], np.nan)


def toi_features(toi: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame(index=toi.index)
    per, dur, dep = _num(toi, "pl_orbper"), _num(toi, "pl_trandurh"), _num(toi, "pl_trandep")
    rad, srad, logg = _num(toi, "pl_rade"), _num(toi, "st_rad"), _num(toi, "st_logg")
    dep_err = 0.5 * (_num(toi, "pl_trandeperr1").abs() + _num(toi, "pl_trandeperr2").abs())
    per_err = 0.5 * (_num(toi, "pl_orbpererr1").abs() + _num(toi, "pl_orbpererr2").abs())
    rad_err = 0.5 * (_num(toi, "pl_radeerr1").abs() + _num(toi, "pl_radeerr2").abs())
    f["log_period"] = _log(per)
    f["log_duration_h"] = _log(dur)
    f["log_depth_ppm"] = _log(dep)
    f["depth_snr"] = dep / dep_err.where(dep_err > 0)
    f["log_period_rel_err"] = _log(per_err / per)
    f["log_radius"] = _log(rad)
    f["radius_rel_err"] = rad_err / rad
    f["log_insol"] = _log(_num(toi, "pl_insol"))
    f["eqt"] = _num(toi, "pl_eqt")
    f["tmag"] = _num(toi, "st_tmag")
    f["log_dist"] = _log(_num(toi, "st_dist"))
    f["teff"] = _num(toi, "st_teff")
    f["logg"] = logg
    f["log_st_rad"] = _log(srad)
    f["n_candidates_system"] = _num(toi, "pl_pnum")
    mstar = pd.Series(mass_from_logg_radius(logg, srad), index=toi.index).clip(0.05, 10)
    f["log_duration_ratio"] = _log(dur / transit_duration_circular_hours(per, srad, mstar))
    f["log_pm"] = _log(np.hypot(_num(toi, "st_pmra"), _num(toi, "st_pmdec")))
    return _finite(f)


KOI_EXCLUDED = {"koi_score", "koi_pdisposition", "koi_fpflag_nt", "koi_fpflag_ss", "koi_fpflag_co", "koi_fpflag_ec"}


def koi_features(koi: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame(index=koi.index)
    per, dur, dep = _num(koi, "koi_period"), _num(koi, "koi_duration"), _num(koi, "koi_depth")
    srad, smass = _num(koi, "koi_srad"), _num(koi, "koi_smass")
    f["log_period"] = _log(per)
    f["log_duration_h"] = _log(dur)
    f["log_depth_ppm"] = _log(dep)
    f["log_prad"] = _log(_num(koi, "koi_prad"))
    f["impact"] = _num(koi, "koi_impact")
    f["log_ror"] = _log(_num(koi, "koi_ror"))
    f["log_dor"] = _log(_num(koi, "koi_dor"))
    f["log_model_snr"] = _log(_num(koi, "koi_model_snr"))
    f["log_num_transits"] = _log(_num(koi, "koi_num_transits"))
    f["log_max_sngle_ev"] = _log(_num(koi, "koi_max_sngle_ev"))
    f["log_max_mult_ev"] = _log(_num(koi, "koi_max_mult_ev"))
    f["sngle_over_mult"] = _num(koi, "koi_max_sngle_ev") / _num(koi, "koi_max_mult_ev")
    f["bin_oedp_sig"] = _num(koi, "koi_bin_oedp_sig")
    f["log_chi2_dof"] = _log(_num(koi, "koi_model_chisq") / _num(koi, "koi_model_dof"))
    f["kepmag"] = _num(koi, "koi_kepmag")
    f["n_candidates_system"] = _num(koi, "koi_count")
    f["teff"] = _num(koi, "koi_steff")
    f["logg"] = _num(koi, "koi_slogg")
    f["log_st_rad"] = _log(srad)
    f["st_mass"] = smass
    f["st_met"] = _num(koi, "koi_smet")
    f["log_insol"] = _log(_num(koi, "koi_insol"))
    f["teq"] = _num(koi, "koi_teq")
    f["fwm_stat_sig"] = _num(koi, "koi_fwm_stat_sig")
    f["fwm_offset_src"] = np.hypot(_num(koi, "koi_fwm_srao"), _num(koi, "koi_fwm_sdeco"))
    f["fwm_offset_pred"] = np.hypot(_num(koi, "koi_fwm_prao"), _num(koi, "koi_fwm_pdeco"))
    f["dicco_msky_sig"] = _num(koi, "koi_dicco_msky") / _num(koi, "koi_dicco_msky_err").where(lambda s: s > 0)
    f["dikco_msky_sig"] = _num(koi, "koi_dikco_msky") / _num(koi, "koi_dikco_msky_err").where(lambda s: s > 0)
    f["log_ingress_frac"] = _log(_num(koi, "koi_ingress") / dur)
    # transit-derived vs spectroscopic stellar density: blends/EBs are inconsistent
    rho_spec = RHO_SUN_CGS * smass / srad**3
    f["log_rho_ratio"] = _log(_num(koi, "koi_srho") / rho_spec)
    f["log_duration_ratio"] = _log(dur / transit_duration_circular_hours(per, srad, smass.clip(0.05, 10)))
    return _finite(f)


# ---------------------------------------------------------------------------
def _model_grid(seed: int) -> dict[str, list]:
    grid = {}
    grid["logistic_l2"] = [
        make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler(),
                      LogisticRegression(C=c, max_iter=5000))
        for c in (0.01, 0.1, 1.0, 10.0)
    ]
    grid["random_forest"] = [
        make_pipeline(SimpleImputer(strategy="median", add_indicator=True),
                      RandomForestClassifier(n_estimators=400, min_samples_leaf=leaf, max_features=mf,
                                             n_jobs=-1, random_state=seed))
        for leaf, mf in itertools.product((1, 5), ("sqrt", 0.5))
    ]
    grid["hist_gradient_boosting"] = [
        HistGradientBoostingClassifier(learning_rate=lr, max_leaf_nodes=leaves, l2_regularization=1.0,
                                       max_iter=600, early_stopping=True, validation_fraction=0.15,
                                       n_iter_no_change=30, random_state=seed)
        for lr, leaves in itertools.product((0.03, 0.1), (15, 31))
    ]
    grid["lightgbm"] = [
        lgb.LGBMClassifier(n_estimators=n_est, learning_rate=lr, num_leaves=leaves, min_child_samples=20,
                           subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
                           random_state=seed, n_jobs=4, verbose=-1)
        for n_est, lr, leaves in ((400, 0.03, 15), (800, 0.02, 31), (300, 0.05, 31), (600, 0.03, 63))
    ]
    return grid


def _describe(est) -> str:
    final = est.steps[-1][1] if hasattr(est, "steps") else est
    params = final.get_params()
    keys = [k for k in ("C", "min_samples_leaf", "max_features", "learning_rate", "max_leaf_nodes", "num_leaves",
                        "n_estimators") if k in params]
    return ", ".join(f"{k}={params[k]}" for k in keys)


def _metrics(y, p) -> dict:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    bins = np.clip((p * 10).astype(int), 0, 9)
    ece = sum(abs(p[bins == b].mean() - y[bins == b].mean()) * (bins == b).mean() for b in range(10) if (bins == b).any())
    return {
        "roc_auc": float(roc_auc_score(y, p)),
        "avg_precision": float(average_precision_score(y, p)),
        "log_loss": float(log_loss(y, p)),
        "brier": float(brier_score_loss(y, p)),
        "ece": float(ece),
        "n": int(len(y)),
        "positive_rate": float(np.mean(y)),
    }


def _oof(est, x, y, groups, cv) -> np.ndarray:
    oof = np.zeros(len(y))
    for tr, te in cv.split(x, y, groups):
        m = clone(est).fit(x.iloc[tr], y[tr])
        oof[te] = m.predict_proba(x.iloc[te])[:, 1]
    return oof


@dataclass
class VettingModel:
    survey: str
    feature_names: list
    estimator: object
    calibrator: IsotonicRegression
    selection: list = field(default_factory=list)
    holdout_metrics: dict = field(default_factory=dict)
    holdout_metrics_uncalibrated: dict = field(default_factory=dict)
    chosen: str = ""
    importances: list = field(default_factory=list)
    n_labelled: int = 0
    dropped_features: list = field(default_factory=list)
    holdout_predictions: pd.DataFrame | None = None

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        raw = self.estimator.predict_proba(features[self.feature_names])[:, 1]
        return self.calibrator.predict(raw)

    def summary(self) -> dict:
        return {
            "survey": self.survey, "chosen": self.chosen, "n_labelled": self.n_labelled,
            "holdout_calibrated": self.holdout_metrics, "holdout_uncalibrated": self.holdout_metrics_uncalibrated,
            "model_search": self.selection, "top_features": self.importances[:15],
            "features": self.feature_names, "dropped_features": self.dropped_features,
        }


def train_vetting_model(features: pd.DataFrame, labels: pd.Series, groups: pd.Series, survey: str,
                        seed: int = 0, n_splits: int = 5) -> VettingModel:
    lab = labels.notna()
    nunique = features[lab].nunique(dropna=True)
    dropped = sorted(nunique.index[nunique < 2])
    if dropped:
        log.info("%s vetting: dropping degenerate features %s", survey, dropped)
    features = features.drop(columns=dropped)
    x = features[lab].reset_index(drop=True)
    y = labels[lab].astype(int).to_numpy()
    g = groups[lab].to_numpy()
    log.info("%s vetting: %d labelled (%d planets / %d false positives), %d features",
             survey, len(y), y.sum(), len(y) - y.sum(), x.shape[1])

    outer = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=seed)
    tr_idx, te_idx = next(outer.split(x, y, g))
    xtr, ytr, gtr = x.iloc[tr_idx].reset_index(drop=True), y[tr_idx], g[tr_idx]
    xte, yte = x.iloc[te_idx].reset_index(drop=True), y[te_idx]
    assert not set(gtr) & set(g[te_idx]), "host leakage between train and hold-out"

    cv = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed + 1)
    results = []
    best = None
    for family, configs in _model_grid(seed).items():
        for est in configs:
            oof = _oof(est, xtr, ytr, gtr, cv)
            m = _metrics(ytr, oof)
            row = {"family": family, "config": _describe(est), **{f"cv_{k}": v for k, v in m.items()}}
            results.append(row)
            log.info("  %-24s %-55s CV logloss=%.4f AUC=%.4f", family, row["config"], m["log_loss"], m["roc_auc"])
            if best is None or m["log_loss"] < best[0]:
                best = (m["log_loss"], family, est, oof)
    _, family, est, oof = best
    for r in results:
        r["selected"] = r["family"] == family and r["config"] == _describe(est)

    cal = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(oof, ytr)
    fitted = clone(est).fit(xtr, ytr)
    raw_te = fitted.predict_proba(xte)[:, 1]
    holdout_uncal = _metrics(yte, raw_te)
    holdout = _metrics(yte, cal.predict(raw_te))

    pi = permutation_importance(fitted, xte, yte, scoring="neg_log_loss", n_repeats=5, random_state=seed, n_jobs=1)
    imp = sorted(zip(x.columns, pi.importances_mean, pi.importances_std), key=lambda t: -t[1])
    importances = [{"feature": f, "delta_log_loss": float(m), "std": float(s)} for f, m, s in imp]

    # final model on all labelled data
    oof_all = _oof(est, x, y, g, cv)
    cal_all = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(oof_all, y)
    final = clone(est).fit(x, y)
    log.info("%s vetting: selected %s (%s); hold-out AUC=%.4f logloss=%.4f ECE=%.4f",
             survey, family, _describe(est), holdout["roc_auc"], holdout["log_loss"], holdout["ece"])
    return VettingModel(
        survey=survey, feature_names=list(x.columns), estimator=final, calibrator=cal_all, selection=results,
        holdout_metrics=holdout, holdout_metrics_uncalibrated=holdout_uncal, chosen=f"{family} ({_describe(est)})",
        importances=importances, n_labelled=len(y), dropped_features=dropped,
        holdout_predictions=pd.DataFrame({"y": yte, "p_calibrated": cal.predict(raw_te), "p_raw": raw_te}),
    )
