"""PubChem PUG-REST connector (NCBI).

Docs: https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest
Public, no key required. Returns structured dicts ready for an agent tool.
"""

from __future__ import annotations

import urllib.parse
from typing import Any, Dict, List

from .http import fetch_json

_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
_PROPS = "MolecularWeight,XLogP,TPSA,HBondDonorCount,HBondAcceptorCount,SMILES,IUPACName"


def compound_by_name(name: str) -> Dict[str, Any]:
    """Look up a compound's identity and key properties by common name."""
    q = urllib.parse.quote(name)
    url = f"{_BASE}/compound/name/{q}/property/{_PROPS}/JSON"
    data = fetch_json(url)
    props = data["PropertyTable"]["Properties"][0]
    return {
        "cid": props.get("CID"),
        "iupac_name": props.get("IUPACName"),
        "smiles": props.get("SMILES") or props.get("ConnectivitySMILES"),
        "mol_weight": props.get("MolecularWeight"),
        "xlogp": props.get("XLogP"),
        "tpsa": props.get("TPSA"),
        "h_bond_donors": props.get("HBondDonorCount"),
        "h_bond_acceptors": props.get("HBondAcceptorCount"),
        "source": "PubChem",
    }


def smiles_by_name(name: str) -> str:
    return compound_by_name(name)["smiles"]


def synonyms(cid: int, limit: int = 15) -> List[str]:
    url = f"{_BASE}/compound/cid/{cid}/synonyms/JSON"
    data = fetch_json(url)
    return data["InformationList"]["Information"][0]["Synonym"][:limit]
