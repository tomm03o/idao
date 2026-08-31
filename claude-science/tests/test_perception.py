"""Tests for the perception layer (multi-level molecule/sequence views)."""

from claude_science.science.perception import MoleculeView, SequenceView, perceive


def test_molecule_view_layers():
    v = MoleculeView("CC(=O)Oc1ccccc1C(=O)O")  # aspirin
    d = v.to_dict()
    assert d["L0_identity"]["formula"] == "C9H8O4"
    assert d["L0_identity"]["inchikey"].startswith("BSYNRYMUTXBXSQ")
    assert d["L1_physicochemical"]["qed"] > 0
    # aspirin has a benzene ring and an ester
    assert d["L2_substructure"]["num_rings"] == 1
    assert "ester" in d["L2_substructure"]["functional_groups"]
    # pharmacophore features present (H-bond acceptors from the esters/acid)
    assert d["L3_pharmacophore"]["pharmacophore_features"].get("Acceptor", 0) >= 1


def test_molecule_scaffold_and_card():
    v = MoleculeView("COc1cc2ncnc(Nc3ccc(F)c(Cl)c3)c2cc1OCCCN1CCOCC1")  # gefitinib
    sub = v.substructure()
    assert "ncnc" in sub["murcko_scaffold"]      # quinazoline core retained
    card = v.card()
    assert "MOLECULE" in card and "scaffold" in card and "pharmacophore" in card


def test_molecule_geometry_is_3d():
    g = MoleculeView("CCO").geometry()
    assert g["embedded"] is True
    assert 0 <= g["npr1"] <= 1 and 0 <= g["npr2"] <= 1
    assert g["radius_of_gyration"] > 0


def test_sequence_view_dna():
    from claude_science.envs.data import REF_CDS
    v = SequenceView(REF_CDS)
    d = v.to_dict()
    assert v.kind == "dna"
    assert d["features"]["n_orfs"] >= 1
    assert 0 <= d["features"]["gc_content"] <= 1
    assert d["translation"].startswith("M")


def test_sequence_view_protein():
    v = SequenceView("MAEDPEVLKRIGDFGLATEKSRWSGSHQFEQLSGSILWMAPEVIR")
    assert v.kind == "protein"
    f = v.features()
    assert "grand_average_hydropathy" in f
    assert f["predicted_dominant_structure"] in ("helix", "sheet", "coil")
    assert f["molecular_weight_da"] > 0


def test_perceive_dispatches():
    assert "L0_identity" in perceive("CCO")               # molecule
    assert "composition" in perceive("ACGTACGTACGT")      # sequence


def test_perception_tools_registered():
    from claude_science.toolkits import science_tools
    reg = science_tools()
    assert "perceive_molecule" in reg.names()
    res = reg.dispatch("perceive_molecule", {"smiles": "CCO"})
    assert res.ok and "card" in res.content and "view" in res.content
