"""Claude Science command-line interface.

    python -m claude_science env list
    python -m claude_science agent run --env assay --seed 0 --agent heuristic
    python -m claude_science bench run --agent heuristic --seeds 0,1,2
    python -m claude_science bench run --agent claude --model claude-fable-5

Agents: heuristic (expert baseline), random (floor), claude (real API).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List

from .benchmark import BenchmarkRunner, render_scorecard
from .envs import ENVIRONMENTS, list_envs, make_env
from .harness import AnthropicAgent, HeuristicAgent, RandomAgent


def _make_agent(name: str, model: str, max_steps: int):
    if name == "heuristic":
        a = HeuristicAgent()
    elif name == "random":
        a = RandomAgent()
    elif name == "claude":
        a = AnthropicAgent(model=model, max_steps=max_steps)
    else:
        raise SystemExit(f"unknown agent {name!r} (heuristic|random|claude)")
    a.max_steps = max_steps
    return a


def _int_list(s: str) -> List[int]:
    return [int(x) for x in s.split(",") if x.strip() != ""]


def cmd_env_list(_args) -> int:
    print("Available environments:\n")
    for cls in list_envs():
        print(f"  {cls.key:<12} [{cls.capability}]")
        print(f"      {cls.title}")
    print("\nDifficulties: low | medium | high")
    return 0


def cmd_agent_run(args) -> int:
    env = make_env(args.env, seed=args.seed, difficulty=args.difficulty)
    agent = _make_agent(args.agent, args.model, args.max_steps)
    tr = agent.run(env)
    sub = env.result()
    print(tr.pretty())
    print()
    print(f"submitted : {sub is not None}")
    print(f"score     : {sub.score:.3f}" if sub else "score     : 0.000 (no submit)")
    if args.json:
        print(json.dumps(tr.to_dict(), indent=2, default=str))
    return 0


def cmd_bench_run(args) -> int:
    envs = args.envs.split(",") if args.envs else list(ENVIRONMENTS)
    runner = BenchmarkRunner(
        envs=envs,
        seeds=_int_list(args.seeds),
        difficulties=args.difficulties.split(","),
    )
    agent = _make_agent(args.agent, args.model, args.max_steps)
    print(f"Running benchmark: agent={agent.name} "
          f"envs={envs} seeds={args.seeds} diff={args.difficulties}\n")
    report = runner.run(agent, progress=True)
    print()
    print(render_scorecard(report))
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(report.to_dict(include_transcripts=True), fh, indent=2, default=str)
        print(f"\nFull report + transcripts written to {args.out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="claude-science", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    env = sub.add_parser("env", help="environment commands")
    env_sub = env.add_subparsers(dest="env_cmd", required=True)
    env_sub.add_parser("list", help="list environments").set_defaults(func=cmd_env_list)

    ar = sub.add_parser("agent", help="agent commands")
    ar_sub = ar.add_subparsers(dest="agent_cmd", required=True)
    run = ar_sub.add_parser("run", help="run one agent on one environment")
    run.add_argument("--env", required=True, choices=list(ENVIRONMENTS))
    run.add_argument("--agent", default="heuristic")
    run.add_argument("--model", default="claude-fable-5")
    run.add_argument("--seed", type=int, default=0)
    run.add_argument("--difficulty", default="medium", choices=["low", "medium", "high"])
    run.add_argument("--max-steps", type=int, default=12, dest="max_steps")
    run.add_argument("--json", action="store_true", help="also dump transcript JSON")
    run.set_defaults(func=cmd_agent_run)

    bn = sub.add_parser("bench", help="benchmark commands")
    bn_sub = bn.add_subparsers(dest="bench_cmd", required=True)
    brun = bn_sub.add_parser("run", help="run the benchmark suite")
    brun.add_argument("--agent", default="heuristic")
    brun.add_argument("--model", default="claude-fable-5")
    brun.add_argument("--envs", default="", help="comma list; default all")
    brun.add_argument("--seeds", default="0,1,2")
    brun.add_argument("--difficulties", default="medium")
    brun.add_argument("--max-steps", type=int, default=12, dest="max_steps")
    brun.add_argument("--out", default="", help="write JSON report to this path")
    brun.set_defaults(func=cmd_bench_run)

    return p


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
