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
