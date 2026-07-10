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
    return reg


def _merge(*registries: ToolRegistry) -> ToolRegistry:
    out = ToolRegistry()
    for reg in registries:
        for tool in reg.tools.values():
            out.register(tool)
    return out


def lab_bench(workspace: Workspace | None = None,
              with_databases: bool = True) -> ToolRegistry:
    """The full simulated-laboratory tool surface for an autonomous agent."""
    ws_reg = workspace_tools(workspace)
    parts = [science_tools(), ws_reg]
    if with_databases:
        parts.append(database_tools())
    merged = _merge(*parts)
    merged._workspace = getattr(ws_reg, "_workspace", None)
    return merged
