"""Expose the database connectors as harness tools an agent can call.

    from claude_science.data_sources import database_tools
    reg = database_tools()          # a ToolRegistry
    reg.dispatch("pubchem_compound", {"name": "imatinib"})
"""

from __future__ import annotations

from ..harness.tools import ToolRegistry
from . import chembl, pubchem, uniprot


def database_tools() -> ToolRegistry:
    reg = ToolRegistry()

    reg.add(
        "pubchem_compound",
        "Look up a compound in PubChem by name; returns CID, SMILES and "
        "physicochemical properties.",
        {"type": "object", "properties": {"name": {"type": "string"}},
         "required": ["name"]},
        lambda name: pubchem.compound_by_name(name),
    )
    reg.add(
        "chembl_molecule",
        "Fetch a ChEMBL molecule record (structure, max clinical phase, QED) "
        "by ChEMBL ID, e.g. CHEMBL25.",
        {"type": "object", "properties": {"chembl_id": {"type": "string"}},
         "required": ["chembl_id"]},
        lambda chembl_id: chembl.molecule(chembl_id),
    )
    reg.add(
        "chembl_target_activities",
        "Retrieve measured bioactivities (e.g. IC50 in nM) for a ChEMBL target "
        "ID -- raw material for a QSAR model.",
        {"type": "object",
         "properties": {"target_chembl_id": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100}},
         "required": ["target_chembl_id"]},
        lambda target_chembl_id, limit=25: chembl.activities_for_target(
            target_chembl_id, limit=limit),
    )
    reg.add(
        "uniprot_protein",
        "Fetch a UniProt entry (name, gene, organism, sequence) by accession, "
        "e.g. P00533.",
        {"type": "object", "properties": {"accession": {"type": "string"}},
         "required": ["accession"]},
        lambda accession: uniprot.protein(accession),
    )
    reg.add(
        "pdb_entry",
        "Fetch structure metadata (title, method, resolution) from RCSB PDB by "
        "4-character PDB ID, e.g. 4HHB.",
        {"type": "object", "properties": {"pdb_id": {"type": "string"}},
         "required": ["pdb_id"]},
        lambda pdb_id: uniprot.pdb_entry(pdb_id),
    )
    return reg
