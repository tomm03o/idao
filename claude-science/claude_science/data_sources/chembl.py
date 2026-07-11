"""ChEMBL REST connector (EMBL-EBI).

Docs: https://www.ebi.ac.uk/chembl/api/data/docs
Bioactivity + drug data for target-based discovery. Public, no key.
"""

from __future__ import annotations

import urllib.parse
from typing import Any, Dict, List

from .http import fetch_json

_BASE = "https://www.ebi.ac.uk/chembl/api/data"


def molecule(chembl_id: str) -> Dict[str, Any]:
    """Fetch a molecule record (structure + properties) by ChEMBL ID."""
    data = fetch_json(f"{_BASE}/molecule/{chembl_id}.json")
    props = data.get("molecule_properties") or {}
    struct = data.get("molecule_structures") or {}
    return {
        "chembl_id": data.get("molecule_chembl_id"),
        "pref_name": data.get("pref_name"),
        "max_phase": data.get("max_phase"),
        "smiles": struct.get("canonical_smiles"),
        "mol_weight": props.get("full_mwt"),
        "alogp": props.get("alogp"),
        "qed_weighted": props.get("qed_weighted"),
        "source": "ChEMBL",
    }


def search_molecule(name: str, limit: int = 5) -> List[Dict[str, Any]]:
    q = urllib.parse.quote(name)
    url = f"{_BASE}/molecule/search.json?q={q}&limit={limit}"
    data = fetch_json(url)
    out = []
    for m in data.get("molecules", [])[:limit]:
        struct = m.get("molecule_structures") or {}
        out.append({
            "chembl_id": m.get("molecule_chembl_id"),
            "pref_name": m.get("pref_name"),
            "max_phase": m.get("max_phase"),
            "smiles": struct.get("canonical_smiles"),
        })
    return out


def activities_for_target(target_chembl_id: str, limit: int = 25,
                          standard_type: str = "IC50") -> List[Dict[str, Any]]:
    """Measured bioactivities (e.g. IC50 in nM) for a target -- QSAR fodder."""
    url = (f"{_BASE}/activity.json?target_chembl_id={target_chembl_id}"
           f"&standard_type={standard_type}&limit={limit}")
    data = fetch_json(url)
    out = []
    for a in data.get("activities", []):
        out.append({
            "molecule_chembl_id": a.get("molecule_chembl_id"),
            "canonical_smiles": a.get("canonical_smiles"),
            "standard_type": a.get("standard_type"),
            "standard_value": a.get("standard_value"),
            "standard_units": a.get("standard_units"),
            "pchembl_value": a.get("pchembl_value"),
        })
    return out


def target_dataset(target_chembl_id: str, max_records: int = 2000,
                   standard_type: str = "IC50"):
    """Build a clean (SMILES, pIC50) structure-activity dataset for a target.

    Paginates the activity endpoint (cached), keeps records with a SMILES and a
    concentration in nM, converts to pIC50 = 9 - log10(value_nM), and collapses
    duplicate measurements of the same molecule to their median. Returns a list
    of ``(smiles, pIC50)`` -- the substrate for QSAR / Bayesian optimisation.
    """
    import math

    by: Dict[str, List[float]] = {}
    fetched = 0
    for offset in range(0, max_records, 1000):
        n = min(1000, max_records - fetched)
        url = (f"{_BASE}/activity.json?target_chembl_id={target_chembl_id}"
               f"&standard_type={standard_type}&limit={n}&offset={offset}")
        data = fetch_json(url)
        rows = data.get("activities", [])
        if not rows:
            break
        for a in rows:
            smi = a.get("canonical_smiles")
            val = a.get("standard_value")
            if smi and val and a.get("standard_units") == "nM":
                try:
                    f = float(val)
                except (TypeError, ValueError):
                    continue
                if f > 0:
                    by.setdefault(smi, []).append(9.0 - math.log10(f))
        fetched += len(rows)
        if len(rows) < n:
            break

    import statistics
    out = []
    for smi, vals in by.items():
        p = statistics.median(vals)
        if 0.0 < p < 12.0:
            out.append((smi, round(p, 4)))
    return out
