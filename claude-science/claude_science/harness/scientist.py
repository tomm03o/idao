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
        return tr
