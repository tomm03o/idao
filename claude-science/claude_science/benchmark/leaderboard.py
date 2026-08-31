"""Multi-agent leaderboard: run several agents/models on the same suite and rank.

This is the Claude-Science-style deliverable -- a comparative capability report
across models. Each agent is specified as a string:

    heuristic | random | claude:<model> | openrouter:<model>

e.g. ``openrouter:tencent/hy3:free``. Baselines (heuristic/random) bracket the
scale so every model's number is interpretable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from .runner import BenchmarkReport, BenchmarkRunner


def make_agent(spec: str, max_steps: int = 12):
    """Build an agent from a spec string.

    Examples: ``heuristic``, ``random``, ``openrouter:tencent/hy3:free``,
    ``claude:claude-fable-5``, or wrap any LLM backend in the scientific-method
    scaffold with a ``scientist:`` prefix, e.g.
    ``scientist:openrouter:tencent/hy3:free``.
    """
    from ..harness import (AnthropicAgent, HeuristicAgent, OpenRouterAgent,
                           RandomAgent, ScientistAgent, VerifiedBestOfN)
    kind, _, rest = spec.partition(":")
    if kind == "scientist":
        return ScientistAgent(make_agent(rest, max_steps=max_steps))
    if kind == "verified":
        n_str, _, inner = rest.partition(":")
        return VerifiedBestOfN(make_agent(inner, max_steps=max_steps),
                               n=int(n_str) if n_str.isdigit() else 5)
    model = rest
    if kind == "heuristic":
        return HeuristicAgent()
    if kind == "random":
        return RandomAgent()
    if kind == "claude":
        return AnthropicAgent(model=model or "claude-fable-5", max_steps=max_steps)
    if kind == "openrouter":
        return OpenRouterAgent(model=model or "tencent/hy3:free", max_steps=max_steps)
    raise ValueError(f"unknown agent spec {spec!r}")


@dataclass
class Leaderboard:
    reports: Dict[str, BenchmarkReport] = field(default_factory=dict)
    errors: Dict[str, str] = field(default_factory=dict)

    def add(self, spec: str, report: BenchmarkReport) -> None:
        self.reports[spec] = report

    def ranked(self) -> List[tuple]:
        return sorted(self.reports.items(),
                     key=lambda kv: kv[1].overall(), reverse=True)

    def capabilities(self) -> List[str]:
        caps = set()
        for r in self.reports.values():
            caps.update(r.by_capability())
        return sorted(caps)

    def to_dict(self) -> Dict:
        return {
            "reports": {spec: r.to_dict(include_transcripts=False)
                        for spec, r in self.reports.items()},
            "errors": dict(self.errors),
        }

    def transcripts(self) -> Dict[str, List[Dict]]:
        """One episode transcript per (agent, task) for inspection in the UI.

        This is what lets an admin see *how* a model reasoned -- which tools it
        called and why it failed -- not just its score.
        """
        out: Dict[str, List[Dict]] = {}
        for spec, rep in self.reports.items():
            out[spec] = [
                {"env": r.env, "task_id": r.task_id, "score": r.score,
                 "submitted": r.submitted, "n_tool_calls": r.n_tool_calls,
                 "steps": (r.transcript or {}).get("steps", [])}
                for r in rep.results
            ]
        return out


def run_leaderboard(specs: List[str], runner: BenchmarkRunner,
                    max_steps: int = 12, progress: bool = True) -> Leaderboard:
    lb = Leaderboard()
    for spec in specs:
        if progress:
            print(f"\n▶ evaluating {spec} …")
        try:
            agent = make_agent(spec, max_steps=max_steps)
            report = runner.run(agent, progress=progress)
            lb.add(spec, report)
            if progress:
                print(f"  {spec}: overall {report.overall():.3f}")
        except Exception as exc:
            # a rate-limited or unreachable model must not sink the whole board
            lb.errors[spec] = f"{type(exc).__name__}: {str(exc)[:160]}"
            if progress:
                print(f"  {spec}: SKIPPED ({lb.errors[spec]})")
    return lb


def render_leaderboard(lb: Leaderboard) -> str:
    caps = lb.capabilities()
    ranked = lb.ranked()
    short = {c: c[:4] for c in caps}

    lines = ["", "═" * (28 + 7 + 8 * len(caps)),
             "  CLAUDE SCIENCE LEADERBOARD", "═" * (28 + 7 + 8 * len(caps))]
    header = f"  {'agent / model':<30}{'overall':>8}  " + "".join(
        f"{short[c]:>7}" for c in caps)
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))
    for rank, (spec, rep) in enumerate(ranked, 1):
        by = rep.by_capability()
        row = f"  {rank}. {spec:<27}{rep.overall():>8.3f}  " + "".join(
            f"{by.get(c, 0):>7.2f}" for c in caps)
        lines.append(row)
    lines.append("")
    lines.append("  capability key: " + "  ".join(f"{short[c]}={c}" for c in caps))
    if lb.errors:
        lines.append("")
        lines.append("  skipped (unreachable / rate-limited):")
        for spec, err in lb.errors.items():
            lines.append(f"    {spec}: {err}")
    return "\n".join(lines)
