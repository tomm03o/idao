"""Tests for the Workbench backend handlers (Pillar 4).

Exercises the workbench.py functions directly (deterministic; the design/CRISPR/
depiction/perception/RAG paths need no network). The HTTP wiring in admin.py is a
thin adapter over these.
"""

from claude_science import workbench


def test_mol3d_sdf():
    sdf = workbench.mol3d_sdf("CCO")
    assert "V2000" in sdf and sdf.strip().endswith("$$$$") is False  # mol block
    assert "\n" in sdf


def test_mol2d_and_descriptors():
    assert "<svg" in workbench.mol2d_svg("CCO")
    d = workbench.descriptors("CC(=O)Oc1ccccc1C(=O)O")
    assert d["qed"] > 0 and "structural_alerts" in d


def test_perceive_endpoint():
    m = workbench.perceive("CCO")
    assert m["kind"] == "molecule" and "card" in m and "L4_geometry" in m["view"]
    s = workbench.perceive("MAEDPEVLKRIGDFG", kind="protein")
    assert s["kind"] == "sequence"


def test_design_endpoint_returns_depicted_candidates():
    r = workbench.design("CC(C)Cc1ccc(cc1)C(C)C(=O)O",
                         seed_smiles=["CC(=O)Oc1ccccc1C(=O)O",
                                      "Cn1cnc2c1c(=O)n(C)c(=O)n2C"],
                         generations=2, pop_size=16)
    assert r["candidates"]
    assert all("<svg" in c["svg"] and c["score"] > 0 for c in r["candidates"])


def test_crispr_endpoint():
    dna = "GGGACCTAGTCATTGGAGGTGACCCGGGATCGGACTGACGTGGTACCGATGCTAGCTAGG"
    r = workbench.crispr_guides(dna)
    assert r["n_guides"] >= 1 and r["top"]


def test_rag_endpoint_shared_router():
    workbench.rag("add", "molecule", doc_id="asp",
                  content="CC(=O)Oc1ccccc1C(=O)O")
    res = workbench.rag("search", "molecule", query="OC(=O)c1ccccc1O")
    assert res["hits"] and res["hits"][0]["doc_id"] == "asp"


def test_vendor_asset_served_and_path_safe():
    js = workbench.vendor_asset("3Dmol-min.js")
    assert len(js) > 100_000 and b"3Dmol" in js
    import pytest
    with pytest.raises(Exception):
        workbench.vendor_asset("../../etc/passwd")
