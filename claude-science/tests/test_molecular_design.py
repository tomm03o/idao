"""Tests for the molecular design studio (Graph-GA + multi-objective scoring).

Deterministic, no network: uses the similarity objective and synthetic seeds.
The real target-guided discovery (ChEMBL) is exercised by the validation script.
"""

import pytest

from claude_science.research.molecular_design import (
    MultiObjectiveScorer, graph_ga, design_like,
)
from claude_science.science import chem

SEEDS = [
    "CC(=O)Oc1ccccc1C(=O)O",              # aspirin
    "CC(C)Cc1ccc(cc1)C(C)C(=O)O",         # ibuprofen
    "COc1cc2ncnc(Nc3ccc(F)c(Cl)c3)c2cc1OCCCN1CCOCC1",  # gefitinib
    "Cn1cnc2c1c(=O)n(C)c(=O)n2C",         # caffeine
]


def test_scorer_scores_druglike_positive():
    scorer = MultiObjectiveScorer(objective=lambda s: 0.5)
    assert scorer("CC(C)Cc1ccc(cc1)C(C)C(=O)O") > 0     # ibuprofen, drug-like
    comps = scorer.components("CC(C)Cc1ccc(cc1)C(C)C(=O)O")
    assert set(comps) == {"objective", "qed", "sa"}


def test_scorer_hard_filters_reject():
    scorer = MultiObjectiveScorer(objective=lambda s: 1.0)
    assert scorer("C" * 40) == 0.0                      # MW>500 AND logP>5: 2 Lipinski violations
    assert scorer("O=C1C=CC(=O)C=C1") == 0.0            # quinone structural alert
    assert scorer("not_a_smiles") == 0.0


def test_graph_ga_returns_valid_druglike_population():
    scorer = MultiObjectiveScorer(objective=lambda s: 0.5)
    pop = graph_ga(scorer, SEEDS, pop_size=20, generations=3, seed=0)
    assert len(pop) >= 5
    for c in pop:
        assert chem.canonical_smiles(c.smiles)          # parseable
        assert c.score > 0                              # drug-like (else filtered)
    # sorted best-first
    assert all(pop[i].score >= pop[i + 1].score for i in range(len(pop) - 1))


def test_design_like_optimises_toward_query():
    query = "COc1cc2ncnc(Nc3ccc(F)c(Cl)c3)c2cc1OCCCN1CCOCC1"  # gefitinib
    pop = design_like(query, SEEDS, pop_size=24, generations=4, seed=1)
    best_designed = max(chem.tanimoto(query, c.smiles) for c in pop[:10])
    # GA explores chemistry related to the query; every output is drug-like
    assert best_designed > 0.0
    assert all(c.score > 0 for c in pop)


def test_design_env_solvable_and_beats_random():
    from claude_science.envs import make_env
    from claude_science.harness import HeuristicAgent, RandomAgent
    e = make_env("design", seed=0, difficulty="low")
    HeuristicAgent().run(e)
    assert e.result().score >= 0.75
    r = make_env("design", seed=0, difficulty="low")
    RandomAgent(seed=0).run(r)
    assert (r.result().score if r.result() else 0) < e.result().score
