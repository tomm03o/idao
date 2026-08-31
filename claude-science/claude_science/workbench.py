"""Backend handlers for the local Workbench app (Pillar 4).

Thin, dependency-free functions the admin HTTP server calls to power the IDE
panels: 3D/2D depiction, descriptors, perception, de novo design, CRISPR guide
design, and a shared type-specialized RAG router. All reuse the validated
science + research layers.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Dict, List

VENDOR = os.path.join(os.path.dirname(__file__), "..", "dashboard", "vendor")


# --------------------------------------------------------------------------- #
# Depiction / descriptors / perception
# --------------------------------------------------------------------------- #
def mol3d_sdf(smiles: str, seed: int = 1) -> str:
    """3D coordinates as an SDF mol-block (for the 3Dmol.js viewer)."""
    from rdkit import Chem
    from rdkit.Chem import AllChem
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"invalid SMILES: {smiles!r}")
    mol = Chem.AddHs(mol)
    if AllChem.EmbedMolecule(mol, randomSeed=seed) != 0:
        raise RuntimeError("could not embed 3D coordinates")
    AllChem.MMFFOptimizeMolecule(mol)
    return Chem.MolToMolBlock(mol)


def mol2d_svg(smiles: str) -> str:
    from .science import chem
    return chem.to_svg(smiles, 320, 240)


def descriptors(smiles: str) -> Dict[str, Any]:
    from .science import chem
    d = chem.descriptors(smiles)
    d["structural_alerts"] = chem.structural_alerts(smiles)
    return d


def perceive(obj: str, kind: str = "auto") -> Dict[str, Any]:
    from .science.perception import MoleculeView, SequenceView
    if kind in ("dna", "protein", "sequence"):
        v = SequenceView(obj, kind="auto" if kind == "sequence" else kind)
        return {"kind": "sequence", "card": v.card(), "view": v.to_dict()}
    try:
        v = MoleculeView(obj)
        return {"kind": "molecule", "card": v.card(),
                "view": v.to_dict(with_geometry=True)}
    except Exception:
        v = SequenceView(obj)
        return {"kind": "sequence", "card": v.card(), "view": v.to_dict()}


# --------------------------------------------------------------------------- #
# Studios
# --------------------------------------------------------------------------- #
def design(query_smiles: str, seed_smiles: List[str] | None = None,
           generations: int = 5, pop_size: int = 30) -> Dict[str, Any]:
    """Similarity-guided de novo design; returns ranked candidates + depictions."""
    from .research.molecular_design import design_like
    from .science import chem
    from .envs.data import DRUGS
    seeds = seed_smiles or [s for _, s in DRUGS[:6]]
    pop = design_like(query_smiles, seeds, pop_size=pop_size,
                      generations=generations)
    out = []
    for c in pop[:12]:
        d = chem.descriptors(c.smiles)
        out.append({"smiles": c.smiles, "score": c.score,
                    "qed": d["qed"], "mol_weight": d["mol_weight"],
                    "tanimoto_to_query": chem.tanimoto(query_smiles, c.smiles),
                    "svg": chem.to_svg(c.smiles, 200, 150)})
    return {"query": query_smiles, "candidates": out}


def crispr_guides(dna: str, top_n: int = 8) -> Dict[str, Any]:
    from .science import crispr
    return crispr.design_guides(dna, top_n=top_n)


# --------------------------------------------------------------------------- #
# Shared RAG router (one per server process)
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def rag_router():
    from .rag import RAGRouter
    return RAGRouter()


def rag(action: str, kind: str = "literature", query: str = "",
        doc_id: str = "", content: str = "", k: int = 5) -> Any:
    r = rag_router()
    if action == "add":
        return {"message": r.add(kind, doc_id, content)}
    if action == "ingest" and kind == "literature":
        n = r.literature.ingest_europepmc(query, limit=k)
        return {"ingested": n, "query": query}
    if action == "search":
        return {"kind": kind, "hits": r.search(kind, query, k)}
    raise ValueError(f"bad rag action {action!r}")


# --------------------------------------------------------------------------- #
def vendor_asset(name: str) -> bytes:
    """Read a vendored static asset (e.g. 3Dmol-min.js). Path-safe."""
    safe = os.path.basename(name)
    path = os.path.realpath(os.path.join(VENDOR, safe))
    if not path.startswith(os.path.realpath(VENDOR)):
        raise ValueError("bad asset path")
    with open(path, "rb") as fh:
        return fh.read()
