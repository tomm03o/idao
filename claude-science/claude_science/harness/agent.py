"""Agents: the policies that drive an environment through its tools.

Three backends ship in the box:

* :class:`AnthropicAgent` -- a real tool-use loop against the Claude Messages
  API. Default model ``claude-fable-5``. Requires ``anthropic`` + an API key.
* :class:`HeuristicAgent` -- calls the environment's own reference policy. No
  network, deterministic; the "expert baseline" a benchmark scores against.
* :class:`RandomAgent` -- samples random valid tool calls. The floor baseline.

All agents share one contract: ``run(env)`` returns a
:class:`~claude_science.harness.transcript.Transcript`.
"""

from __future__ import annotations

import os
import random
from typing import Any, Dict, List, Protocol

from .transcript import Transcript


class Environment(Protocol):
    """Structural type the agents rely on (see envs/base.py)."""

    task_id: str

    def system_prompt(self) -> str: ...
    def task_prompt(self) -> str: ...
    def tools(self) -> Any: ...            # ToolRegistry
    def is_done(self) -> bool: ...
    def reference_policy(self) -> List[Dict[str, Any]]: ...


class Agent:
    name = "agent"
    max_steps = 12

    def run(self, env: Environment) -> Transcript:  # pragma: no cover - abstract
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Baselines (no network required)
# --------------------------------------------------------------------------- #
class RandomAgent(Agent):
    name = "random"

    def __init__(self, seed: int = 0):
        self.rng = random.Random(seed)

    def run(self, env: Environment) -> Transcript:
        tr = Transcript(env.task_id, self.name)
        reg = env.tools()
        for _ in range(self.max_steps):
            if env.is_done():
                break
            name = self.rng.choice(reg.names())
            args = _random_args(reg.get(name).parameters, self.rng)
            tr.log("tool_call", {"tool": name, "args": args})
            res = reg.dispatch(name, args)
            tr.log("observation", res.to_text())
        tr.log("final", {"note": "random agent submitted no explicit answer"})
        return tr


class HeuristicAgent(Agent):
    """Replays the environment's expert reference policy."""

    name = "heuristic"

    def run(self, env: Environment) -> Transcript:
        tr = Transcript(env.task_id, self.name)
        reg = env.tools()
        for call in env.reference_policy():
            if env.is_done():
                break
            name, args = call["tool"], call.get("args", {})
            tr.log("tool_call", {"tool": name, "args": args})
            res = reg.dispatch(name, args)
            tr.log("observation", res.to_text())
            if name == "submit":
                tr.log("final", args)
        if tr.final() is None:
            tr.log("final", {"note": "heuristic policy finished without submit"})
        return tr


# --------------------------------------------------------------------------- #
# Real Claude-driven agent
# --------------------------------------------------------------------------- #
class AnthropicAgent(Agent):
    name = "claude"

    def __init__(
        self,
        model: str = "claude-fable-5",
        max_steps: int = 12,
        max_tokens: int = 2048,
        api_key: str | None = None,
    ):
        self.model = model
        self.max_steps = max_steps
        self.max_tokens = max_tokens
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")

    def _client(self):
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "AnthropicAgent needs the 'anthropic' package: pip install anthropic"
            ) from exc
        if not self._api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        return anthropic.Anthropic(api_key=self._api_key)

    def run(self, env: Environment) -> Transcript:
        client = self._client()
        tr = Transcript(env.task_id, f"{self.name}:{self.model}")
        reg = env.tools()
        tools = reg.anthropic_schemas()
        messages: List[Dict[str, Any]] = [
            {"role": "user", "content": env.task_prompt()}
        ]

        for _ in range(self.max_steps):
            resp = client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=env.system_prompt(),
                tools=tools,
                messages=messages,
            )
            messages.append({"role": "assistant", "content": resp.content})

            tool_uses = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
            for block in resp.content:
                if getattr(block, "type", "") == "text":
                    tr.log("message", block.text)

            if resp.stop_reason != "tool_use" or not tool_uses:
                tr.log("final", _last_text(resp.content))
                break

            results = []
            for tu in tool_uses:
                tr.log("tool_call", {"tool": tu.name, "args": tu.input})
                res = reg.dispatch(tu.name, tu.input or {})
                tr.log("observation", res.to_text())
                if tu.name == "submit":
                    tr.log("final", tu.input)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": res.to_text(),
                        "is_error": not res.ok,
                    }
                )
            messages.append({"role": "user", "content": results})

            if env.is_done():
                break

        if tr.final() is None:
            tr.log("final", {"note": "agent stopped without a final answer"})
        return tr


# --------------------------------------------------------------------------- #
def _random_args(schema: Dict[str, Any], rng: random.Random) -> Dict[str, Any]:
    props = schema.get("properties", {})
    out: Dict[str, Any] = {}
    for key in schema.get("required", list(props)):
        spec = props.get(key, {})
        t = spec.get("type", "number")
        if t == "number":
            lo, hi = spec.get("minimum", 0.0), spec.get("maximum", 10.0)
            out[key] = round(rng.uniform(lo, hi), 3)
        elif t == "integer":
            lo, hi = int(spec.get("minimum", 0)), int(spec.get("maximum", 5))
            out[key] = rng.randint(lo, hi)
        elif t == "string" and "enum" in spec:
            out[key] = rng.choice(spec["enum"])
        elif t == "array":
            out[key] = []
        else:
            out[key] = spec.get("default", "")
    return out


def _last_text(content: List[Any]) -> str:
    for block in reversed(content):
        if getattr(block, "type", "") == "text":
            return block.text
    return ""
