"""Benchmark runner: score an agent across environments, seeds and difficulties.

The unit of evaluation is a *task* = (environment, seed, difficulty). For each
task a fresh environment is built, the agent runs against it, and the
environment's own scorer produces a reward in [0, 1]. Results aggregate into a
per-capability and overall scorecard, and a full JSON report with transcripts.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List

from ..envs import make_env
from ..harness.agent import Agent
from ..harness.transcript import Transcript


@dataclass
class TaskResult:
    task_id: str
    env: str
    capability: str
    difficulty: str
    seed: int
    score: float
    n_tool_calls: int
    wall_s: float
    submitted: bool
    transcript: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BenchmarkReport:
    agent: str
    results: List[TaskResult]
    created: float = field(default_factory=time.time)

    def overall(self) -> float:
        return round(statistics.mean(r.score for r in self.results), 4) if self.results else 0.0

    def by_capability(self) -> Dict[str, float]:
        buckets: Dict[str, List[float]] = {}
        for r in self.results:
            buckets.setdefault(r.capability, []).append(r.score)
        return {k: round(statistics.mean(v), 4) for k, v in sorted(buckets.items())}

    def by_env(self) -> Dict[str, float]:
        buckets: Dict[str, List[float]] = {}
        for r in self.results:
            buckets.setdefault(r.env, []).append(r.score)
        return {k: round(statistics.mean(v), 4) for k, v in sorted(buckets.items())}

    def to_dict(self, include_transcripts: bool = True) -> Dict[str, Any]:
        results = []
        for r in self.results:
            d = asdict(r)
            if not include_transcripts:
                d.pop("transcript", None)
            results.append(d)
        return {
            "agent": self.agent,
            "created": self.created,
            "overall": self.overall(),
            "by_capability": self.by_capability(),
            "by_env": self.by_env(),
            "n_tasks": len(self.results),
            "results": results,
        }


class BenchmarkRunner:
    def __init__(
        self,
        envs: List[str] | None = None,
        seeds: List[int] | None = None,
        difficulties: List[str] | None = None,
    ):
        from ..envs import ENVIRONMENTS

        self.envs = envs or list(ENVIRONMENTS)
        self.seeds = seeds or [0, 1, 2]
        self.difficulties = difficulties or ["medium"]

    def tasks(self):
        for env in self.envs:
            for diff in self.difficulties:
                for seed in self.seeds:
                    yield env, diff, seed

    def run(self, agent: Agent, progress: bool = False) -> BenchmarkReport:
        results: List[TaskResult] = []
        for env_key, diff, seed in self.tasks():
            env = make_env(env_key, seed=seed, difficulty=diff)
            t0 = time.time()
            tr: Transcript = agent.run(env)
            wall = time.time() - t0
            sub = env.result()
            score = sub.score if sub and sub.score is not None else 0.0
            tres = TaskResult(
                task_id=env.task_id,
                env=env_key,
                capability=env.capability,
                difficulty=diff,
                seed=seed,
                score=round(score, 4),
                n_tool_calls=tr.n_tool_calls(),
                wall_s=round(wall, 3),
                submitted=sub is not None,
                transcript=tr.to_dict(),
            )
            results.append(tres)
            if progress:
                print(
                    f"  {env.task_id:<24} score={tres.score:.3f} "
                    f"calls={tres.n_tool_calls}"
                )
        return BenchmarkReport(agent=agent.name, results=results)
