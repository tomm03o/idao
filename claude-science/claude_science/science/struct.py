"""Validated molecular modelling / computational chemistry, backed by RDKit.

Real 3D structure generation and molecular-mechanics energetics:

* ETKDGv3 distance-geometry conformer embedding (Riniker & Landrum, 2015),
* MMFF94 force-field energy and minimisation (Halgren, 1996),
* multi-start conformer search returning the lowest-energy conformer and the
  conformational strain (energy above the found global minimum).

These are the same primitives used in real structure-based work: the numbers
are physical (kcal/mol), not a surrogate.
"""

from __future__ import annotations

from typing import Dict, List

from rdkit import Chem
from rdkit.Chem import AllChem


def _embed(smiles: str, seed: int) -> Chem.Mol:
    mol = Chem.AddHs(Chem.MolFromSmiles(smiles) or _raise(smiles))
    params = AllChem.ETKDGv3()
    params.randomSeed = seed
    if AllChem.EmbedMolecule(mol, params) != 0:
        raise RuntimeError(f"could not embed 3D coordinates for {smiles!r}")
    return mol


def _raise(smiles: str):
    raise ValueError(f"invalid SMILES: {smiles!r}")


def mmff_energy(smiles: str, seed: int = 0, minimize: bool = True) -> Dict[str, float]:
    """Embed one conformer and report its MMFF94 energy (kcal/mol)."""
    mol = _embed(smiles, seed)
    props = AllChem.MMFFGetMoleculeProperties(mol)
    if props is None:
        raise RuntimeError("MMFF94 not parameterised for this molecule")
    ff = AllChem.MMFFGetMoleculeForceField(mol, props)
    e_initial = ff.CalcEnergy()
    converged = 0
    if minimize:
        converged = ff.Minimize(maxIts=2000)
    return {
        "smiles": smiles,
        "seed": seed,
        "energy_initial": round(e_initial, 3),
        "energy_minimized": round(ff.CalcEnergy(), 3),
        "converged": converged == 0,
    }


def conformer_search(smiles: str, n_confs: int = 20) -> Dict[str, object]:
    """Multi-start MMFF94 conformer search.

    Generates ``n_confs`` ETKDG conformers, minimises each, and returns the
    lowest-energy conformer plus the spread (a proxy for flexibility).
    """
    mol = Chem.AddHs(Chem.MolFromSmiles(smiles) or _raise(smiles))
    params = AllChem.ETKDGv3()
    params.randomSeed = 0xC0FFEE
    ids = AllChem.EmbedMultipleConfs(mol, numConfs=n_confs, params=params)
    props = AllChem.MMFFGetMoleculeProperties(mol)
    if props is None:
        raise RuntimeError("MMFF94 not parameterised for this molecule")

    energies: List[float] = []
    for cid in ids:
        ff = AllChem.MMFFGetMoleculeForceField(mol, props, confId=cid)
        ff.Minimize(maxIts=2000)
        energies.append(round(ff.CalcEnergy(), 3))

    if not energies:
        raise RuntimeError("conformer generation failed")
    emin = min(energies)
    return {
        "smiles": smiles,
        "n_conformers": len(energies),
        "energy_min": emin,
        "energy_max": max(energies),
        "energy_spread": round(max(energies) - emin, 3),
        "energies": sorted(energies),
    }
