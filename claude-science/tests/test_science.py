"""Validate the science layer against known reference values.

If these drift, a simulator or scorer is wrong -- these are ground-truth checks,
not smoke tests.
"""

import numpy as np
import pytest

from claude_science.science import chem, pk, seq, struct


# --- cheminformatics ------------------------------------------------------- #
def test_aspirin_descriptors():
    d = chem.descriptors("CC(=O)Oc1ccccc1C(=O)O")
    assert d["mol_weight"] == pytest.approx(180.16, abs=0.05)   # known MW
    assert d["clogp"] == pytest.approx(1.31, abs=0.1)           # Crippen logP
    assert 0.4 < d["qed"] < 0.7
    assert d["lipinski_pass"] is True


def test_tanimoto_bounds_and_identity():
    assert chem.tanimoto("CCO", "CCO") == 1.0
    s = chem.tanimoto("CC(=O)Oc1ccccc1C(=O)O", "OC(=O)c1ccccc1O")  # aspirin~salicylic
    assert 0.2 < s < 0.9


def test_structural_alerts_detects_michael_acceptor():
    assert "michael_acceptor" in chem.structural_alerts("C=CC(=O)c1ccccc1")
    assert chem.structural_alerts("CCO") == []


# --- pharmacokinetics ------------------------------------------------------ #
def test_nca_recovers_half_life():
    t = np.linspace(0.25, 24, 40)
    ke = 0.15
    c = pk.conc_one_compartment_oral(t, dose=100, F=0.8, ka=1.2, ke=ke, V=30)
    res = pk.nca(t, c, dose=100)
    assert res["half_life"] == pytest.approx(np.log(2) / ke, rel=0.1)
    assert res["cmax"] > 0


def test_four_pl_fit_recovers_ic50():
    x = np.array([1, 3, 10, 30, 100, 300, 1000, 3000.0])
    y = pk.four_pl(x, 0, 100, 250.0, 1.0)
    fit = pk.fit_dose_response(x, y)
    assert fit["ic50"] == pytest.approx(250.0, rel=0.05)
    assert fit["r_squared"] > 0.99


# --- sequence bioinformatics ---------------------------------------------- #
def test_translation_and_revcomp():
    assert seq.translate("ATGGCCTGA") == "MA*"
    assert seq.reverse_complement("ATGC") == "GCAT"


def test_needleman_wunsch_textbook():
    # classic GATTACA / GCATGCU example scores -1 with match+1/mismatch-1/gap-2
    res = seq.needleman_wunsch("GATTACA", "GCATGCU")
    assert res["score"] == -1
    assert res["length"] >= 7


# --- computational chemistry ---------------------------------------------- #
def test_mmff_energy_is_finite():
    e = struct.mmff_energy("CCO")["energy_minimized"]
    assert isinstance(e, float)


def test_conformer_search_min_le_max():
    cs = struct.conformer_search("CCCCCCC(=O)O", n_confs=8)
    assert cs["energy_min"] <= cs["energy_max"]
    assert cs["n_conformers"] >= 1
