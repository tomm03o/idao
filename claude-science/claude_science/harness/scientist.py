"""A structured research-scientist scaffold (Plan-and-Execute over any backend).

Flat ReAct loops react step by step; a scientist works in phases. This wrapper
imposes the scientific-method structure that autonomous-discovery systems use
(AutoDiscovery's hypothesis/experiment generators; the Plan-and-Execute pattern
that separates a Planner from an Executor):

    1. HYPOTHESISE + PLAN  — before touching an instrument, the agent states what
       it expects and the sequence of experiments it will run (single LLM call,
       no tools). This becomes an auditable pre-registration.
    2. EXECUTE             — the standard tool-use loop runs, with the plan
       injected into the task so actions follow the design.
    3. CONCLUDE            — the `submit` call ends the episode; the whole run is
       recorded as hypothesis → plan → actions → conclusion.

``ScientistAgent`` composes with *any* base agent exposing ``complete()`` (a
single-shot chat) and ``run(env)`` (the tool loop) — i.e. OpenRouterAgent or
AnthropicAgent — so it is model-agnostic. The structure is domain-agnostic too:
it works on the numerics environments exactly as on the biology ones.
"""

from __future__ import annotations

from typing import Any

from .agent import Agent
from .transcript import Step, Transcript

_SCIENTIST_SYSTEM = (
    "You are a meticulous research scientist. You reason from first principles, "
    "state falsifiable hypotheses, design efficient experiments within budget, "
    "and draw conclusions strictly from the data you collect."
)

_PLAN_PROMPT = (
    "You are about to work on the task below in a simulated laboratory with "
    "tool-based instruments. BEFORE using any tool, write a short research plan:\n"
    "  1. HYPOTHESIS — what you expect and why (one or two sentences).\n"
    "  2. EXPERIMENTS — the ordered sequence of tool calls you intend to make "
    "and what each will tell you.\n"
    "  3. DECISION RULE — how you will turn the results into your final answer.\n"
    "Keep it under 150 words. Do not call tools yet.\n\n"
    "Available tools: {tools}\n\nTASK:\n{task}"
)


class _PlannedEnv:
    """Proxy that augments an environment's task prompt with the agent's plan.

    Everything except ``task_prompt`` delegates to the wrapped environment, so
    tool dispatch, scoring and the submission all act on the real env.
    """

    def __init__(self, env: Any, plan: str):
        self._env = env
        self._plan = plan

    def task_prompt(self) -> str:
        return (f"{self._env.task_prompt()}\n\n--- YOUR PRE-REGISTERED PLAN ---\n"
                f"{self._plan}\n\nNow execute your plan step by step using the "
                "tools, adapting if the data contradicts your hypothesis. Call "
                "`submit` once when confident.")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._env, name)


class ScientistAgent(Agent):
    """Wrap a base agent with an explicit hypothesis→plan→execute→conclude cycle."""

    def __init__(self, base: Any):
        if not hasattr(base, "run"):
            raise TypeError("base agent must expose run()")
        self.base = base
        self.max_steps = getattr(base, "max_steps", 12)
        self.name = f"scientist:{base.name}"

    def run(self, env: Any) -> Transcript:
        tool_names = ", ".join(env.tools().names())
        if hasattr(self.base, "complete"):
            try:
                plan = self.base.complete(
                    _PLAN_PROMPT.format(tools=tool_names, task=env.task_prompt()),
                    system=_SCIENTIST_SYSTEM,
                )
            except Exception as exc:  # planning failure must not abort the run
                plan = f"(planning step unavailable: {type(exc).__name__})"
        else:
            plan = "(base agent has no LLM planner; running without a plan step)"

        tr = self.base.run(_PlannedEnv(env, plan))
        tr.agent = self.name
        tr.steps.insert(0, Step(kind="plan", content=plan))

        # Phase 4 (CONCLUDE): if the agent used up its budget without submitting,
        # force a conclusion from the evidence it gathered. This closes the
        # hypothesis→plan→execute→conclude loop instead of leaving the episode
        # unfinished — a common failure of flat tool loops that over-iterate.
        if not env.is_done() and hasattr(self.base, "complete"):
            self._force_conclude(env, tr)
        return tr

    def _force_conclude(self, env: Any, tr: Transcript) -> None:
        import json

        evidence = "\n".join(
            f"{s.kind}: {s.content if isinstance(s.content, str) else json.dumps(s.content)}"
            for s in tr.steps if s.kind in ("tool_call", "observation")
        )[-2000:]
        schema = json.dumps(env.submit_schema().get("properties", {}))
        prompt = (
            "You have run out of experiment budget without submitting. Based ONLY "
            "on the evidence below, output your best final answer now as a single "
            f"JSON object matching these fields: {schema}. Output JSON only.\n\n"
            f"EVIDENCE:\n{evidence}"
        )
        try:
            raw = self.base.complete(prompt, system=_SCIENTIST_SYSTEM)
            payload = _extract_json(raw, keys=list(env.submit_schema()
                                                   .get("properties", {})))
            if payload:
                res = env.tools().dispatch("submit", payload)
                tr.log("tool_call", {"tool": "submit", "args": payload})
                tr.log("observation", res.to_text())
                tr.log("final", payload)
        except Exception as exc:
            tr.log("conclude", f"(forced conclusion failed: {type(exc).__name__})")


def _extract_json(text: str, keys: list | None = None) -> dict | None:
    """Pull a submission dict out of a model reply.

    Reasoning-model replies are verbose and may contain several ``{...}`` spans
    (including the schema itself). When ``keys`` are given, return the last flat
    object that contains one of them; otherwise the last parseable flat object,
    then a whole-string parse. This is robust to prose wrapped around the answer.
    """
    import json
    import re

    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()

    candidates = re.findall(r"\{[^{}]*\}", text, re.S)
    parsed = []
    for c in candidates:
        try:
            obj = json.loads(c)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            parsed.append(obj)
    if keys:
        for obj in reversed(parsed):
            if any(k in obj for k in keys):
                return obj
    if parsed:
        return parsed[-1]
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None
