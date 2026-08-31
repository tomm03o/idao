"""UniProt + RCSB PDB connectors (protein sequence & structure).

UniProt REST: https://rest.uniprot.org
RCSB PDB REST: https://data.rcsb.org
Both public, no key. Sequence retrieval is the entry point for the `variant`
and structure-based workflows.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .http import fetch_json, fetch_text

_UNIPROT = "https://rest.uniprot.org/uniprotkb"
_RCSB = "https://data.rcsb.org/rest/v1/core"


def protein(accession: str) -> Dict[str, Any]:
    """Fetch a UniProt entry: name, gene, length, organism, sequence."""
    fields = "accession,protein_name,gene_names,organism_name,sequence,length"
    data = fetch_json(f"{_UNIPROT}/{accession}.json?fields={fields}")
    name = (
        data.get("proteinDescription", {})
        .get("recommendedName", {})
        .get("fullName", {})
        .get("value")
    )
    genes = [g.get("geneName", {}).get("value") for g in data.get("genes", [])]
    return {
        "accession": data.get("primaryAccession"),
        "protein_name": name,
        "genes": [g for g in genes if g],
        "organism": data.get("organism", {}).get("scientificName"),
        "length": data.get("sequence", {}).get("length"),
        "sequence": data.get("sequence", {}).get("value"),
        "source": "UniProt",
    }


def sequence(accession: str) -> str:
    return protein(accession)["sequence"]


def search_protein(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    fields = "accession,protein_name,gene_names,organism_name,length"
    url = f"{_UNIPROT}/search?query={query}&fields={fields}&size={limit}&format=json"
    data = fetch_json(url)
    out = []
    for r in data.get("results", [])[:limit]:
        out.append({
            "accession": r.get("primaryAccession"),
            "organism": r.get("organism", {}).get("scientificName"),
            "length": r.get("sequence", {}).get("length"),
        })
    return out


def pdb_entry(pdb_id: str) -> Dict[str, Any]:
    """Structure metadata from RCSB PDB (title, method, resolution)."""
    data = fetch_json(f"{_RCSB}/entry/{pdb_id}")
    return {
        "pdb_id": pdb_id.upper(),
        "title": data.get("struct", {}).get("title"),
        "method": data.get("exptl", [{}])[0].get("method"),
        "resolution": (data.get("rcsb_entry_info", {})
                       .get("resolution_combined", [None])[0]),
        "source": "RCSB PDB",
    }
