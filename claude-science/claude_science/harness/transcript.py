"""Episode transcript: an auditable record of an agent's run.

Every step an agent takes -- a thought, a tool call, an observation, a final
answer -- is appended here. The transcript is what makes a run reproducible and
reviewable, which matters in a regulated (pharma) setting.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List


@dataclass
class Step:
    kind: str  # "message" | "tool_call" | "observation" | "final"
    content: Any
    t: float = field(default_factory=time.time)
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Transcript:
    task_id: str
    agent: str
    steps: List[Step] = field(default_factory=list)
    started: float = field(default_factory=time.time)

    def log(self, kind: str, content: Any, **meta: Any) -> None:
        self.steps.append(Step(kind=kind, content=content, meta=meta))

    def tool_calls(self) -> List[Step]:
        return [s for s in self.steps if s.kind == "tool_call"]

    def n_tool_calls(self) -> int:
        return len(self.tool_calls())

    def final(self) -> Any:
        for s in reversed(self.steps):
            if s.kind == "final":
                return s.content
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "agent": self.agent,
            "started": self.started,
            "steps": [asdict(s) for s in self.steps],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)

    def pretty(self) -> str:
        lines = [f"── transcript [{self.task_id}] agent={self.agent} ──"]
        for i, s in enumerate(self.steps):
            body = s.content if isinstance(s.content, str) else json.dumps(
                s.content, default=str
            )
            if len(body) > 500:
                body = body[:500] + " …"
            lines.append(f"  {i:02d} {s.kind:<11} {body}")
        return "\n".join(lines)
