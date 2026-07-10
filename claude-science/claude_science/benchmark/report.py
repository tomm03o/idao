"""Human-readable rendering of a benchmark report."""

from __future__ import annotations

from .runner import BenchmarkReport


def render_scorecard(report: BenchmarkReport) -> str:
    lines: list[str] = []
    lines.append("╔══════════════════════════════════════════════════════╗")
    lines.append(f"║  Claude Science — Scorecard for agent: {report.agent:<14}║")
    lines.append("╚══════════════════════════════════════════════════════╝")
    lines.append(f"  Tasks run     : {len(report.results)}")
    lines.append(f"  OVERALL SCORE : {report.overall():.3f}   (0=floor, 1=expert)")
    lines.append("")
    lines.append("  By capability")
    for cap, sc in report.by_capability().items():
        lines.append(f"    {cap:<28} {_bar(sc)} {sc:.3f}")
    lines.append("")
    lines.append("  By environment")
    for env, sc in report.by_env().items():
        lines.append(f"    {env:<28} {_bar(sc)} {sc:.3f}")
    lines.append("")
    lines.append("  Per-task detail")
    lines.append(f"    {'task':<26}{'score':>7}{'calls':>7}{'time_s':>8}")
    for r in report.results:
        lines.append(
            f"    {r.task_id:<26}{r.score:>7.3f}{r.n_tool_calls:>7}{r.wall_s:>8.2f}"
        )
    return "\n".join(lines)


def _bar(score: float, width: int = 20) -> str:
    filled = int(round(score * width))
    return "▐" + "█" * filled + "░" * (width - filled) + "▌"
