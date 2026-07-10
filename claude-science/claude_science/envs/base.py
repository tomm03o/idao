"""Environment base class.

An environment is a self-contained scientific scenario. It owns:

* the *ground truth* (hidden parameters the agent must discover or optimise),
* a set of **tools** (instruments the agent may use, always including
  ``submit``),
* a **scorer** that turns a submission into a scalar in ``[0, 1]``,
* a **reference policy**: the sequence of tool calls an expert would make,
  used both as a baseline agent and as a self-test that the env is solvable.

Subclasses implement :meth:`_build`, :meth:`score`, and
:meth:`reference_policy`. Everything else (tool registry wiring, done-flag,
metadata) is handled here.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Dict, List

from ..harness.tools import ToolRegistry


@dataclass
class Submission:
    payload: Dict[str, Any]
    score: float | None = None


class Environment:
    #: short machine id, e.g. "pkpd", used on the CLI and in reports
    key: str = "base"
    #: human summary shown by `claude-science env list`
    title: str = "Base environment"
    #: which scientific capability the task probes
    capability: str = "general"

    def __init__(self, seed: int = 0, difficulty: str = "medium"):
        self.seed = seed
        self.difficulty = difficulty
        self.rng = random.Random(seed)
        self.task_id = f"{self.key}-{difficulty}-{seed}"
        self._submission: Submission | None = None
        self._registry = ToolRegistry()
        self.log: List[Dict[str, Any]] = []
        self._build()
        self._register_common_tools()

    # -- lifecycle ------------------------------------------------------- #
    def _build(self) -> None:
        """Sample the hidden ground truth and register domain tools."""
        raise NotImplementedError

    def _register_common_tools(self) -> None:
        self._registry.add(
            name="submit",
            description=(
                "Submit your final answer. Ends the episode. Provide the fields "
                "described in the task."
            ),
            parameters=self.submit_schema(),
            handler=self._submit,
        )

    def submit_schema(self) -> Dict[str, Any]:
        raise NotImplementedError

    def _submit(self, **payload: Any) -> str:
        self._submission = Submission(payload=payload)
        self._submission.score = self.score(payload)
        return (
            f"Submission recorded. Provisional score = "
            f"{self._submission.score:.3f}"
        )

    # -- agent-facing API ------------------------------------------------ #
    def tools(self) -> ToolRegistry:
        return self._registry

    def is_done(self) -> bool:
        return self._submission is not None

    def result(self) -> Submission | None:
        return self._submission

    def system_prompt(self) -> str:
        return (
            "You are a scientific research agent operating in a simulated "
            "biological/pharmaceutical laboratory. You have instruments exposed "
            "as tools. Design experiments deliberately, reason from the data you "
            "collect, and call `submit` exactly once when confident. Experiments "
            "may be noisy and your call budget is limited, so be economical."
        )

    def task_prompt(self) -> str:
        raise NotImplementedError

    # -- scoring --------------------------------------------------------- #
    def score(self, payload: Dict[str, Any]) -> float:
        """Map a submission payload to a scalar reward in [0, 1]."""
        raise NotImplementedError

    def reference_policy(self) -> List[Dict[str, Any]]:
        """An expert tool-call sequence (used by HeuristicAgent + self-test)."""
        raise NotImplementedError

    # -- helpers --------------------------------------------------------- #
    def _record(self, kind: str, data: Any) -> None:
        self.log.append({"kind": kind, "data": data})

    @staticmethod
    def clamp01(x: float) -> float:
        return max(0.0, min(1.0, x))
