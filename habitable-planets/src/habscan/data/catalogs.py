"""Harmonise heterogeneous catalogues into one planet table.

Common schema (one row per planet or planet candidate)
------------------------------------------------------
uid, name, host, source ('confirmed' | 'toi' | 'koi'), disposition,
label_real (1 = planet, 0 = false positive, NaN = unknown), controversial,
discovery_method, ra, dec, dist_pc, mag,
period[, _e1, _e2] (days), a_au[...], ecc[...], insol[...] (Earth units),
radius[...] (R_E), radius_measured (bool),
mass[...] (M_E), mass_kind ('measured' | 'msini' | 'upper' | 'lower' | 'none'),
st_teff[...] (K), st_rad[...] (R_sun), st_mass[...] (M_sun), st_lum[...] (L_sun, linear),
st_logg[...] (cgs), st_age[...] (Gyr), st_met (dex), n_planets_system.

Error columns follow the archive convention: _e1 >= 0 upper, _e2 <= 0 lower.

Decisions that matter for habitability, made explicit here:
* pscomppars fills missing masses/radii with a mass-radius relation
  (pl_bmassprov == 'M-R relationship', or any radius of a non-transiting
  planet). Those are *not* measurements; they are marked 'none' /
  radius_measured=False so the Monte Carlo engine imputes them itself with
  propagated uncertainty instead of trusting a single forecast value.
* Mass limits (pl_bmasselim = +1 upper, -1 lower) become constraints.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..physics.planet import mass_from_logg_radius

SCHEMA_COLUMNS = [
    "uid", "name", "host", "source", "disposition", "label_real", "controversial", "discovery_method",
    "ra", "dec", "dist_pc", "mag", "n_planets_system", "ttv_flag",
    "period", "period_e1", "period_e2", "a_au", "a_au_e1", "a_au_e2", "ecc", "ecc_e1", "ecc_e2",
    "insol", "insol_e1", "insol_e2", "radius", "radius_e1", "radius_e2", "radius_measured",
    "mass", "mass_e1", "mass_e2", "mass_kind",
    "st_teff", "st_teff_e1", "st_teff_e2", "st_rad", "st_rad_e1", "st_rad_e2",
    "st_mass", "st_mass_e1", "st_mass_e2", "st_lum", "st_lum_e1", "st_lum_e2",
    "st_logg", "st_logg_e1", "st_logg_e2", "st_age", "st_age_e1", "st_age_e2", "st_met",
]


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df:
        return pd.Series(np.nan, index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors="coerce").astype(float)


def _triplet(out: dict, df: pd.DataFrame, dst: str, src: str, err1: str | None = None, err2: str | None = None):
    out[dst] = _num(df, src)
    out[f"{dst}_e1"] = _num(df, err1 or f"{src}err1")
    out[f"{dst}_e2"] = _num(df, err2 or f"{src}err2")


def _log_to_linear(logv: pd.Series, e1: pd.Series, e2: pd.Series):
    v = 10.0**logv
    return v, 10.0 ** (logv + e1.abs()) - v, 10.0 ** (logv - e2.abs()) - v


def _finalise(out: dict, index) -> pd.DataFrame:
    df = pd.DataFrame(out, index=index)
    for c in SCHEMA_COLUMNS:
        if c not in df:
            df[c] = np.nan
    df = df[SCHEMA_COLUMNS].reset_index(drop=True)
    # non-physical values -> NaN
    for c in ("period", "a_au", "insol", "radius", "mass", "st_teff", "st_rad", "st_mass", "st_lum"):
        df.loc[~(df[c] > 0), c] = np.nan
    df.loc[~(df["st_age"] > 0), "st_age"] = np.nan
    df["ecc"] = df["ecc"].clip(lower=0.0, upper=0.99)
    return df


def harmonise_confirmed(ps: pd.DataFrame) -> pd.DataFrame:
    out: dict = {}
    out["name"] = ps["pl_name"].astype(str)
    out["uid"] = "PS:" + out["name"]
    out["host"] = ps["hostname"].astype(str)
    out["source"] = "confirmed"
    out["disposition"] = "CONFIRMED"
    out["label_real"] = 1.0
    out["controversial"] = _num(ps, "pl_controv_flag").fillna(0).astype(int) == 1
    out["discovery_method"] = ps["discoverymethod"].astype(str)
    out["ra"], out["dec"], out["dist_pc"] = _num(ps, "ra"), _num(ps, "dec"), _num(ps, "sy_dist")
    out["mag"] = _num(ps, "sy_vmag")
    out["n_planets_system"] = _num(ps, "sy_pnum")
    out["ttv_flag"] = _num(ps, "ttv_flag").fillna(0).astype(int) == 1
    _triplet(out, ps, "period", "pl_orbper")
    _triplet(out, ps, "a_au", "pl_orbsmax")
    _triplet(out, ps, "ecc", "pl_orbeccen")
    _triplet(out, ps, "insol", "pl_insol")
    _triplet(out, ps, "st_teff", "st_teff")
    _triplet(out, ps, "st_rad", "st_rad")
    _triplet(out, ps, "st_mass", "st_mass")
    _triplet(out, ps, "st_logg", "st_logg")
    _triplet(out, ps, "st_age", "st_age")
    out["st_met"] = _num(ps, "st_met")
    lum, le1, le2 = _log_to_linear(_num(ps, "st_lum"), _num(ps, "st_lumerr1"), _num(ps, "st_lumerr2"))
    out["st_lum"], out["st_lum_e1"], out["st_lum_e2"] = lum, le1, le2

    # eccentricity upper limits are not measurements of e
    ecc_lim = _num(ps, "pl_orbeccenlim").fillna(0)
    out["ecc"] = out["ecc"].where(ecc_lim == 0)

    # radius: only transit (or radius-limit-free imaging) radii count as measured
    transiting = _num(ps, "tran_flag").fillna(0) == 1
    rad_lim = _num(ps, "pl_radelim").fillna(0)
    _triplet(out, ps, "radius", "pl_rade")
    out["radius_measured"] = transiting & (rad_lim == 0) & out["radius"].notna()
    for c in ("radius", "radius_e1", "radius_e2"):
        out[c] = out[c].where(out["radius_measured"])

    # mass
    _triplet(out, ps, "mass", "pl_bmasse")
    prov = ps["pl_bmassprov"].fillna("").astype(str)
    mlim = _num(ps, "pl_bmasselim").fillna(0)
    kind = np.select(
        [prov.eq("M-R relationship"), mlim.eq(1), mlim.eq(-1), prov.eq("Msini"), prov.isin(["Mass", "Msin(i)/sin(i)"])],
        ["none", "upper", "lower", "msini", "measured"],
        default="none",
    )
    kind = pd.Series(kind, index=ps.index)
    kind = kind.where(out["mass"].notna(), "none")
    out["mass_kind"] = kind
    for c in ("mass", "mass_e1", "mass_e2"):
        out[c] = out[c].where(kind != "none")
    return _finalise(out, ps.index)


TOI_LABELS = {"CP": 1.0, "KP": 1.0, "FP": 0.0, "FA": 0.0}


def harmonise_toi(toi: pd.DataFrame) -> pd.DataFrame:
    out: dict = {}
    toi_id = _num(toi, "toi")
    out["name"] = "TOI-" + toi_id.map(lambda x: f"{x:.2f}" if np.isfinite(x) else "nan")
    out["uid"] = "TOI:" + out["name"]
    out["host"] = "TIC " + _num(toi, "tid").map(lambda x: f"{int(x)}" if np.isfinite(x) else "nan")
    out["source"] = "toi"
    disp = toi["tfopwg_disp"].fillna("").astype(str)
    out["disposition"] = disp
    out["label_real"] = disp.map(TOI_LABELS).astype(float)
    out["controversial"] = False
    out["discovery_method"] = "Transit"
    out["ra"], out["dec"], out["dist_pc"] = _num(toi, "ra"), _num(toi, "dec"), _num(toi, "st_dist")
    out["mag"] = _num(toi, "st_tmag")
    out["n_planets_system"] = _num(toi, "pl_pnum")
    _triplet(out, toi, "period", "pl_orbper")
    _triplet(out, toi, "insol", "pl_insol")
    _triplet(out, toi, "radius", "pl_rade")
    out["radius_measured"] = out["radius"].notna()
    out["mass_kind"] = "none"
    _triplet(out, toi, "st_teff", "st_teff")
    _triplet(out, toi, "st_rad", "st_rad")
    _triplet(out, toi, "st_logg", "st_logg")
    # stellar mass from log g and radius (TOI table has no mass column)
    logg, r = out["st_logg"], out["st_rad"]
    m = pd.Series(mass_from_logg_radius(logg, r), index=toi.index)
    sl = np.sqrt((np.log(10) * 0.5 * (out["st_logg_e1"].abs() + out["st_logg_e2"].abs())) ** 2
                 + (2 * 0.5 * (out["st_rad_e1"].abs() + out["st_rad_e2"].abs()) / r) ** 2)
    sl = sl.clip(upper=1.0)
    out["st_mass"] = m
    out["st_mass_e1"] = m * (np.exp(sl) - 1)
    out["st_mass_e2"] = -m * (1 - np.exp(-sl))
    return _finalise(out, toi.index)


KOI_LABELS = {"CONFIRMED": 1.0, "FALSE POSITIVE": 0.0}


def harmonise_koi(koi: pd.DataFrame) -> pd.DataFrame:
    out: dict = {}
    out["name"] = koi["kepoi_name"].astype(str)
    out["uid"] = "KOI:" + out["name"]
    out["host"] = "KIC " + _num(koi, "kepid").map(lambda x: f"{int(x)}" if np.isfinite(x) else "nan")
    out["source"] = "koi"
    disp = koi["koi_disposition"].fillna("").astype(str)
    out["disposition"] = disp
    out["label_real"] = disp.map(KOI_LABELS).astype(float)
    out["controversial"] = False
    out["discovery_method"] = "Transit"
    out["ra"], out["dec"] = _num(koi, "ra"), _num(koi, "dec")
    out["mag"] = _num(koi, "koi_kepmag")
    out["n_planets_system"] = _num(koi, "koi_count")
    _triplet(out, koi, "period", "koi_period", "koi_period_err1", "koi_period_err2")
    _triplet(out, koi, "insol", "koi_insol", "koi_insol_err1", "koi_insol_err2")
    _triplet(out, koi, "radius", "koi_prad", "koi_prad_err1", "koi_prad_err2")
    out["radius_measured"] = out["radius"].notna()
    out["mass_kind"] = "none"
    out["a_au"] = _num(koi, "koi_sma")
    _triplet(out, koi, "st_teff", "koi_steff", "koi_steff_err1", "koi_steff_err2")
    _triplet(out, koi, "st_rad", "koi_srad", "koi_srad_err1", "koi_srad_err2")
    _triplet(out, koi, "st_mass", "koi_smass", "koi_smass_err1", "koi_smass_err2")
    _triplet(out, koi, "st_logg", "koi_slogg", "koi_slogg_err1", "koi_slogg_err2")
    _triplet(out, koi, "st_age", "koi_sage", "koi_sage_err1", "koi_sage_err2")
    out["st_met"] = _num(koi, "koi_smet")
    return _finalise(out, koi.index)


def build_planet_table(ps: pd.DataFrame | None, toi: pd.DataFrame | None, koi: pd.DataFrame | None) -> pd.DataFrame:
    """All sources stacked. Dispositioned TOIs/KOIs are kept (needed for vetting labels)."""
    parts = []
    if ps is not None:
        parts.append(harmonise_confirmed(ps))
    if toi is not None:
        parts.append(harmonise_toi(toi))
    if koi is not None:
        parts.append(harmonise_koi(koi))
    if not parts:
        raise ValueError("no input catalogues")
    df = pd.concat(parts, ignore_index=True)
    df["radius_measured"] = df["radius_measured"].fillna(False).astype(bool)
    df["controversial"] = df["controversial"].fillna(False).astype(bool)
    df["ttv_flag"] = df["ttv_flag"].fillna(False).astype(bool)
    return df


def scan_mask(df: pd.DataFrame) -> pd.Series:
    """Rows to score for habitability: confirmed planets + still-open candidates.

    TOIs/KOIs with planet dispositions are already in pscomppars and false
    positives are dropped, so nothing is counted twice.
    """
    open_toi = (df["source"] == "toi") & df["disposition"].isin(["PC", "APC"])
    open_koi = (df["source"] == "koi") & (df["disposition"] == "CANDIDATE")
    return (df["source"] == "confirmed") | open_toi | open_koi
