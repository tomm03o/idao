"""End-to-end pipeline: data → rocky model → vetting → Monte Carlo habitability → benchmark → outputs."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__
from .benchmark import (ablation_study, attach_hwc, hwc_agreement, hwc_circularity_test, load_hwc_labels,
                        sensitivity_study, shoreline_validation, solar_system_score, solar_system_validation)
from .data.archive import fetch_all, load_raw, raw_metadata
from .data.catalogs import build_planet_table, scan_mask
from .habitability import HabitabilityConfig, HabitabilityEngine
from .ml.rocky import fit_rocky_model_average
from .ml.vetting import koi_features, toi_features, train_vetting_model

log = logging.getLogger(__name__)

RANKING_COLUMNS = [
    "rank", "name", "host", "source", "disposition", "p_real", "p_habitable", "p_habitable_and_real",
    "robust_top_fraction", "p_rocky", "p_hz", "p_hz_conservative", "p_hz_optimistic", "p_atm_retention",
    "p_main_sequence", "p_tidally_locked", "s_eff_med", "s_eff_p16", "s_eff_p84", "teq_med", "radius_med",
    "mass_med", "mass_forecast_med", "radius_forecast_med", "esi_med", "esi_p16", "esi_p84",
    "shoreline_log_ratio_med", "xuv_fluence_rel_med", "hz_con_inner_au", "hz_con_outer_au", "case", "mass_kind",
    "flux_source", "teff_extrapolated", "st_teff", "st_rad", "st_mass", "st_age", "period", "dist_pc", "mag",
    "discovery_method", "controversial", "hwc_name", "hwc_habitable", "hwc_esi",
]


@dataclass
class PipelineResult:
    ranking: pd.DataFrame
    benchmark: dict
    out_dir: Path


def _vetting(planets, raw, survey, source, features_fn, seed):
    mask = (planets["source"] == source).to_numpy()
    if not mask.any() or raw is None:
        return None, pd.Series(dtype=float)
    feats = features_fn(raw).reset_index(drop=True)
    sub = planets[mask].reset_index(drop=True)
    if len(feats) != len(sub):
        raise RuntimeError(f"{survey}: feature/catalogue row mismatch ({len(feats)} vs {len(sub)})")
    model = train_vetting_model(feats, sub["label_real"], sub["host"], survey, seed=seed)
    p = pd.Series(model.predict(feats), index=planets.index[mask])
    labelled = sub["label_real"].notna().to_numpy()
    p[labelled] = sub.loc[labelled, "label_real"].to_numpy()  # resolved: use the disposition itself
    return model, p


def run(raw_dir: Path, out_dir: Path, fetch: bool = False, n_samples: int = 2000, seed: int = 20261127,
        sensitivity: bool = True, top_k: int = 100) -> PipelineResult:
    t0 = time.time()
    raw_dir, out_dir = Path(raw_dir), Path(out_dir)
    (out_dir / "figures").mkdir(parents=True, exist_ok=True)
    if fetch or not (raw_dir / "pscomppars.csv").exists():
        fetch_all(raw_dir)
    ps, toi, koi, hwc = (load_raw(raw_dir, n) for n in ("pscomppars", "toi", "koi", "hwc"))
    if ps is None:
        raise FileNotFoundError(f"no pscomppars.csv in {raw_dir}; run with --fetch")
    planets = build_planet_table(ps, toi, koi)
    log.info("planet table: %d rows (%s)", len(planets), planets["source"].value_counts().to_dict())

    # 1. rocky-planet population model ------------------------------------
    rocky = fit_rocky_model_average(planets, seed=seed)

    # 2. candidate vetting --------------------------------------------------
    p_real = pd.Series(np.nan, index=planets.index)
    p_real[planets["source"] == "confirmed"] = 1.0
    vet = {}
    for survey, source, raw, fn in (("TESS", "toi", toi, toi_features), ("Kepler", "koi", koi, koi_features)):
        model, p = _vetting(planets, raw, survey, source, fn, seed)
        if model is not None:
            vet[survey] = model
            p_real[p.index] = p

    # 3. habitability Monte Carlo ------------------------------------------
    cfg = HabitabilityConfig(n_samples=n_samples, seed=seed)
    engine = HabitabilityEngine(cfg, rocky)
    scan = planets[scan_mask(planets)]
    log.info("scoring %d planets/candidates with %d Monte Carlo samples each", len(scan), n_samples)
    res = engine.evaluate(scan)

    ranking = pd.concat([scan, res], axis=1)
    ranking["p_real"] = p_real[scan.index]
    ranking["p_habitable_and_real"] = ranking["p_real"] * ranking["p_habitable"]
    hwc_labels = load_hwc_labels(hwc) if hwc is not None else None
    if hwc_labels is not None:
        ranking = pd.concat([ranking, attach_hwc(scan, hwc_labels)], axis=1)
    else:
        ranking[["hwc_name", "hwc_habitable", "hwc_esi"]] = np.nan

    # 4. benchmark ----------------------------------------------------------
    bench: dict = {"version": __version__, "config": cfg.to_dict(), "data": raw_metadata(raw_dir)}
    ss = solar_system_validation(engine)
    bench["solar_system"] = {"table": ss.round(4).to_dict(orient="records"), "score": solar_system_score(ss)}
    shore = shoreline_validation(scan, res, cfg.shoreline_width_dex)
    bench["shoreline"] = shore.round(4).to_dict(orient="records")
    bench["rocky_model"] = rocky.summary()
    bench["vetting"] = {k: v.summary() for k, v in vet.items()}
    confirmed = ranking["source"] == "confirmed"
    if hwc is not None:
        bench["hwc_circularity"] = hwc_circularity_test(hwc, seed=seed)
        bench["hwc_agreement_full_model"] = hwc_agreement(ranking.loc[confirmed, "p_habitable"],
                                                          ranking.loc[confirmed, "hwc_habitable"])
    conf_planets = scan[confirmed.to_numpy()]
    abl = ablation_study(conf_planets, cfg, rocky, res[confirmed.to_numpy()],
                         ranking.loc[confirmed, "hwc_habitable"] if hwc is not None else None)
    bench["ablation"] = abl.round(4).to_dict(orient="records")

    # 5. robustness of the top of the list --------------------------------
    ranking["robust_top_fraction"] = np.nan
    if sensitivity:
        relevant = ranking.index[(ranking["p_habitable"] > 1e-3).to_numpy()]
        frac, settings = sensitivity_study(scan.loc[relevant], cfg, rocky, k=20,
                                           p_real=ranking.loc[relevant, "p_real"])
        ranking.loc[relevant, "robust_top_fraction"] = frac
        bench["sensitivity_settings"] = settings.to_dict(orient="records")

    ranking = ranking.sort_values(["p_habitable_and_real", "p_habitable"], ascending=False)
    ranking["rank"] = np.arange(1, len(ranking) + 1)
    ranking = ranking[RANKING_COLUMNS]

    # 6. outputs ------------------------------------------------------------
    ranking.to_csv(out_dir / "ranking_all.csv.gz", index=False, float_format="%.5g", compression="gzip")
    ranking.head(top_k).to_csv(out_dir / "top_candidates.csv", index=False, float_format="%.4g")
    bench["summary"] = {
        "n_scored": int(len(ranking)),
        "n_evaluable": int(res["evaluable"].sum()),
        "n_confirmed": int(confirmed.sum()),
        "n_open_candidates": int((~confirmed).sum()),
        "expected_number_habitable_confirmed": float(ranking.loc[ranking.source == "confirmed", "p_habitable"].sum()),
        "expected_number_habitable_candidates": float(ranking.loc[ranking.source != "confirmed",
                                                                  "p_habitable_and_real"].sum()),
        "runtime_s": round(time.time() - t0, 1),
    }
    (out_dir / "benchmark.json").write_text(json.dumps(bench, indent=2, default=_json_default), encoding="utf-8")
    from .report import write_report  # matplotlib import deferred

    write_report(ranking, bench, vet, rocky, shore, ss, abl, out_dir)
    log.info("done in %.1fs -> %s", time.time() - t0, out_dir)
    return PipelineResult(ranking, bench, out_dir)


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (tuple, set)):
        return list(o)
    return str(o)
