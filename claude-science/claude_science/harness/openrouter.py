"""OpenRouter agent backend (OpenAI-compatible), dependency-free.

Lets the harness evaluate *any* OpenRouter-hosted model -- open-weights or
proprietary -- through the same ``run(env) -> Transcript`` contract as the Claude
agent. It drives the standard chat-completions tool-use loop over urllib, so it
needs no SDK; only an ``OPENROUTER_API_KEY``.

    from claude_science.harness.openrouter import OpenRouterAgent
    agent = OpenRouterAgent(model="tencent/hy3:free")

The registry's Anthropic-style tool schemas are converted to OpenAI function
tools on the fly, so environments need no changes.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List

from .agent import Agent
from .transcript import Transcript

_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterAgent(Agent):
    name = "openrouter"

    def __init__(self, model: str = "tencent/hy3:free", max_steps: int = 12,
                 max_tokens: int = 1024, api_key: str | None = None,
                 temperature: float = 0.0, timeout: int = 90):
        self.model = model
        self.max_steps = max_steps
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout
        self._api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        self.name = f"openrouter:{model}"

    # -- low-level call -------------------------------------------------- #
    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self._api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        body = json.dumps(payload).encode()
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "X-Title": "claude-science",
        }
        last: Exception | None = None
        for attempt in range(4):
            try:
                req = urllib.request.Request(_ENDPOINT, data=body, headers=headers)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:200]
                if exc.code in (429, 502, 503) and attempt < 3:
                    time.sleep(2 ** attempt)
                    continue
                raise RuntimeError(f"OpenRouter HTTP {exc.code}: {detail}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last = exc
                time.sleep(2 ** attempt)
        raise ConnectionError(f"OpenRouter unreachable: {last}")

    @staticmethod
    def _to_openai_tools(reg) -> List[Dict[str, Any]]:
        out = []
        for t in reg.tools.values():
            out.append({"type": "function", "function": {
                "name": t.name, "description": t.description,
                "parameters": t.parameters}})
        return out

    # -- single-shot (for static QA in the RL pipeline) ------------------ #
    def complete(self, prompt: str, system: str = "") -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = self._post({"model": self.model, "messages": messages,
                           "max_tokens": self.max_tokens,
                           "temperature": self.temperature})
        return (resp["choices"][0]["message"].get("content") or "").strip()

    # -- agentic loop ---------------------------------------------------- #
    def run(self, env) -> Transcript:
        reg = env.tools()
        tools = self._to_openai_tools(reg)
        tr = Transcript(env.task_id, self.name)
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": env.system_prompt()},
            {"role": "user", "content": env.task_prompt()},
        ]

        for _ in range(self.max_steps):
            resp = self._post({
                "model": self.model, "messages": messages, "tools": tools,
                "max_tokens": self.max_tokens, "temperature": self.temperature,
            })
            msg = resp["choices"][0]["message"]
            messages.append(_clean_assistant(msg))

            if msg.get("content"):
                tr.log("message", msg["content"])

            calls = msg.get("tool_calls") or []
            if not calls:
                tr.log("final", msg.get("content", ""))
                break

            for call in calls:
                fn = call.get("function", {})
                name = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                tr.log("tool_call", {"tool": name, "args": args})
                res = reg.dispatch(name, args)
                tr.log("observation", res.to_text())
                if name == "submit":
                    tr.log("final", args)
                messages.append({
                    "role": "tool", "tool_call_id": call.get("id", name),
                    "name": name, "content": res.to_text(),
                })

            if env.is_done():
                break

        if tr.final() is None:
            tr.log("final", {"note": "agent stopped without a final answer"})
        return tr


def _clean_assistant(msg: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only the fields the API accepts when echoing an assistant turn."""
    out: Dict[str, Any] = {"role": "assistant",
                           "content": msg.get("content") or ""}
    if msg.get("tool_calls"):
        out["tool_calls"] = [
            {"id": c.get("id"), "type": "function",
             "function": {"name": c["function"]["name"],
                          "arguments": c["function"].get("arguments", "{}")}}
            for c in msg["tool_calls"]
        ]
    return out
