"""Interactive scientific console — a Claude-Code-style REPL for lab work.

A human sits at a terminal and delegates biological / chemical / bioinformatic
tasks to an agent that has the whole platform as tools: validated science,
live database access, a sandboxed workspace/terminal, internet (literature +
web fetch) and a RAG corpus. The agent plans, calls tools, shows its work, and
reports back — then the human replies, so it is a genuine collaboration loop,
not a one-shot.

    python -m claude_science.console --model tencent/hy3:free
    python -m claude_science.console --agent claude --model claude-fable-5

Slash commands: /tools /history /pipeline <file> /save <file> /reset /help /exit

The agent backend is pluggable (OpenRouter or Claude); tool execution and
command handling are provider-independent and unit-tested.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Callable, Dict, List

from .harness.tools import ToolRegistry
from .toolkits import lab_bench
from .retrieval import Corpus, retrieval_tools
from .data_sources.web import web_tools
from .workspace import Workspace

SYSTEM = (
    "You are a scientific research agent working alongside a human in a "
    "simulated computational laboratory. You have tools for cheminformatics, "
    "pharmacokinetics, sequence bioinformatics, molecular modelling, live "
    "biological/chemical databases (PubChem, ChEMBL, UniProt, PDB), the "
    "biomedical literature, generic web pages, a document-retrieval (RAG) "
    "corpus, and a sandboxed workspace with a Python/shell terminal. Plan "
    "explicitly, call tools to gather real data rather than guessing, cite the "
    "database or paper you used, and hand back concise, verifiable results."
)


def build_session_tools(with_databases: bool = True) -> ToolRegistry:
    """Assemble the full console toolset into one registry."""
    ws = Workspace()
    reg = lab_bench(workspace=ws, with_databases=with_databases)
    for extra in (web_tools(), retrieval_tools(Corpus())):
        for tool in extra.tools.values():
            reg.register(tool)
    reg._workspace = ws
    return reg


class ScienceConsole:
    def __init__(self, agent, tools: ToolRegistry | None = None,
                 system: str = SYSTEM, max_tool_iters: int = 8,
                 printer: Callable[[str], None] = print):
        self.agent = agent
        self.tools = tools or build_session_tools()
        self.system = system
        self.max_tool_iters = max_tool_iters
        self.print = printer
        self.messages: List[Dict[str, Any]] = []

    # -- command handling (provider-independent, tested) ----------------- #
    def handle_command(self, line: str) -> bool:
        """Return True if the line was a slash-command (handled here)."""
        if not line.startswith("/"):
            return False
        cmd, _, arg = line[1:].partition(" ")
        arg = arg.strip()
        if cmd in ("exit", "quit"):
            raise SystemExit(0)
        elif cmd == "help":
            self.print(__doc__.split("Slash commands:")[1].split("\n")[0]
                       if "Slash commands:" in __doc__ else "commands: /tools /reset")
        elif cmd == "tools":
            self.print("\n".join(f"  {n:26} {self.tools.get(n).description[:60]}"
                                 for n in self.tools.names()))
        elif cmd == "history":
            self.print(json.dumps(self.messages, indent=2, default=str)[:4000])
        elif cmd == "reset":
            self.messages = []
            self.print("(conversation reset)")
        elif cmd == "save":
            path = arg or "session.json"
            with open(path, "w") as fh:
                json.dump(self.messages, fh, indent=2, default=str)
            self.print(f"(saved to {path})")
        elif cmd == "pipeline":
            self.run_pipeline(arg)
        else:
            self.print(f"(unknown command /{cmd}; try /help)")
        return True

    def run_pipeline(self, path: str) -> None:
        """Run a newline-separated list of prompts as a scripted pipeline."""
        if not path or not os.path.exists(path):
            self.print(f"(pipeline file not found: {path})")
            return
        steps = [ln.strip() for ln in open(path) if ln.strip()
                 and not ln.startswith("#")]
        for i, step in enumerate(steps, 1):
            self.print(f"\n── pipeline step {i}/{len(steps)}: {step}")
            self.turn(step)

    # -- one collaborative turn (drives the agent's tool loop) ----------- #
    def turn(self, user_text: str) -> str:
        self.messages.append({"role": "user", "content": user_text})
        final = self.agent.chat(self.messages, self.tools, self.system,
                                on_event=self._on_event,
                                max_iters=self.max_tool_iters)
        return final

    def _on_event(self, kind: str, payload: Any) -> None:
        if kind == "text" and payload:
            self.print(f"\n🧠 {payload}")
        elif kind == "tool_call":
            self.print(f"  ⚙  {payload['tool']}({_short(payload['args'])})")
        elif kind == "observation":
            self.print(f"     → {_short(payload)}")

    # -- REPL ------------------------------------------------------------ #
    def repl(self) -> None:
        self.print("Claude Science console — type a task, or /help. Ctrl-D to exit.\n")
        while True:
            try:
                line = input("you › ").strip()
            except (EOFError, KeyboardInterrupt):
                self.print("\nbye")
                break
            if not line:
                continue
            try:
                if self.handle_command(line):
                    continue
                self.turn(line)
            except SystemExit:
                self.print("bye")
                break
            except Exception as exc:  # keep the session alive on tool/model errors
                self.print(f"[error] {type(exc).__name__}: {exc}")


def _short(obj: Any, n: int = 160) -> str:
    s = obj if isinstance(obj, str) else json.dumps(obj, default=str)
    return s if len(s) <= n else s[:n] + " …"


def _make_agent(kind: str, model: str):
    from .harness import AnthropicAgent, OpenRouterAgent
    if kind == "claude":
        return _ClaudeChat(AnthropicAgent(model=model))
    return _ORChat(OpenRouterAgent(model=model))


class _ORChat:
    """Adapts OpenRouterAgent into a persistent multi-turn chat with tools."""

    def __init__(self, agent):
        self.agent = agent
        self.name = agent.name

    def chat(self, messages, tools, system, on_event, max_iters=8) -> str:
        oa_tools = self.agent._to_openai_tools(tools)
        convo = [{"role": "system", "content": system}] + messages
        final = ""
        for _ in range(max_iters):
            resp = self.agent._post({"model": self.agent.model, "messages": convo,
                                     "tools": oa_tools, "max_tokens": 1200,
                                     "temperature": 0.0})
            msg = resp["choices"][0]["message"]
            from .harness.openrouter import _clean_assistant
            convo.append(_clean_assistant(msg))
            if msg.get("content"):
                on_event("text", msg["content"])
                final = msg["content"]
            calls = msg.get("tool_calls") or []
            if not calls:
                break
            for call in calls:
                fn = call.get("function", {})
                name = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                on_event("tool_call", {"tool": name, "args": args})
                res = tools.dispatch(name, args)
                on_event("observation", res.to_text())
                convo.append({"role": "tool", "tool_call_id": call.get("id", name),
                              "name": name, "content": res.to_text()})
        messages[:] = convo[1:]  # persist (minus system)
        return final


class _ClaudeChat:
    """Adapts AnthropicAgent into a persistent multi-turn chat with tools."""

    def __init__(self, agent):
        self.agent = agent
        self.name = agent.name

    def chat(self, messages, tools, system, on_event, max_iters=8) -> str:
        client = self.agent._client()
        schemas = tools.anthropic_schemas()
        # rebuild native message list from the plain history
        convo = [{"role": m["role"], "content": m["content"]} for m in messages
                 if m["role"] in ("user", "assistant")]
        final = ""
        for _ in range(max_iters):
            resp = client.messages.create(model=self.agent.model, max_tokens=1500,
                                          system=system, tools=schemas, messages=convo)
            convo.append({"role": "assistant", "content": resp.content})
            for b in resp.content:
                if getattr(b, "type", "") == "text":
                    on_event("text", b.text)
                    final = b.text
            tus = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
            if resp.stop_reason != "tool_use" or not tus:
                break
            results = []
            for tu in tus:
                on_event("tool_call", {"tool": tu.name, "args": tu.input})
                res = tools.dispatch(tu.name, tu.input or {})
                on_event("observation", res.to_text())
                results.append({"type": "tool_result", "tool_use_id": tu.id,
                                "content": res.to_text(), "is_error": not res.ok})
            convo.append({"role": "user", "content": results})
        messages.append({"role": "assistant", "content": final})
        return final


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="claude-science-console", description=__doc__)
    p.add_argument("--agent", default="openrouter", choices=["openrouter", "claude"])
    p.add_argument("--model", default="tencent/hy3:free")
    p.add_argument("--no-databases", action="store_true")
    p.add_argument("--pipeline", default="", help="run a pipeline file then exit")
    args = p.parse_args(argv)

    backend = _make_agent(args.agent, args.model)
    console = ScienceConsole(backend,
                             tools=build_session_tools(not args.no_databases))
    try:
        if args.pipeline:
            console.run_pipeline(args.pipeline)
        else:
            console.repl()
    finally:
        ws = getattr(console.tools, "_workspace", None)
        if ws:
            ws.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
