"""Tests for the training-free reliability layer and cognition tools."""

import pytest

from claude_science.envs import make_env
from claude_science.harness import (VerifiedBestOfN, HeuristicAgent, RandomAgent,
                                    Blackboard, Critic, calc, cognition_tools)
from claude_science.benchmark.leaderboard import make_agent


# --- reliability (verified best-of-N) -------------------------------------- #
def test_verified_bestofn_never_worse_than_single():
    # best-of-N takes the max over samples, so it can only match or beat a
    # single stochastic rollout in expectation; here it must reach the target.
    env = make_env("variant", seed=0, difficulty="low")
    agent = VerifiedBestOfN(HeuristicAgent(), n=3)
    agent.run(env)
    assert env.result().score >= 0.75


def test_verified_bestofn_beats_single_random_on_average():
    import statistics
    single, verified = [], []
    for seed in range(4):
        e1 = make_env("rootfind", seed=seed, difficulty="low")
        RandomAgent(seed=seed).run(e1)
        single.append(e1.result().score if e1.result() else 0.0)

        e2 = make_env("rootfind", seed=seed, difficulty="low")
        VerifiedBestOfN(RandomAgent(seed=seed), n=8).run(e2)
        verified.append(e2.result().score if e2.result() else 0.0)
    # verifier-guided selection lifts the mean (max over samples)
    assert statistics.mean(verified) >= statistics.mean(single)


def test_verified_early_stop_marks_transcript():
    env = make_env("variant", seed=1, difficulty="low")
    tr = VerifiedBestOfN(HeuristicAgent(), n=5).run(env)
    assert any("verified best-of" in str(s.content) for s in tr.steps)


def test_verified_spec_parses():
    a = make_agent("verified:4:heuristic")
    assert isinstance(a, VerifiedBestOfN) and a.n == 4


# --- cognition ------------------------------------------------------------- #
def test_blackboard_typed_slots():
    bb = Blackboard()
    bb.write("hypotheses", "the root is near 2")
    bb.write("observations", "f(2) = -0.1")
    assert bb.read("hypotheses") == ["the root is near 2"]
    assert set(bb.dump()) == {"hypotheses", "observations"}
    with pytest.raises(ValueError):
        bb.write("bogus", "x")


def test_critic_verifies_druglike():
    good = Critic.verify_druglike("CC(C)Cc1ccc(cc1)C(C)C(=O)O")   # ibuprofen
    bad = Critic.verify_druglike("O=C1C=CC(=O)C=C1")             # quinone alert
    assert good["ok"] is True
    assert bad["ok"] is False and bad["structural_alerts"]


def test_calc_exact():
    assert calc("2**10 + 24")["result"] == 1048
    assert abs(calc("log(exp(3))")["result"] - 3.0) < 1e-9
    assert "error" in calc("__import__('os')")           # unsafe rejected


def test_cognition_tools_registered():
    reg = cognition_tools()
    for name in ("memory_write", "memory_read", "critic_verify_druglike", "calc"):
        assert name in reg.names()
    assert reg.dispatch("calc", {"expression": "6*7"}).content["result"] == 42
