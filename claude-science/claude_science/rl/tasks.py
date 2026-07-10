"""Verifiable task and dataset containers.

A :class:`VerifiableTask` bundles a prompt with everything needed to *grade* an
answer automatically: which judge to use, the gold reference, and judge
parameters. Datasets serialise to JSONL -- the lingua franca of LLM training.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Iterable, Iterator, List

from .judges import Verdict, get_judge


@dataclass
class VerifiableTask:
    task_id: str
    domain: str
    prompt: str
    judge: str                       # name of a registered judge
    gold: Any = None
    judge_params: Dict[str, Any] = field(default_factory=dict)
    system: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    def grade(self, prediction: Any) -> Verdict:
        return get_judge(self.judge)(
            prediction, self.gold, **self.judge_params
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "VerifiableTask":
        return cls(**d)


@dataclass
class TaskDataset:
    tasks: List[VerifiableTask] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.tasks)

    def __iter__(self) -> Iterator[VerifiableTask]:
        return iter(self.tasks)

    def add(self, task: VerifiableTask) -> None:
        self.tasks.append(task)

    def extend(self, tasks: Iterable[VerifiableTask]) -> None:
        self.tasks.extend(tasks)

    def by_domain(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for t in self.tasks:
            counts[t.domain] = counts.get(t.domain, 0) + 1
        return dict(sorted(counts.items()))

    def save_jsonl(self, path: str) -> None:
        with open(path, "w") as fh:
            for t in self.tasks:
                fh.write(json.dumps(t.to_dict(), default=str) + "\n")

    @classmethod
    def load_jsonl(cls, path: str) -> "TaskDataset":
        tasks = []
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    tasks.append(VerifiableTask.from_dict(json.loads(line)))
        return cls(tasks)
