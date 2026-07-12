"""Composed toolkits: assemble the whole platform into one tool surface.

``lab_bench`` gives an agent the full "simulated laboratory": validated science
functions + live database access + a sandboxed workspace/terminal. Point a real
Claude agent at this registry and it can plan and run open-ended computational
experiments -- look up a target, pull known actives, compute descriptors, fit a
model, write and execute analysis code, and save results -- autonomously.
"""

from __future__ import annotations

from typing import Any, Dict

from .harness.tools import ToolRegistry
from .science import chem, pk, seq, struct
from .workspace import Workspace, workspace_tools
from .data_sources import database_tools


def science_tools() -> ToolRegistry:
    """Expose the validated science layer as callable tools."""
    reg = ToolRegistry()
    reg.add("chem_descriptors",
            "Full RDKit physicochemical / drug-likeness profile of a SMILES "
            "(MW, cLogP, TPSA, QED, SA score, Lipinski/Veber).",
            {"type": "object", "properties": {"smiles": {"type": "string"}},
             "required": ["smiles"]}, chem.descriptors)
    reg.add("chem_tanimoto",
            "ECFP4 Tanimoto similarity between two SMILES.",
            {"type": "object", "properties": {"smiles_a": {"type": "string"},
             "smiles_b": {"type": "string"}}, "required": ["smiles_a", "smiles_b"]},
            chem.tanimoto)
    reg.add("chem_alerts",
            "Reactive/undesirable substructure (PAINS-style) alerts in a SMILES.",
            {"type": "object", "properties": {"smiles": {"type": "string"}},
             "required": ["smiles"]}, chem.structural_alerts)
    reg.add("pk_nca",
            "Non-compartmental analysis of a concentration-time profile "
            "(Cmax, AUC, half-life, CL/F).",
            {"type": "object", "properties": {
                "times": {"type": "array", "items": {"type": "number"}},
                "concs": {"type": "array", "items": {"type": "number"}},
                "dose": {"type": "number"}}, "required": ["times", "concs"]},
            lambda times, concs, dose=None: pk.nca(times, concs, dose))
    reg.add("pk_fit_dose_response",
            "Fit a 4-parameter logistic curve; returns IC50 with SE and R^2.",
            {"type": "object", "properties": {
                "concentrations": {"type": "array", "items": {"type": "number"}},
                "responses": {"type": "array", "items": {"type": "number"}}},
             "required": ["concentrations", "responses"]},
            pk.fit_dose_response)
    reg.add("seq_align",
            "Needleman-Wunsch global alignment of two sequences.",
            {"type": "object", "properties": {"seq1": {"type": "string"},
             "seq2": {"type": "string"}}, "required": ["seq1", "seq2"]},
            seq.needleman_wunsch)
    reg.add("seq_translate",
            "Translate a DNA coding sequence to protein (1-letter).",
            {"type": "object", "properties": {"dna": {"type": "string"}},
             "required": ["dna"]}, lambda dna: {"protein": seq.translate(dna)})
    reg.add("struct_conformer_search",
            "Multi-start ETKDG + MMFF94 conformer search; returns min/max/spread "
            "energies (kcal/mol).",
            {"type": "object", "properties": {"smiles": {"type": "string"},
             "n_conformers": {"type": "integer", "minimum": 1, "maximum": 60}},
             "required": ["smiles"]},
            lambda smiles, n_conformers=20: struct.conformer_search(smiles, n_conformers))
    reg.add("design_similar_molecules",
            "Goal-directed de novo design (Graph-GA): generate drug-like molecules "
            "similar to a query SMILES. Returns ranked candidates with scores.",
            {"type": "object", "properties": {
                "query_smiles": {"type": "string"},
                "seed_smiles": {"type": "array", "items": {"type": "string"}},
                "generations": {"type": "integer", "minimum": 1, "maximum": 12}},
             "required": ["query_smiles", "seed_smiles"]},
            _design_similar)
    reg.add("perceive_molecule",
            "Build a multi-level structural view of a molecule so you can reason "
            "over its chemistry, not its SMILES tokens: identity, drug-likeness, "
            "Murcko scaffold, functional groups, pharmacophore features, 3D shape. "
            "Returns a structured view and a compact text card.",
            {"type": "object", "properties": {"smiles": {"type": "string"},
             "with_geometry": {"type": "boolean"}}, "required": ["smiles"]},
            _perceive_molecule)
    reg.add("perceive_sequence",
            "Build a multi-level view of a DNA/protein sequence: composition, GC / "
            "ORFs (DNA) or hydropathy + secondary-structure propensity (protein).",
            {"type": "object", "properties": {"sequence": {"type": "string"},
             "kind": {"type": "string", "enum": ["auto", "dna", "protein"]}},
             "required": ["sequence"]},
            _perceive_sequence)
    reg.add("crispr_find_guides",
            "Enumerate candidate CRISPR-Cas9 sgRNA protospacers (NGG PAM, both "
            "strands) in a DNA locus, ranked by on-target efficiency.",
            {"type": "object", "properties": {"dna": {"type": "string"},
             "top_n": {"type": "integer", "minimum": 1, "maximum": 50}},
             "required": ["dna"]},
            _crispr_find_guides)
    reg.add("crispr_off_target_cfd",
            "CFD-style off-target activity (0-1) of a 20 nt guide against a 20 nt "
            "off-target site with the given 2 nt PAM ('GG' for NGG).",
            {"type": "object", "properties": {"guide": {"type": "string"},
             "off_target": {"type": "string"}, "off_pam": {"type": "string"}},
             "required": ["guide", "off_target"]},
            _crispr_off_target)
    return reg


def _perceive_molecule(smiles, with_geometry=False):
    from .science.perception import MoleculeView
    v = MoleculeView(smiles)
    return {"view": v.to_dict(with_geometry=with_geometry), "card": v.card()}


def _perceive_sequence(sequence, kind="auto"):
    from .science.perception import SequenceView
    v = SequenceView(sequence, kind=kind)
    return {"view": v.to_dict(), "card": v.card()}


def _crispr_find_guides(dna, top_n=8):
    from .science import crispr
    guides = sorted(crispr.find_guides(dna), key=lambda g: g.on_target,
                    reverse=True)[:top_n]
    return [{"protospacer": g.protospacer, "pam": g.pam, "strand": g.strand,
             "start": g.start, "on_target": round(g.on_target, 3)} for g in guides]


def _crispr_off_target(guide, off_target, off_pam="GG"):
    from .science import crispr
    return {"cfd": crispr.cfd_off_target(guide, off_target, off_pam)}


def _design_similar(query_smiles, seed_smiles, generations=5):
    from .research.molecular_design import design_like
    pop = design_like(query_smiles, seed_smiles, pop_size=30,
                      generations=generations)
    return [{"smiles": c.smiles, "score": c.score} for c in pop[:10]]


def _merge(*registries: ToolRegistry) -> ToolRegistry:
    out = ToolRegistry()
    for reg in registries:
        for tool in reg.tools.values():
            out.register(tool)
    return out


def lab_bench(workspace: Workspace | None = None,
              with_databases: bool = True, with_rag: bool = True) -> ToolRegistry:
    """The full simulated-laboratory tool surface for an autonomous agent."""
    from .rag import rag_tools
    ws_reg = workspace_tools(workspace)
    parts = [science_tools(), ws_reg]
    if with_databases:
        parts.append(database_tools())
    rag_reg = None
    if with_rag:
        rag_reg = rag_tools()
        parts.append(rag_reg)
    merged = _merge(*parts)
    merged._workspace = getattr(ws_reg, "_workspace", None)
    merged._rag_router = getattr(rag_reg, "_router", None)
    return merged
