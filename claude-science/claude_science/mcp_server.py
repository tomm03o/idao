"""Model Context Protocol (MCP) server for Claude Science — dependency-free.

Exposes the whole platform to any MCP client (Claude Code, Claude Desktop, the
Agent SDK) over the standard stdio transport: newline-delimited JSON-RPC 2.0.
An agent connected to this server can:

* use the validated science, database, web, RAG and workspace tools directly, and
* **play the benchmark**: ``bench_start`` opens an episode (returns the task and
  the episode's instrument schemas), ``bench_act`` calls an instrument, and the
  server reports the score the moment ``submit`` is called.

Register it with a client via ``.mcp.json`` (see repo) or run standalone:

    python -m claude_science.mcp_server        # speaks JSON-RPC on stdin/stdout

No third-party packages required — the MCP wire format is implemented here.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Callable, Dict, List

from .toolkits import lab_bench
from .data_sources.web import web_tools
from .retrieval import Corpus, retrieval_tools
from .workspace import Workspace
from .envs import ENVIRONMENTS, make_env

PROTOCOL_VERSION = "2024-11-05"


class MCPServer:
    def __init__(self) -> None:
        self._ws = Workspace()
        self._registry = lab_bench(workspace=self._ws, with_databases=True)
        for extra in (web_tools(), retrieval_tools(Corpus())):
            for t in extra.tools.values():
                self._registry.register(t)
        self._episode = None            # (env, tool schemas)
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._build_tool_list()

    # -- tool catalogue -------------------------------------------------- #
    def _build_tool_list(self) -> None:
        for t in self._registry.tools.values():
            self._tools[t.name] = {
                "name": t.name, "description": t.description,
                "inputSchema": t.parameters,
                "_handler": lambda name=t.name, **kw: self._registry.dispatch(name, kw).to_text(),
            }
        # benchmark control tools
        self._register("bench_list_environments",
                       "List the benchmark environments (labs) available to play.",
                       {"type": "object", "properties": {}},
                       lambda: json.dumps([
                           {"key": c.key, "title": c.title, "capability": c.capability}
                           for c in ENVIRONMENTS.values()]))
        self._register("bench_start",
                       "Open a benchmark episode. Returns the task prompt and the "
                       "episode's instrument tools (call them via bench_act).",
                       {"type": "object", "properties": {
                           "env_key": {"type": "string",
                                       "enum": list(ENVIRONMENTS)},
                           "seed": {"type": "integer"},
                           "difficulty": {"type": "string",
                                          "enum": ["low", "medium", "high"]}},
                        "required": ["env_key"]},
                       self._bench_start)
        self._register("bench_act",
                       "Call one instrument in the current episode, e.g. "
                       "{\"tool\": \"analyze_molecule\", \"arguments\": {...}}. "
                       "Calling 'submit' ends the episode and returns the score.",
                       {"type": "object", "properties": {
                           "tool": {"type": "string"},
                           "arguments": {"type": "object"}},
                        "required": ["tool"]},
                       self._bench_act)
        self._register("bench_score",
                       "Report the current episode's submission score (0-1).",
                       {"type": "object", "properties": {}},
                       self._bench_score)

    def _register(self, name: str, desc: str, schema: Dict[str, Any],
                  handler: Callable[..., str]) -> None:
        self._tools[name] = {"name": name, "description": desc,
                             "inputSchema": schema, "_handler": handler}

    # -- benchmark control ---------------------------------------------- #
    def _bench_start(self, env_key: str, seed: int = 0,
                     difficulty: str = "medium") -> str:
        env = make_env(env_key, seed=seed, difficulty=difficulty)
        self._episode = env
        instruments = [{"name": t.name, "description": t.description,
                        "input_schema": t.parameters}
                       for t in env.tools().tools.values()]
        return json.dumps({
            "task_id": env.task_id,
            "system": env.system_prompt(),
            "task": env.task_prompt(),
            "instruments": instruments,
            "hint": "call these via bench_act(tool=..., arguments=...)",
        }, indent=2)

    def _bench_act(self, tool: str, arguments: Dict[str, Any] | None = None) -> str:
        if self._episode is None:
            return "ERROR: no active episode; call bench_start first"
        res = self._episode.tools().dispatch(tool, arguments or {})
        out = {"observation": res.content if res.ok else res.error, "ok": res.ok}
        if self._episode.is_done():
            sub = self._episode.result()
            out["episode_done"] = True
            out["score"] = sub.score
        return json.dumps(out, default=str, indent=2)

    def _bench_score(self) -> str:
        if self._episode is None:
            return "no active episode"
        sub = self._episode.result()
        return json.dumps({"submitted": sub is not None,
                           "score": sub.score if sub else None})

    # -- JSON-RPC dispatch ---------------------------------------------- #
    def handle(self, msg: Dict[str, Any]) -> Dict[str, Any] | None:
        method, mid = msg.get("method"), msg.get("id")
        if method == "initialize":
            return _ok(mid, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "claude-science", "version": "0.4.0"}})
        if method in ("notifications/initialized", "initialized"):
            return None
        if method == "ping":
            return _ok(mid, {})
        if method == "tools/list":
            return _ok(mid, {"tools": [
                {k: v for k, v in t.items() if not k.startswith("_")}
                for t in self._tools.values()]})
        if method == "tools/call":
            params = msg.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {}) or {}
            tool = self._tools.get(name)
            if not tool:
                return _err(mid, -32601, f"unknown tool {name!r}")
            try:
                text = tool["_handler"](**args)
            except Exception as exc:  # surface as tool error, not RPC error
                return _ok(mid, {"content": [{"type": "text",
                          "text": f"ERROR: {type(exc).__name__}: {exc}"}],
                          "isError": True})
            return _ok(mid, {"content": [{"type": "text", "text": str(text)}]})
        return _err(mid, -32601, f"method not found: {method}")

    def serve_stdio(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            resp = self.handle(msg)
            if resp is not None:
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()

    def cleanup(self) -> None:
        self._ws.cleanup()


def _ok(mid: Any, result: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _err(mid: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def main() -> int:
    server = MCPServer()
    try:
        server.serve_stdio()
    finally:
        server.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
