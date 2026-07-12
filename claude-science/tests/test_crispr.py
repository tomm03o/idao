"""Tests for the CRISPR gene-editing module and the guide-selection env."""

import pytest

from claude_science.science import crispr


GUIDE = "GTCACCTCCAATGACTAGGG"


def test_find_guides_enumerates_ngg_sites():
    dna = "AAAA" + "G" * 0 + "ACCTAGTCATTGGAGGTGACCCGGG" + "TTTTGG" * 3
    guides = crispr.find_guides(dna)
    assert guides
    for g in guides:
        assert len(g.protospacer) == 20
        assert g.pam[1:] == "GG"                 # NGG
        assert g.strand in ("+", "-")


def test_on_target_score_bounds_and_polyt_penalty():
    assert 0.0 <= crispr.on_target_score(GUIDE) <= 1.0
    good = crispr.on_target_score("GTCACCTCCAATGACTAGCG")
    polyt = crispr.on_target_score("GTCATTTTCAATGACTAGCG")  # poly-T terminator
    assert polyt < good
    assert crispr.on_target_score("TOO_SHORT") == 0.0


def test_cfd_seed_vs_distal_and_pam():
    # perfect match with NGG PAM = 1.0
    assert crispr.cfd_off_target(GUIDE, GUIDE, "GG") == pytest.approx(1.0)
    seed_mm = GUIDE[:19] + ("A" if GUIDE[19] != "A" else "C")
    distal_mm = ("A" if GUIDE[0] != "A" else "C") + GUIDE[1:]
    seed = crispr.cfd_off_target(GUIDE, seed_mm, "GG")
    distal = crispr.cfd_off_target(GUIDE, distal_mm, "GG")
    assert seed < distal                          # seed mismatch penalised harder
    assert distal > 0.7                           # distal mismatch tolerated
    # NAG PAM strongly reduces activity
    assert crispr.cfd_off_target(GUIDE, GUIDE, "AG") < 0.3


def test_cfd_validates_length():
    with pytest.raises(ValueError):
        crispr.cfd_off_target("ACGT", GUIDE, "GG")


def test_design_guides_report():
    dna = ("GGGACCTAGTCATTGGAGGTGACCCGGGATCGGACTGACGTGGTACCGATGCTAGCTAGG" * 2)
    rep = crispr.design_guides(dna, top_n=3)
    assert rep["n_guides"] >= 3 and len(rep["top"]) == 3
    assert rep["top"][0]["on_target"] >= rep["top"][-1]["on_target"]


def test_guide_env_solvable_and_beats_random():
    from claude_science.envs import make_env
    from claude_science.harness import HeuristicAgent, RandomAgent
    e = make_env("guide", seed=0, difficulty="low")
    HeuristicAgent().run(e)
    assert e.result().score >= 0.75
    r = make_env("guide", seed=0, difficulty="low")
    RandomAgent(seed=0).run(r)
    assert (r.result().score if r.result() else 0) <= e.result().score


def test_crispr_tools_registered():
    from claude_science.toolkits import science_tools
    reg = science_tools()
    assert "crispr_find_guides" in reg.names()
    res = reg.dispatch("crispr_find_guides", {"dna": "ACGTGGTACCGATGCTAGCTAGGGGG"})
    assert res.ok
