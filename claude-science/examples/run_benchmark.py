"""Programmatic benchmark example.

Runs the expert baseline and the random floor across the full suite and prints
both scorecards side by side. Swap in AnthropicAgent (with ANTHROPIC_API_KEY)
to score a real Claude model:

    from claude_science import AnthropicAgent
    agent = AnthropicAgent(model="claude-fable-5")
"""

from claude_science import BenchmarkRunner, render_scorecard
from claude_science.harness import HeuristicAgent, RandomAgent


def main() -> None:
    runner = BenchmarkRunner(seeds=[0, 1, 2, 3], difficulties=["low", "medium"])
    for agent in (HeuristicAgent(), RandomAgent(seed=7)):
        report = runner.run(agent)
        print(render_scorecard(report))
        print(f"\n>>> {agent.name}: overall = {report.overall():.3f}\n")


if __name__ == "__main__":
    main()
