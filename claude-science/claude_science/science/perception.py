"""Perception layer: multi-level representations agents can reason over.

LLMs see a SMILES string or a residue sequence as *tokens* and reason poorly about
the underlying object. This module builds a **derived, structured, multi-resolution
view** of a molecule / sequence so a model reasons over chemistry and biology rather
than characters — a "perception" pass before reasoning, analogous to visual features
for an image.

Each view exposes its layers as a dict and a compact text ``card()`` that can be
injected into an agent's context. All chemistry reuses the validated
:mod:`claude_science.science.chem` / :mod:`struct` layers; sequence analysis reuses
:mod:`seq`.

Molecule layers:  L0 identity · L1 physicochemical · L2 substructure/scaffold ·
L3 pharmacophore/electronic · L4 3D geometry (lazy).
Sequence layers:  composition · features (ORFs / hydrophobicity / secondary-structure
propensity) · translation.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Dict, List

from rdkit import Chem, RDConfig
from rdkit.Chem import (AllChem, ChemicalFeatures, Descriptors, rdMolDescriptors)
from rdkit.Chem.Scaffolds import MurckoScaffold

from . import chem, seq


@lru_cache(maxsize=1)
def _feature_factory():
    fdef = os.path.join(RDConfig.RDDataDir, "BaseFeatures.fdef")
    return ChemicalFeatures.BuildFeatureFactory(fdef)


@lru_cache(maxsize=1)
def _fr_descriptors():
    return [(n, getattr(Descriptors, n)) for n in dir(Descriptors)
            if n.startswith("fr_")]


# --------------------------------------------------------------------------- #
# Molecule
# --------------------------------------------------------------------------- #
class MoleculeView:
    """A layered, queryable representation of a molecule."""

    def __init__(self, smiles: str):
        self.mol = chem.parse(smiles)
        self.smiles = Chem.MolToSmiles(self.mol)

    # -- layers ---------------------------------------------------------- #
    def identity(self) -> Dict[str, Any]:
        return {
            "canonical_smiles": self.smiles,
            "inchikey": Chem.MolToInchiKey(self.mol),
            "formula": rdMolDescriptors.CalcMolFormula(self.mol),
            "mol_weight": round(Descriptors.MolWt(self.mol), 2),
            "heavy_atoms": self.mol.GetNumHeavyAtoms(),
        }

    def physicochemical(self) -> Dict[str, Any]:
        d = chem.descriptors(self.smiles)
        return {k: d[k] for k in ("clogp", "tpsa", "h_bond_donors",
                                  "h_bond_acceptors", "rotatable_bonds",
                                  "aromatic_rings", "fraction_csp3", "qed",
                                  "sa_score", "lipinski_pass", "veber_pass")}

    def substructure(self) -> Dict[str, Any]:
        scaffold = MurckoScaffold.GetScaffoldForMol(self.mol)
        ri = self.mol.GetRingInfo()
        ring_sizes = sorted(len(r) for r in ri.AtomRings())
        groups = {name[3:]: int(fn(self.mol)) for name, fn in _fr_descriptors()
                  if fn(self.mol) > 0}
        try:
            from rdkit.Chem import BRICS
            brics = sorted(BRICS.BRICSDecompose(self.mol))
        except Exception:
            brics = []
        return {
            "murcko_scaffold": Chem.MolToSmiles(scaffold) if scaffold.GetNumAtoms() else "",
            "num_rings": ri.NumRings(),
            "ring_sizes": ring_sizes,
            "functional_groups": dict(sorted(groups.items())),
            "brics_fragments": brics,
            "structural_alerts": chem.structural_alerts(self.smiles),
        }

    def pharmacophore(self) -> Dict[str, Any]:
        feats = _feature_factory().GetFeaturesForMol(self.mol)
        counts: Dict[str, int] = {}
        for f in feats:
            counts[f.GetFamily()] = counts.get(f.GetFamily(), 0) + 1
        AllChem.ComputeGasteigerCharges(self.mol)
        charges = [float(a.GetProp("_GasteigerCharge")) for a in self.mol.GetAtoms()
                   if a.HasProp("_GasteigerCharge")]
        charges = [c for c in charges if c == c]  # drop NaN
        return {
            "pharmacophore_features": dict(sorted(counts.items())),
            "gasteiger_charge_min": round(min(charges), 3) if charges else None,
            "gasteiger_charge_max": round(max(charges), 3) if charges else None,
        }

    def geometry(self, seed: int = 1) -> Dict[str, Any]:
        """3D shape descriptors (lazy — embeds a conformer)."""
        mh = Chem.AddHs(self.mol)
        if AllChem.EmbedMolecule(mh, randomSeed=seed) != 0:
            return {"embedded": False}
        AllChem.MMFFOptimizeMolecule(mh)
        return {
            "embedded": True,
            "npr1": round(rdMolDescriptors.CalcNPR1(mh), 3),
            "npr2": round(rdMolDescriptors.CalcNPR2(mh), 3),
            "radius_of_gyration": round(rdMolDescriptors.CalcRadiusOfGyration(mh), 3),
            "shape": _shape_label(rdMolDescriptors.CalcNPR1(mh),
                                  rdMolDescriptors.CalcNPR2(mh)),
        }

    def to_dict(self, with_geometry: bool = False) -> Dict[str, Any]:
        out = {
            "L0_identity": self.identity(),
            "L1_physicochemical": self.physicochemical(),
            "L2_substructure": self.substructure(),
            "L3_pharmacophore": self.pharmacophore(),
        }
        if with_geometry:
            out["L4_geometry"] = self.geometry()
        return out

    def card(self) -> str:
        i, p, s, ph = (self.identity(), self.physicochemical(),
                       self.substructure(), self.pharmacophore())
        fg = ", ".join(list(s["functional_groups"])[:8]) or "none"
        feats = ", ".join(f"{k}:{v}" for k, v in ph["pharmacophore_features"].items())
        alerts = ", ".join(s["structural_alerts"]) or "none"
        return (
            f"MOLECULE {i['formula']} (MW {i['mol_weight']}, {i['inchikey']})\n"
            f"  drug-likeness: QED {p['qed']}, SA {p['sa_score']}, "
            f"Lipinski {'pass' if p['lipinski_pass'] else 'FAIL'}, "
            f"cLogP {p['clogp']}, TPSA {p['tpsa']}\n"
            f"  scaffold: {s['murcko_scaffold'] or '(acyclic)'}  "
            f"({s['num_rings']} rings {s['ring_sizes']})\n"
            f"  functional groups: {fg}\n"
            f"  pharmacophore: {feats}\n"
            f"  structural alerts: {alerts}"
        )


def _shape_label(npr1: float, npr2: float) -> str:
    # normalized principal-moment-of-inertia triangle (Sauer & Schwarz 2003)
    if npr2 > 0.9 and npr1 < 0.4:
        return "rod-like"
    if npr1 > 0.4 and npr2 > 0.75:
        return "disc-like"
    return "sphere-like" if npr1 > 0.55 else "intermediate"


# --------------------------------------------------------------------------- #
# Sequence
# --------------------------------------------------------------------------- #
# Kyte-Doolittle hydropathy (J. Mol. Biol. 1982)
_KD = {"A": 1.8, "R": -4.5, "N": -3.5, "D": -3.5, "C": 2.5, "E": -3.5,
       "Q": -3.5, "G": -0.4, "H": -3.2, "I": 4.5, "L": 3.8, "K": -3.9,
       "M": 1.9, "F": 2.8, "P": -1.6, "S": -0.8, "T": -0.7, "W": -0.9,
       "Y": -1.3, "V": 4.2}
# Chou-Fasman conformational parameters (Adv. Enzymol. 1978)
_CF_HELIX = {"E": 1.51, "M": 1.45, "A": 1.42, "L": 1.21, "K": 1.16, "F": 1.13,
             "Q": 1.11, "W": 1.08, "I": 1.08, "V": 1.06, "D": 1.01, "H": 1.00,
             "R": 0.98, "T": 0.83, "S": 0.77, "C": 0.70, "Y": 0.69, "N": 0.67,
             "P": 0.57, "G": 0.57}
_CF_SHEET = {"V": 1.70, "I": 1.60, "Y": 1.47, "C": 1.19, "W": 1.37, "F": 1.38,
             "L": 1.30, "T": 1.19, "Q": 1.10, "M": 1.05, "R": 0.93, "N": 0.89,
             "H": 0.87, "A": 0.83, "S": 0.75, "G": 0.75, "K": 0.74, "P": 0.55,
             "D": 0.54, "E": 0.37}
_AA_MW = {"A": 71.08, "R": 156.19, "N": 114.10, "D": 115.09, "C": 103.14,
          "E": 129.12, "Q": 128.13, "G": 57.05, "H": 137.14, "I": 113.16,
          "L": 113.16, "K": 128.17, "M": 131.19, "F": 147.18, "P": 97.12,
          "S": 87.08, "T": 101.10, "W": 186.21, "Y": 163.18, "V": 99.13}


class SequenceView:
    """A layered representation of a nucleotide or protein sequence."""

    def __init__(self, sequence: str, kind: str = "auto"):
        self.seq = sequence.upper().strip()
        self.kind = self._detect() if kind == "auto" else kind

    def _detect(self) -> str:
        letters = set(self.seq)
        if letters <= set("ACGTUN"):
            return "dna"
        return "protein"

    def composition(self) -> Dict[str, Any]:
        from collections import Counter
        c = Counter(self.seq)
        return {"length": len(self.seq), "kind": self.kind,
                "composition": dict(sorted(c.items()))}

    def features(self) -> Dict[str, Any]:
        if self.kind == "dna":
            orfs = seq.find_orfs(self.seq, min_aa=10)
            return {
                "gc_content": seq.gc_content(self.seq),
                "n_orfs": len(orfs),
                "longest_orf_aa": orfs[0]["length_aa"] if orfs else 0,
                "longest_orf_protein": orfs[0]["protein"] if orfs else "",
            }
        return self._protein_features()

    def _protein_features(self) -> Dict[str, Any]:
        s = [a for a in self.seq if a in _KD]
        if not s:
            return {}
        n = len(s)
        kd = sum(_KD[a] for a in s) / n
        helix = sum(_CF_HELIX.get(a, 1.0) for a in s) / n
        sheet = sum(_CF_SHEET.get(a, 1.0) for a in s) / n
        mw = sum(_AA_MW.get(a, 110) for a in s) + 18.02
        aromatic = sum(s.count(a) for a in "FWY") / n
        pred = "helix" if helix > 1.03 and helix > sheet else (
            "sheet" if sheet > 1.05 else "coil")
        return {
            "mean_hydropathy_kd": round(kd, 3),
            "grand_average_hydropathy": round(kd, 3),
            "helix_propensity": round(helix, 3),
            "sheet_propensity": round(sheet, 3),
            "predicted_dominant_structure": pred,
            "aromatic_fraction": round(aromatic, 3),
            "molecular_weight_da": round(mw, 1),
        }

    def to_dict(self) -> Dict[str, Any]:
        out = {"composition": self.composition(), "features": self.features()}
        if self.kind == "dna":
            out["translation"] = seq.translate(self.seq)
        return out

    def card(self) -> str:
        comp = self.composition()
        feat = self.features()
        head = f"SEQUENCE ({self.kind}, {comp['length']} residues)"
        if self.kind == "dna":
            return (f"{head}\n  GC {feat.get('gc_content')}, "
                    f"{feat.get('n_orfs')} ORFs, longest {feat.get('longest_orf_aa')} aa\n"
                    f"  protein: {feat.get('longest_orf_protein', '')[:60]}")
        return (f"{head}\n  hydropathy(KD) {feat.get('grand_average_hydropathy')}, "
                f"helix {feat.get('helix_propensity')} / sheet {feat.get('sheet_propensity')} "
                f"→ {feat.get('predicted_dominant_structure')}, "
                f"MW {feat.get('molecular_weight_da')} Da")


# --------------------------------------------------------------------------- #
def perceive(obj: str, kind: str = "auto") -> Dict[str, Any]:
    """Best-effort perception: molecule if it parses as SMILES, else sequence."""
    if kind in ("molecule", "smiles"):
        return MoleculeView(obj).to_dict()
    if kind in ("dna", "protein", "sequence"):
        return SequenceView(obj, kind="auto" if kind == "sequence" else kind).to_dict()
    try:
        return MoleculeView(obj).to_dict()
    except Exception:
        return SequenceView(obj).to_dict()
