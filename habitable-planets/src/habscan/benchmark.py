"""Validation and model comparison.

There is no labelled set of "habitable exoplanets": none has been observed
to be habitable. So "which model captures habitability best" cannot be
answered with a classification score on catalogue labels. That would only
measure how well a model copies the catalogue's own rule, which
:func:`hwc_circularity_test` demonstrates explicitly.

What *can* be tested:
1. Solar System ground truth (the only planets whose habitability we know):
   Earth must score high; Venus, Mercury and the giants must not; Mars is
   marginal. Also tested: Earth "observed" as a transit-only or RV-only
   exoplanet, to check the imputation paths.
2. Atmospheric-retention against JWST thermal-emission constraints on rocky
   exoplanets (the only empirical exoplanet test of the shoreline component).
3. Agreement with the PHL Habitable Worlds Catalog (an external, rule-based
   reference, used for comparison and never for training).
4. Ablations: what each physical component and uncertainty propagation
   changes in the ranking.
5. Sensitivity of the top candidates to the uncertain model knobs; planets
   that stay on top across all variants are the robust candidates.
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.tree import DecisionTreeClassifier, export_text

from .data.catalogs import SCHEMA_COLUMNS
from .habitability import HabitabilityConfig, HabitabilityEngine
from .ml.rocky import fixed_rocky_model
from .physics import atmosphere as atm
from .physics import habitable_zone as hz
from .physics.planet import earth_similarity_index

log = logging.getLogger(__name__)

# name: (a [AU], e, R [R_E], M [M_E]); NASA planetary fact sheets
SOLAR_SYSTEM_PLANETS = {
    "Mercury": (0.387, 0.2056, 0.383, 0.0553),
    "Venus": (0.723, 0.0068, 0.949, 0.815),
    "Earth": (1.000, 0.0167, 1.000, 1.000),
    "Mars": (1.524, 0.0934, 0.532, 0.107),
    "Jupiter": (5.203, 0.0489, 11.21, 317.8),
    "Saturn": (9.537, 0.0565, 9.45, 95.2),
    "Uranus": (19.19, 0.0457, 4.01, 14.5),
    "Neptune": (30.07, 0.0113, 3.88, 17.1),
}
SOLAR_SYSTEM_EXPECTED = {"Earth": "habitable", "Mars": "marginal"}

# Rocky exoplanets with JWST/Spitzer thermal-emission constraints on a thick atmosphere.
# value: (has substantial atmosphere?, reference)
EMISSION_CONSTRAINTS = {
    "LHS 3844 b": (False, "Kreidberg et al. 2019, Nature 573, 87 (Spitzer: bare rock)"),
    "GJ 1252 b": (False, "Crossfield et al. 2022, ApJL 937, L17 (no thick atmosphere)"),
    "TRAPPIST-1 b": (False, "Greene et al. 2023, Nature 618, 39 (no thick atmosphere)"),
    "TRAPPIST-1 c": (False, "Zieba et al. 2023, Nature 620, 746 (no thick CO2 atmosphere)"),
    "GJ 1132 b": (False, "Xue et al. 2024, ApJL 973, L8 (no thick atmosphere)"),
    "GJ 367 b": (False, "Zhang et al. 2024, ApJL 961, L44 (airless, dark surface)"),
    "55 Cnc e": (True, "Hu et al. 2024, Nature 630, 609 (secondary atmosphere; magma-ocean outgassing)"),
}


def _sun_row(name: str, a, e, r, m, mass_kind="measured", radius_measured=True, rel=0.01) -> dict:
    row = {c: np.nan for c in SCHEMA_COLUMNS}
    row.update(
        uid=f"SS:{name}", name=name, host="Sun", source="solar_system", disposition="KNOWN", label_real=1.0,
        controversial=False, discovery_method="-", st_teff=5772.0, st_teff_e1=20.0, st_teff_e2=-20.0,
        st_rad=1.0, st_rad_e1=0.005, st_rad_e2=-0.005, st_mass=1.0, st_mass_e1=0.005, st_mass_e2=-0.005,
        st_lum=1.0, st_lum_e1=0.01, st_lum_e2=-0.01, st_logg=4.438, st_logg_e1=0.01, st_logg_e2=-0.01,
        st_age=4.57, st_age_e1=0.05, st_age_e2=-0.05,
        a_au=a, a_au_e1=a * 1e-4, a_au_e2=-a * 1e-4, ecc=e, ecc_e1=1e-4, ecc_e2=-1e-4,
        period=365.25 * a**1.5, period_e1=1e-3, period_e2=-1e-3,
        radius=r if radius_measured else np.nan, radius_e1=r * rel, radius_e2=-r * rel, radius_measured=radius_measured,
        mass=m, mass_e1=m * rel, mass_e2=-m * rel, mass_kind=mass_kind,
    )
    if mass_kind == "none":
        row.update(mass=np.nan, mass_e1=np.nan, mass_e2=np.nan)
    return row


def solar_system_table() -> pd.DataFrame:
    rows = [_sun_row(n, *v) for n, v in SOLAR_SYSTEM_PLANETS.items()]
    a, e, r, m = SOLAR_SYSTEM_PLANETS["Earth"]
    # Earth as it would be seen by a transit survey (radius 3 %, no mass) and by RV (M sin i 10 %, no radius)
    rows.append(_sun_row("Earth (transit-only, 3% radius)", a, e, r, m, mass_kind="none", rel=0.03))
    rows.append(_sun_row("Earth (RV-only, Msini 10%)", a, e, r, m, mass_kind="msini", radius_measured=False, rel=0.10))
    return pd.DataFrame(rows)[SCHEMA_COLUMNS]


def solar_system_validation(engine: HabitabilityEngine) -> pd.DataFrame:
    ss = solar_system_table()
    res = engine.evaluate(ss)
    out = pd.concat([ss[["name"]], res[["p_habitable", "p_rocky", "p_hz", "p_atm_retention", "s_eff_med",
                                        "esi_med", "case"]]], axis=1)
    out["expected"] = out["name"].map(lambda n: "habitable" if n.startswith("Earth") else
                                      SOLAR_SYSTEM_EXPECTED.get(n, "not habitable"))
    return out


def solar_system_score(table: pd.DataFrame) -> dict:
    """Scalar summary: Earth's score, worst non-habitable body, Mars."""
    p = table.set_index("name")["p_habitable"]
    non = table[table["expected"] == "not habitable"]["p_habitable"]
    return {
        "earth": float(p.get("Earth", np.nan)),
        "earth_transit_only": float(p.get("Earth (transit-only, 3% radius)", np.nan)),
        "earth_rv_only": float(p.get("Earth (RV-only, Msini 10%)", np.nan)),
        "mars": float(p.get("Mars", np.nan)),
        "max_not_habitable": float(non.max()),
        "separation": float(p.get("Earth", np.nan) - non.max()),
    }


def shoreline_validation(planets: pd.DataFrame, results: pd.DataFrame, width_dex: float) -> pd.DataFrame:
    rows = []
    for name, ratio, p, obs in atm.solar_system_table(width_dex):
        rows.append({"body": name, "kind": "Solar System", "log10_ratio": np.log10(ratio), "p_retention": p,
                     "observed_atmosphere": obs, "reference": "NASA fact sheets; Zahnle & Catling 2017"})
    names = planets["name"]
    for name, (obs, ref) in EMISSION_CONSTRAINTS.items():
        hit = results[names == name]
        if hit.empty:
            continue
        r = hit.iloc[0]
        rows.append({"body": name, "kind": "exoplanet (thermal emission)", "log10_ratio": r["shoreline_log_ratio_med"],
                     "p_retention": r["p_atm_retention"], "observed_atmosphere": obs, "reference": ref})
    df = pd.DataFrame(rows)
    known = df["observed_atmosphere"].notna()
    df["correct"] = np.where(known, (df["p_retention"] > 0.5) == df["observed_atmosphere"].astype(bool), np.nan)
    return df


# ---------------------------------------------------------------------------
def _norm_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def load_hwc_labels(hwc: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame({
        "key": hwc["P_NAME"].map(_norm_name),
        "hwc_name": hwc["P_NAME"],
        "hwc_habitable": pd.to_numeric(hwc["P_HABITABLE"], errors="coerce").fillna(0).astype(int),
        "hwc_esi": pd.to_numeric(hwc["P_ESI"], errors="coerce"),
    })
    return out.drop_duplicates("key")


def attach_hwc(planets: pd.DataFrame, hwc_labels: pd.DataFrame) -> pd.DataFrame:
    keys = planets["name"].map(_norm_name)
    m = pd.DataFrame({"key": keys}).merge(hwc_labels, on="key", how="left")
    m.index = planets.index
    return m[["hwc_name", "hwc_habitable", "hwc_esi"]]


def hwc_agreement(scores: pd.Series, hwc_hab: pd.Series) -> dict:
    ok = hwc_hab.notna() & scores.notna()
    y_any = (hwc_hab[ok] > 0).astype(int)
    y_cons = (hwc_hab[ok] == 1).astype(int)
    s = scores[ok]
    return {
        "n_matched": int(ok.sum()),
        "n_hwc_habitable": int(y_any.sum()),
        "auc_vs_hwc_any": float(roc_auc_score(y_any, s)) if y_any.nunique() == 2 else np.nan,
        "ap_vs_hwc_any": float(average_precision_score(y_any, s)) if y_any.nunique() == 2 else np.nan,
        "auc_vs_hwc_conservative": float(roc_auc_score(y_cons, s)) if y_cons.nunique() == 2 else np.nan,
    }


def hwc_circularity_test(hwc: pd.DataFrame, seed: int = 0) -> dict:
    """Can a tiny decision tree reproduce HWC labels from 4 catalogue columns? (If yes: labels = rule.)"""
    cols = ["P_FLUX", "P_RADIUS", "P_MASS", "S_TEMPERATURE"]
    d = hwc[cols + ["P_HABITABLE"]].apply(pd.to_numeric, errors="coerce").dropna()
    x = d[cols].to_numpy()
    y = (d["P_HABITABLE"] > 0).astype(int).to_numpy()
    out = {"n": int(len(y)), "n_positive": int(y.sum())}
    for depth in (2, 3, 4, 6):
        tree = DecisionTreeClassifier(max_depth=depth, class_weight="balanced", random_state=seed)
        p = cross_val_predict(tree, x, y, cv=StratifiedKFold(5, shuffle=True, random_state=seed), method="predict_proba")[:, 1]
        out[f"depth_{depth}"] = {"cv_auc": float(roc_auc_score(y, p)),
                                 "cv_balanced_accuracy": float(((p > 0.5) & (y == 1)).sum() / max(y.sum(), 1) / 2
                                                               + ((p <= 0.5) & (y == 0)).sum() / max((y == 0).sum(), 1) / 2)}
    tree = DecisionTreeClassifier(max_depth=4, class_weight="balanced", random_state=seed).fit(x, y)
    out["rules_depth4"] = export_text(tree, feature_names=cols, decimals=2)
    return out


# ---------------------------------------------------------------------------
def hwc_rule_scores(planets: pd.DataFrame, results: pd.DataFrame) -> pd.Series:
    """Deterministic HWC-style rule on point values (baseline model).

    conservative: conservative HZ and (0.5 <= R <= 1.6 or 0.1 <= M <= 3) -> 1
    optimistic:   optimistic HZ and (R <= 2.5 or M <= 10)               -> 0.5
    Uses the catalogue values (catalogue M-R forecasts where nothing was measured),
    exactly like a catalogue would.
    """
    s = results["s_eff_med"]
    teff = planets["st_teff"]
    r = planets["radius"]
    m = planets["mass"]
    cons = hz.in_conservative_hz(s, teff) & (r.between(0.5, 1.6) | m.between(0.1, 3.0))
    opt = hz.in_optimistic_hz(s, teff) & ((r <= 2.5) | (m <= 10.0))
    return pd.Series(np.where(cons, 1.0, np.where(opt, 0.5, 0.0)), index=planets.index).where(s.notna())


def esi_scores(results: pd.DataFrame) -> pd.Series:
    return results["esi_med"]


def _spearman_on_relevant(a: pd.Series, b: pd.Series, floor: float = 0.01) -> float:
    """Rank correlation restricted to planets that at least one model considers non-negligible."""
    m = a.notna() & b.notna() & ((a > floor) | (b > floor))
    if m.sum() < 3:
        return float("nan")
    return float(spearmanr(a[m], b[m]).statistic)


def top_overlap(a: pd.Series, b: pd.Series, k: int) -> float:
    ta = set(a.dropna().sort_values(ascending=False).index[:k])
    tb = set(b.dropna().sort_values(ascending=False).index[:k])
    return len(ta & tb) / k


def ablation_study(planets: pd.DataFrame, base_cfg: HabitabilityConfig, rocky_model, reference: pd.DataFrame,
                   hwc_hab: pd.Series | None, k: int = 25) -> pd.DataFrame:
    """Re-score planets under alternative model definitions and compare to the full model."""
    variants = {
        "full_physical_mc": (base_cfg, rocky_model),
        "no_atmosphere_term": (replace(base_cfg, use_atmosphere=False), rocky_model),
        "no_uncertainty (point estimates)": (replace(base_cfg, point_estimate=True), rocky_model),
        "fixed_rogers_rocky_cut": (base_cfg, fixed_rocky_model()),
        **({f"rocky_{k}_only": (base_cfg, m) for k, m in getattr(rocky_model, "members", {}).items()}),
        "binary_conservative_hz": (replace(base_cfg, hz_mode="conservative"), rocky_model),
        "binary_optimistic_hz": (replace(base_cfg, hz_mode="optimistic"), rocky_model),
    }
    full = reference["p_habitable"]
    rows = []
    for name, (cfg, rm) in variants.items():
        eng = HabitabilityEngine(cfg, rm)
        res = reference if name == "full_physical_mc" else eng.evaluate(planets)
        ss = solar_system_score(solar_system_validation(eng))
        score = res["p_habitable"]
        rho = _spearman_on_relevant(full, score)
        row = {"model": name, "n_p_gt_0.5": int((score > 0.5).sum()), "expected_n_habitable": float(score.sum()),
               f"top{k}_overlap_with_full": top_overlap(full, score, k), "spearman_vs_full": float(rho),
               **{f"solar_{kk}": v for kk, v in ss.items()}}
        if hwc_hab is not None:
            row.update(hwc_agreement(score, hwc_hab))
        rows.append(row)
    # catalogue-style baselines (no physics engine)
    for name, score in (("hwc_rule_baseline", hwc_rule_scores(planets, reference)), ("esi_only", esi_scores(reference))):
        rho = _spearman_on_relevant(full, score)
        row = {"model": name, "n_p_gt_0.5": int((score > 0.5).sum()), "expected_n_habitable": np.nan,
               f"top{k}_overlap_with_full": top_overlap(full, score, k), "spearman_vs_full": float(rho)}
        ss_tab = solar_system_table()
        ss_res = HabitabilityEngine(replace(base_cfg, point_estimate=True), rocky_model).evaluate(ss_tab)
        ss_score = (hwc_rule_scores(ss_tab, ss_res) if name == "hwc_rule_baseline"
                    else pd.Series(earth_similarity_index(ss_tab["radius"], ss_res["s_eff_med"])))
        named = dict(zip(ss_tab["name"], ss_score))
        non = [v for n, v in named.items() if n in SOLAR_SYSTEM_PLANETS and n not in ("Earth", "Mars")]
        row.update(solar_earth=float(named["Earth"]), solar_mars=float(named["Mars"]),
                   solar_max_not_habitable=float(np.nanmax(non)), solar_separation=float(named["Earth"] - np.nanmax(non)))
        if hwc_hab is not None:
            row.update(hwc_agreement(score, hwc_hab))
        rows.append(row)
    return pd.DataFrame(rows)


def sensitivity_study(planets: pd.DataFrame, base_cfg: HabitabilityConfig, rocky_model, k: int = 20,
                      log10_k_shifts=(-0.3, 0.0, 0.3), widths=(0.15, 0.25, 0.4),
                      cmf_ranges=((0.15, 0.45), (0.05, 0.7)), n_samples: int = 1000,
                      p_real: pd.Series | None = None):
    """Fraction of knob settings in which each planet stays in the top-k.

    Knobs: shoreline position (±0.3 dex around the Mars calibration), shoreline
    width, and the core-mass-fraction prior used to turn radii into masses.
    Planets are ranked by the same criterion as the final list: P(habitable) × P(real).
    """
    weight = pd.Series(1.0, index=planets.index) if p_real is None else p_real.reindex(planets.index).fillna(0.0)
    counts = pd.Series(0.0, index=planets.index)
    settings = []
    for shift in log10_k_shifts:
        for w in widths:
            for cmf in cmf_ranges:
                cfg = replace(base_cfg, shoreline_log10_k=base_cfg.shoreline_log10_k + shift, shoreline_width_dex=w,
                              cmf_range=cmf, n_samples=min(base_cfg.n_samples, n_samples))
                res = HabitabilityEngine(cfg, rocky_model).evaluate(planets)
                top = (res["p_habitable"] * weight).dropna().sort_values(ascending=False).index[:k]
                counts[top] += 1
                settings.append({"log10_k": cfg.shoreline_log10_k, "width_dex": w, "cmf_range": str(cmf)})
    return counts / len(settings), pd.DataFrame(settings)
