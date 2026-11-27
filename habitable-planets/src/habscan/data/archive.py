"""Download and cache source catalogues.

Sources
-------
* NASA Exoplanet Archive TAP service (https://exoplanetarchive.ipac.caltech.edu/TAP)
  - ``pscomppars``: one row per confirmed planet, composite best parameters.
  - ``toi``: TESS Objects of Interest with TFOPWG dispositions.
  - ``cumulative``: Kepler Objects of Interest (KOI) cumulative table.
* PHL Habitable Worlds Catalog (Planetary Habitability Laboratory, UPR Arecibo),
  used only as an external reference for benchmarking.

Every download writes ``<name>.csv`` plus ``<name>.meta.json`` (query, URL,
UTC timestamp, row count, sha256) so that every run is traceable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import pandas as pd
import requests

log = logging.getLogger(__name__)

TAP_URL = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
HWC_URL = "https://www.hpcf.upr.edu/~abel/phl/hwc/data/hwc.csv"


def _with_errors(*cols: str) -> list[str]:
    out = []
    for c in cols:
        out += [c, f"{c}err1", f"{c}err2"]
    return out


PSCOMPPARS_COLUMNS = (
    [
        "pl_name", "hostname", "tic_id", "gaia_dr3_id", "discoverymethod", "disc_year", "disc_facility",
        "pl_controv_flag", "tran_flag", "rv_flag", "ttv_flag", "sy_snum", "sy_pnum", "sy_dist", "sy_vmag", "sy_kmag",
        "ra", "dec", "pl_bmassprov", "pl_bmasselim", "pl_radelim", "pl_orbeccenlim", "st_spectype",
        "pl_eqt", "pl_orbincl", "st_met", "st_agelim",
    ]
    + _with_errors(
        "pl_orbper", "pl_orbsmax", "pl_orbeccen", "pl_rade", "pl_bmasse", "pl_insol",
        "st_teff", "st_rad", "st_mass", "st_lum", "st_logg", "st_age",
    )
)

KOI_COLUMNS = [
    "kepid", "kepoi_name", "kepler_name", "koi_disposition", "koi_pdisposition", "koi_score",
    "ra", "dec", "koi_kepmag", "koi_count", "koi_num_transits", "koi_max_sngle_ev", "koi_max_mult_ev",
    "koi_bin_oedp_sig", "koi_model_snr", "koi_model_chisq", "koi_model_dof",
    "koi_period", "koi_period_err1", "koi_period_err2", "koi_duration", "koi_duration_err1", "koi_duration_err2",
    "koi_depth", "koi_depth_err1", "koi_depth_err2", "koi_prad", "koi_prad_err1", "koi_prad_err2",
    "koi_impact", "koi_impact_err1", "koi_impact_err2", "koi_ror", "koi_ror_err1", "koi_ror_err2",
    "koi_dor", "koi_dor_err1", "koi_dor_err2", "koi_ingress", "koi_sma", "koi_eccen", "koi_incl",
    "koi_teq", "koi_insol", "koi_insol_err1", "koi_insol_err2",
    "koi_steff", "koi_steff_err1", "koi_steff_err2", "koi_slogg", "koi_slogg_err1", "koi_slogg_err2",
    "koi_smet", "koi_srad", "koi_srad_err1", "koi_srad_err2", "koi_smass", "koi_smass_err1", "koi_smass_err2",
    "koi_sage", "koi_sage_err1", "koi_sage_err2", "koi_srho", "koi_srho_err1", "koi_srho_err2",
    "koi_fwm_stat_sig", "koi_fwm_srao", "koi_fwm_sdeco", "koi_fwm_prao", "koi_fwm_pdeco",
    "koi_dicco_msky", "koi_dicco_msky_err", "koi_dikco_msky", "koi_dikco_msky_err",
    "koi_fpflag_nt", "koi_fpflag_ss", "koi_fpflag_co", "koi_fpflag_ec",
]

TABLES = {
    "pscomppars": f"select {','.join(PSCOMPPARS_COLUMNS)} from pscomppars",
    "toi": "select * from toi",
    "koi": f"select {','.join(KOI_COLUMNS)} from cumulative",
}


@dataclass
class FetchResult:
    name: str
    path: Path
    rows: int
    fetched_at: str


def _get(url: str, params: dict | None = None, retries: int = 4, timeout: int = 300) -> str:
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            return r.text
        except requests.RequestException as exc:  # network errors are retried with backoff
            last = exc
            wait = 2 ** (attempt + 1)
            log.warning("download failed (%s), retry in %ss", exc, wait)
            time.sleep(wait)
    raise RuntimeError(f"failed to download {url}: {last}")


def _write(raw_dir: Path, name: str, text: str, source: dict) -> FetchResult:
    raw_dir.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(StringIO(text), low_memory=False)
    if df.empty:
        raise RuntimeError(f"{name}: empty response")
    path = raw_dir / f"{name}.csv"
    path.write_text(text, encoding="utf-8")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta = dict(source, name=name, rows=len(df), fetched_at=now, sha256=hashlib.sha256(text.encode()).hexdigest())
    (raw_dir / f"{name}.meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    log.info("%s: %d rows -> %s", name, len(df), path)
    return FetchResult(name, path, len(df), now)


def fetch_tap_table(name: str, raw_dir: Path) -> FetchResult:
    query = TABLES[name]
    text = _get(TAP_URL, params={"query": query, "format": "csv"})
    return _write(raw_dir, name, text, {"url": TAP_URL, "query": query})


def fetch_hwc(raw_dir: Path) -> FetchResult:
    text = _get(HWC_URL)
    return _write(raw_dir, "hwc", text, {"url": HWC_URL})


def fetch_all(raw_dir: Path, include_hwc: bool = True) -> list[FetchResult]:
    results = [fetch_tap_table(n, raw_dir) for n in TABLES]
    if include_hwc:
        try:
            results.append(fetch_hwc(raw_dir))
        except RuntimeError as exc:
            log.warning("HWC reference catalogue unavailable: %s (benchmark vs HWC will be skipped)", exc)
    return results


def load_raw(raw_dir: Path, name: str) -> pd.DataFrame | None:
    path = raw_dir / f"{name}.csv"
    if not path.exists():
        return None
    return pd.read_csv(path, low_memory=False)


def raw_metadata(raw_dir: Path) -> dict:
    out = {}
    for p in sorted(raw_dir.glob("*.meta.json")):
        out[p.name.removesuffix(".meta.json")] = json.loads(p.read_text())
    return out
