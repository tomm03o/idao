"""Tool abstraction for the Claude Science harness.

A ``Tool`` is a named, schema-described callable that an agent can invoke.
Environments expose their instruments (assays, simulators, analyses) as tools;
the agent decides which to call and with what arguments. The schema is a JSON
Schema fragment so it can be handed directly to the Claude Messages API
``tools`` parameter, or validated locally for baseline agents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List


@dataclass
class ToolResult:
    """Structured outcome of a tool call."""

    ok: bool
    content: Any
    error: str | None = None

    def to_text(self) -> str:
        if not self.ok:
            return f"ERROR: {self.error}"
        return self.content if isinstance(self.content, str) else _json(self.content)


@dataclass
class Tool:
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema object
    handler: Callable[..., Any]

    def anthropic_schema(self) -> Dict[str, Any]:
        """Return the tool definition in Claude Messages API format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }

    def call(self, **kwargs: Any) -> ToolResult:
        missing = [
            key
            for key in self.parameters.get("required", [])
            if key not in kwargs
        ]
        if missing:
            return ToolResult(False, None, f"missing required argument(s): {missing}")
        try:
            out = self.handler(**kwargs)
            return ToolResult(True, out)
        except Exception as exc:  # surfaced to the agent as an observation
            return ToolResult(False, None, f"{type(exc).__name__}: {exc}")


@dataclass
class ToolRegistry:
    tools: Dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def add(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: Callable[..., Any],
    ) -> None:
        self.register(Tool(name, description, parameters, handler))

    def get(self, name: str) -> Tool | None:
        return self.tools.get(name)

    def names(self) -> List[str]:
        return sorted(self.tools)

    def anthropic_schemas(self) -> List[Dict[str, Any]]:
        return [t.anthropic_schema() for t in self.tools.values()]

    def dispatch(self, name: str, arguments: Dict[str, Any]) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return ToolResult(False, None, f"unknown tool: {name!r}")
        return tool.call(**arguments)


def _json(obj: Any) -> str:
    import json

    return json.dumps(obj, indent=2, default=str, sort_keys=True)
