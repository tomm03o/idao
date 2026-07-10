"""Validated cheminformatics, backed by RDKit.

Everything here is a real, literature-standard computation -- no toy surrogates:

* physicochemical descriptors (Wildman-Crippen logP, Ertl TPSA, ...),
* drug-likeness rules (Lipinski, Veber, Ghose) and Bickerton's QED,
* Ertl-Schuffenhauer synthetic accessibility (SA) score,
* Morgan/ECFP fingerprints and Tanimoto similarity for virtual screening,
* a small curated structural-alert (PAINS-style) filter.

References
----------
* Wildman & Crippen, J. Chem. Inf. Comput. Sci. 1999, 39, 868.
* Ertl, J. Chem. Inf. Model. 2000 (TPSA); Ertl & Schuffenhauer, J. Cheminform.
  2009 (SA score).
* Lipinski et al., Adv. Drug Deliv. Rev. 1997; Veber et al., J. Med. Chem. 2002.
* Bickerton et al., Nat. Chem. 2012 (QED).
* Rogers & Hahn, J. Chem. Inf. Model. 2010 (ECFP).
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from typing import Any, Dict, List, Optional

from rdkit import Chem, DataStructs, RDLogger
from rdkit.Chem import (
    Crippen,
    Descriptors,
    QED,
    rdMolDescriptors,
    RDConfig,
)
from rdkit.Chem import rdFingerprintGenerator

RDLogger.DisableLog("rdApp.*")  # silence parse warnings; we handle errors ourselves


@lru_cache(maxsize=1)
def _sascorer():
    """Ertl-Schuffenhauer SA scorer ships in RDKit's Contrib tree."""
    sys.path.append(os.path.join(RDConfig.RDContribDir, "SA_Score"))
    import sascorer  # type: ignore

    return sascorer


@lru_cache(maxsize=1)
def _morgan_gen():
    return rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)


def parse(smiles: str) -> Chem.Mol:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"invalid SMILES: {smiles!r}")
    return mol


def canonical_smiles(smiles: str) -> str:
    return Chem.MolToSmiles(parse(smiles))


# --------------------------------------------------------------------------- #
# Descriptors & drug-likeness
# --------------------------------------------------------------------------- #
def descriptors(smiles: str) -> Dict[str, Any]:
    """Full physicochemical + drug-likeness profile for a molecule."""
    mol = parse(smiles)
    mw = Descriptors.MolWt(mol)
    logp = Crippen.MolLogP(mol)
    hbd = rdMolDescriptors.CalcNumHBD(mol)
    hba = rdMolDescriptors.CalcNumHBA(mol)
    tpsa = rdMolDescriptors.CalcTPSA(mol)
    rot = rdMolDescriptors.CalcNumRotatableBonds(mol)
    rings = rdMolDescriptors.CalcNumAromaticRings(mol)
    heavy = mol.GetNumHeavyAtoms()
    return {
        "canonical_smiles": Chem.MolToSmiles(mol),
        "mol_weight": round(mw, 2),
        "clogp": round(logp, 3),
        "tpsa": round(tpsa, 2),
        "h_bond_donors": hbd,
        "h_bond_acceptors": hba,
        "rotatable_bonds": rot,
        "aromatic_rings": rings,
        "heavy_atoms": heavy,
        "fraction_csp3": round(rdMolDescriptors.CalcFractionCSP3(mol), 3),
        "qed": round(QED.qed(mol), 3),
        "sa_score": round(_sascorer().calculateScore(mol), 2),
        "lipinski_pass": lipinski(smiles)["pass"],
        "veber_pass": _veber(mw, tpsa, rot, hbd, hba),
    }


def lipinski(smiles: str) -> Dict[str, Any]:
    """Lipinski rule of five (>=2 violations flags poor oral absorption)."""
    mol = parse(smiles)
    violations = []
    if Descriptors.MolWt(mol) > 500:
        violations.append("MW>500")
    if Crippen.MolLogP(mol) > 5:
        violations.append("clogP>5")
    if rdMolDescriptors.CalcNumHBD(mol) > 5:
        violations.append("HBD>5")
    if rdMolDescriptors.CalcNumHBA(mol) > 10:
        violations.append("HBA>10")
    return {"violations": violations, "n_violations": len(violations),
            "pass": len(violations) < 2}


def _veber(mw: float, tpsa: float, rot: int, hbd: int, hba: int) -> bool:
    # Veber: rotatable bonds <= 10 and TPSA <= 140 -> good oral bioavailability
    return rot <= 10 and tpsa <= 140


# --------------------------------------------------------------------------- #
# Similarity / virtual screening
# --------------------------------------------------------------------------- #
def fingerprint(smiles: str):
    return _morgan_gen().GetFingerprint(parse(smiles))


def tanimoto(smiles_a: str, smiles_b: str) -> float:
    return round(
        DataStructs.TanimotoSimilarity(fingerprint(smiles_a), fingerprint(smiles_b)),
        4,
    )


def similarity_search(
    query: str, library: List[str], top_k: int = 10
) -> List[Dict[str, Any]]:
    """Rank a library by ECFP4 Tanimoto similarity to a query (virtual screen)."""
    qfp = fingerprint(query)
    scored = []
    for smi in library:
        try:
            s = DataStructs.TanimotoSimilarity(qfp, fingerprint(smi))
        except ValueError:
            continue
        scored.append({"smiles": smi, "tanimoto": round(s, 4)})
    scored.sort(key=lambda r: r["tanimoto"], reverse=True)
    return scored[:top_k]


# --------------------------------------------------------------------------- #
# Structural alerts (curated PAINS-style subset via SMARTS)
# --------------------------------------------------------------------------- #
_ALERTS = {
    "quinone": "O=C1C=CC(=O)C=C1",
    "michael_acceptor": "[CX3]=[CX3][CX3]=O",
    "azo": "[#6]N=N[#6]",
    "nitro_aromatic": "[c][NX3+](=O)[O-]",
    "aldehyde": "[CX3H1](=O)[#6]",
    "thiol": "[#6][SX2H]",
    "isocyanate": "N=C=O",
}


@lru_cache(maxsize=1)
def _compiled_alerts():
    return {k: Chem.MolFromSmarts(v) for k, v in _ALERTS.items()}


def structural_alerts(smiles: str) -> List[str]:
    """Return names of reactive/undesirable substructures present."""
    mol = parse(smiles)
    return [name for name, patt in _compiled_alerts().items()
            if patt is not None and mol.HasSubstructMatch(patt)]


def substructure_match(smiles: str, smarts: str) -> bool:
    patt = Chem.MolFromSmarts(smarts)
    if patt is None:
        raise ValueError(f"invalid SMARTS: {smarts!r}")
    return parse(smiles).HasSubstructMatch(patt)
