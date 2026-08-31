"""Run agents/solvers over a verifiable-task dataset and export training data.

The output is the whole reason this module exists: reward-labelled trajectories
in the standard shapes an RL/fine-tuning stack consumes:

* **SFT**        -- ``{"messages": [...]}`` from high-reward rollouts only.
* **preference** -- ``{"prompt", "chosen", "rejected"}`` DPO pairs, formed from a
  higher-reward vs lower-reward rollout of the same task.
* **RLVR**       -- ``{"prompt", "verifier": {...}}`` so an online RL loop can
  regenerate the reward on the fly (no stored completions needed).

Solvers implement ``solve(task) -> (answer, trajectory)``. Two reference solvers
(``OracleSolver`` returns the gold, ``NullSolver`` returns a wrong answer) make
the pipeline runnable and testable with no API key; ``AgentSolver`` wraps a real
harness agent for genuine rollouts.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Protocol, Tuple

from .tasks import TaskDataset, VerifiableTask


@dataclass
class RolloutRecord:
    task_id: str
    domain: str
    prompt: str
    system: str
    answer: Any
    reward: float
    passed: bool
    solver: str
    trajectory: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__


class Solver(Protocol):
    name: str
    def solve(self, task: VerifiableTask) -> Tuple[Any, List[Dict[str, Any]]]: ...


# --------------------------------------------------------------------------- #
# Reference solvers (no API key)
# --------------------------------------------------------------------------- #
class OracleSolver:
    """Returns the correct answer; for agentic tasks, runs the expert policy."""

    name = "oracle"

    def solve(self, task: VerifiableTask):
        if task.judge == "env_score":
            return _run_expert(task)
        return task.gold, []


class NullSolver:
    """Returns a deliberately wrong answer -- the 'rejected' side of a pair."""

    name = "null"

    def solve(self, task: VerifiableTask):
        if task.judge == "numeric" or task.judge == "log_fold":
            return 0.0, []
        if task.judge == "set_overlap":
            return [], []
        if task.judge == "env_score":
            return {}, []
        return "", []


class AgentSolver:
    """Wrap a real harness agent (e.g. AnthropicAgent) for genuine rollouts.

    Agentic tasks are run in their reconstructed environment. Static QA tasks
    are answered single-shot via the agent's model (only AnthropicAgent).
    """

    def __init__(self, agent):
        self.agent = agent
        self.name = f"agent:{agent.name}"

    def solve(self, task: VerifiableTask):
        if task.judge == "env_score":
            from ..envs import make_env
            p = task.judge_params
            env = make_env(p["env_key"], p["seed"], p["difficulty"])
            tr = self.agent.run(env)
            sub = env.result()
            payload = sub.payload if sub else {}
            return payload, [s.__dict__ for s in tr.steps]
        return self._single_shot(task), []

    def _single_shot(self, task: VerifiableTask) -> str:
        system = task.system or "Answer with only the final value, no prose."
        # OpenRouterAgent (and any agent) exposing a `complete` method
        if hasattr(self.agent, "complete"):
            return self.agent.complete(task.prompt, system=system)
        # AnthropicAgent fallback
        client = self.agent._client()
        resp = client.messages.create(
            model=self.agent.model, max_tokens=512, system=system,
            messages=[{"role": "user", "content": task.prompt}],
        )
        return "".join(b.text for b in resp.content
                       if getattr(b, "type", "") == "text").strip()


def _run_expert(task: VerifiableTask):
    from ..envs import make_env
    from ..harness import HeuristicAgent
    p = task.judge_params
    env = make_env(p["env_key"], p["seed"], p["difficulty"])
    tr = HeuristicAgent().run(env)
    sub = env.result()
    return (sub.payload if sub else {}), [s.__dict__ for s in tr.steps]


# --------------------------------------------------------------------------- #
# Rollout + export
# --------------------------------------------------------------------------- #
def run_rollouts(dataset: TaskDataset, solver: Solver) -> List[RolloutRecord]:
    records: List[RolloutRecord] = []
    for task in dataset:
        answer, traj = solver.solve(task)
        v = task.grade(answer)
        records.append(RolloutRecord(
            task_id=task.task_id, domain=task.domain, prompt=task.prompt,
            system=task.system, answer=answer, reward=v.reward, passed=v.passed,
            solver=solver.name, trajectory=traj,
        ))
    return records


def to_sft_jsonl(records: List[RolloutRecord], path: str,
                 min_reward: float = 0.999) -> int:
    """Write SFT examples from high-reward rollouts. Returns count written."""
    n = 0
    with open(path, "w") as fh:
        for r in records:
            if r.reward < min_reward:
                continue
            messages = []
            if r.system:
                messages.append({"role": "system", "content": r.system})
            messages.append({"role": "user", "content": r.prompt})
            messages.append({"role": "assistant", "content": _answer_text(r.answer)})
            fh.write(json.dumps({"messages": messages, "reward": r.reward}) + "\n")
            n += 1
    return n


def to_preference_jsonl(records: List[RolloutRecord], path: str,
                        margin: float = 0.25) -> int:
    """Form DPO pairs: for each task, pair the best vs a worse rollout."""
    by_task: Dict[str, List[RolloutRecord]] = {}
    for r in records:
        by_task.setdefault(r.task_id, []).append(r)
    n = 0
    with open(path, "w") as fh:
        for recs in by_task.values():
            for a, b in itertools.combinations(recs, 2):
                hi, lo = (a, b) if a.reward >= b.reward else (b, a)
                if hi.reward - lo.reward < margin:
                    continue
                fh.write(json.dumps({
                    "prompt": hi.prompt,
                    "system": hi.system,
                    "chosen": _answer_text(hi.answer),
                    "rejected": _answer_text(lo.answer),
                    "reward_chosen": hi.reward, "reward_rejected": lo.reward,
                }) + "\n")
                n += 1
    return n


def to_rlvr_jsonl(dataset: TaskDataset, path: str) -> int:
    """Write prompts + verifier specs for online RL with verifiable rewards."""
    n = 0
    with open(path, "w") as fh:
        for t in dataset:
            fh.write(json.dumps({
                "task_id": t.task_id, "domain": t.domain,
                "prompt": t.prompt, "system": t.system,
                "verifier": {"judge": t.judge, "gold": t.gold,
                             "params": t.judge_params},
            }, default=str) + "\n")
            n += 1
    return n


def _answer_text(answer: Any) -> str:
    if isinstance(answer, (dict, list)):
        return json.dumps(answer, default=str)
    return str(answer)
