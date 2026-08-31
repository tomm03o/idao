"""Tests for the type-specialized RAG suite (molecule / sequence / literature)."""

import pytest

from claude_science.rag import MoleculeRAG, SequenceRAG, LiteratureRAG, RAGRouter, rag_tools


def test_molecule_rag_retrieves_by_structure():
    rag = MoleculeRAG()
    rag.add("aspirin", "CC(=O)Oc1ccccc1C(=O)O")
    rag.add("caffeine", "Cn1cnc2c1c(=O)n(C)c(=O)n2C")
    rag.add("ibuprofen", "CC(C)Cc1ccc(cc1)C(C)C(=O)O")
    hits = rag.search("OC(=O)c1ccccc1O", k=2)      # salicylic acid
    assert hits[0]["doc_id"] == "aspirin"          # structurally nearest
    assert hits[0]["tanimoto"] > hits[1]["tanimoto"]


def test_molecule_rag_rejects_invalid():
    rag = MoleculeRAG()
    with pytest.raises(Exception):
        rag.add("bad", "not_a_smiles")


def test_sequence_rag_retrieves_homologs():
    rag = SequenceRAG()
    rag.add("close", "MAEDPEVLKRIGDFGLATEKSRWSGSHQFEQLSGSILW")
    rag.add("far", "QWERTYIPASDFGHKLCVNMQWERTY")
    hits = rag.search("MAEDPEVLKRIGDFGLATEKSRW", k=2)
    assert hits[0]["doc_id"] == "close"
    assert hits[0]["local_align_score"] > hits[-1]["local_align_score"]


def test_literature_rag_bm25():
    rag = LiteratureRAG()
    rag.add("d1", "Imatinib inhibits BCR-ABL tyrosine kinase in leukemia")
    rag.add("d2", "Aspirin inhibits cyclooxygenase reducing inflammation")
    hits = rag.search("kinase leukemia", k=1)
    assert hits and hits[0]["doc_id"] == "d1"


def test_router_dispatches_by_kind():
    r = RAGRouter()
    r.add("molecule", "asp", "CC(=O)Oc1ccccc1C(=O)O")
    r.add("sequence", "s1", "ACGTACGTACGTACGT")
    r.add("literature", "p1", "kinase inhibitor cancer therapy")
    assert r.search("molecule", "OC(=O)c1ccccc1O")[0]["doc_id"] == "asp"
    assert r.search("sequence", "ACGTACGTACGT")[0]["doc_id"] == "s1"
    assert r.search("literature", "cancer")[0]["doc_id"] == "p1"
    assert r.stats() == {"literature": 1, "molecule": 1, "sequence": 1}
    with pytest.raises(KeyError):
        r.search("nope", "x")


def test_rag_tools_registered():
    reg = rag_tools()
    for name in ("rag_add", "rag_molecule_search", "rag_sequence_search",
                 "rag_literature_search"):
        assert name in reg.names()
    reg.dispatch("rag_add", {"kind": "molecule", "doc_id": "a",
                             "content": "CCO"})
    assert reg.dispatch("rag_molecule_search", {"smiles": "CCO"}).ok
