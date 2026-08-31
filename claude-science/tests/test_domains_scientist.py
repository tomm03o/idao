"""Tests for the numerics domain (harness generality) and the ScientistAgent
scientific-method scaffold (agent structure). No network required.
"""

import pytest

from claude_science.envs import make_env, envs_by_domain, ENVIRONMENTS
from claude_science.harness import HeuristicAgent, RandomAgent, ScientistAgent
from claude_science.benchmark.leaderboard import make_agent


NUMERICS = ["rootfind", "optimize", "quadrature", "eigenvalue"]


# --- domain generality ----------------------------------------------------- #
def test_platform_spans_multiple_domains():
    domains = envs_by_domain()
    assert "life-sciences" in domains and "numerics" in domains
    assert set(NUMERICS) <= set(domains["numerics"])


@pytest.mark.parametrize("key", NUMERICS)
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_numerics_reference_policy_solves(key, seed):
    env = make_env(key, seed=seed, difficulty="low")
    HeuristicAgent().run(env)
    sub = env.result()
    assert sub is not None and sub.score >= 0.75, f"{key}/{seed}: {sub.score}"


@pytest.mark.parametrize("key", NUMERICS)
def test_numerics_system_prompt_is_domain_specific(key):
    env = make_env(key, seed=0)
    assert env.domain == "numerics"
    assert "biological" not in env.system_prompt().lower()
    assert "numerical" in env.system_prompt().lower() or \
           "mathematics" in env.system_prompt().lower()


# --- scientist scaffold ----------------------------------------------------- #
class _FakeBackend:
    name = "fake"
    max_steps = 12

    def __init__(self):
        self.plan_calls = 0

    def complete(self, prompt, system=""):
        self.plan_calls += 1
        assert "HYPOTHESIS" in prompt
        return "HYPOTHESIS: x. EXPERIMENTS: y. DECISION: z."

    def run(self, env):
        # plan must have been injected into the (proxied) task
        assert "PRE-REGISTERED PLAN" in env.task_prompt()
        return HeuristicAgent().run(env)


def test_scientist_wraps_and_solves():
    backend = _FakeBackend()
    env = make_env("optimize", seed=1, difficulty="low")
    tr = ScientistAgent(backend).run(env)
    assert backend.plan_calls == 1
    assert tr.steps[0].kind == "plan"
    assert tr.agent == "scientist:fake"
    assert env.result().score >= 0.75


def test_scientist_survives_planning_failure():
    class Broken(_FakeBackend):
        def complete(self, prompt, system=""):
            raise RuntimeError("model down")
    env = make_env("rootfind", seed=0, difficulty="low")
    tr = ScientistAgent(Broken()).run(env)
    # still runs and solves; plan step records the failure
    assert tr.steps[0].kind == "plan"
    assert "unavailable" in tr.steps[0].content
    assert env.result().score >= 0.75


def test_scientist_requires_valid_backend():
    with pytest.raises(TypeError):
        ScientistAgent(object())


def test_scientist_spec_parsing():
    a = make_agent("scientist:heuristic")
    assert isinstance(a, ScientistAgent)
    assert a.base.__class__.__name__ == "HeuristicAgent"


def test_scientist_force_conclude_recovers_unsubmitted_run():
    """If the base loop ends without submitting, the CONCLUDE phase forces a
    final answer from the gathered evidence."""
    from claude_science.harness.scientist import _extract_json

    assert _extract_json('```json\n{"root": 2.4}\n```') == {"root": 2.4}
    assert _extract_json('the answer is {"root": 2.4} ok') == {"root": 2.4}
    assert _extract_json("no json here") is None

    class NoSubmitBackend:
        name = "nosub"
        max_steps = 3

        def complete(self, prompt, system=""):
            # planning call has HYPOTHESIS; conclude call asks for JSON
            if "HYPOTHESIS" in prompt:
                return "plan"
            return '{"root": %s}' % env.root  # conclude with the true root

        def run(self, env_):
            from claude_science.harness.transcript import Transcript
            tr = Transcript(env_.task_id, self.name)
            tr.log("tool_call", {"tool": "evaluate", "args": {"x": 0.0}})
            tr.log("observation", "f_x=1.0")
            return tr  # never submits

    env = make_env("rootfind", seed=0, difficulty="low")
    tr = ScientistAgent(NoSubmitBackend()).run(env)
    assert env.is_done()                       # conclude phase submitted
    assert env.result().score >= 0.75
    assert any(s.kind == "final" for s in tr.steps)
