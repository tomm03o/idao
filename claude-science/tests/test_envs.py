"""Every environment must be solvable by its own reference policy.

This doubles as a correctness check on the simulators and scorers: if the
expert baseline can't score well, the environment is mis-specified.
"""

import pytest

from claude_science import make_env
from claude_science.envs import ENVIRONMENTS
from claude_science.harness import HeuristicAgent, RandomAgent


@pytest.mark.parametrize("key", list(ENVIRONMENTS))
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_reference_policy_solves(key, seed):
    env = make_env(key, seed=seed, difficulty="low")
    HeuristicAgent().run(env)
    sub = env.result()
    assert sub is not None, f"{key}: heuristic agent never submitted"
    assert sub.score >= 0.75, f"{key} seed={seed}: expert score too low ({sub.score})"


@pytest.mark.parametrize("key", list(ENVIRONMENTS))
def test_submit_ends_episode(key):
    env = make_env(key, seed=0)
    assert not env.is_done()
    HeuristicAgent().run(env)
    assert env.is_done()


@pytest.mark.parametrize("key", list(ENVIRONMENTS))
def test_expert_beats_random(key):
    expert_scores, random_scores = [], []
    for seed in range(4):
        e = make_env(key, seed=seed, difficulty="low")
        HeuristicAgent().run(e)
        expert_scores.append(e.result().score)

        r = make_env(key, seed=seed, difficulty="low")
        RandomAgent(seed=seed).run(r)
        rs = r.result()
        random_scores.append(rs.score if rs else 0.0)

    assert sum(expert_scores) / 4 > sum(random_scores) / 4


@pytest.mark.parametrize("key", list(ENVIRONMENTS))
def test_tools_have_submit(key):
    env = make_env(key, seed=0)
    assert "submit" in env.tools().names()
