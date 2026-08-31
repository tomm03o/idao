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
from .harness import (AnthropicAgent, HeuristicAgent, OpenRouterAgent,
                      RandomAgent)


def _make_agent(name: str, model: str, max_steps: int):
    if name == "heuristic":
        a = HeuristicAgent()
    elif name == "random":
        a = RandomAgent()
    elif name == "claude":
        a = AnthropicAgent(model=model, max_steps=max_steps)
    elif name == "openrouter":
        a = OpenRouterAgent(model=model, max_steps=max_steps)
    else:
        raise SystemExit(
            f"unknown agent {name!r} (heuristic|random|claude|openrouter)")
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


def cmd_bench_compare(args) -> int:
    from .benchmark import run_leaderboard, render_leaderboard
    import json as _json
    envs = args.envs.split(",") if args.envs else list(ENVIRONMENTS)
    runner = BenchmarkRunner(envs=envs, seeds=_int_list(args.seeds),
                             difficulties=args.difficulties.split(","))
    specs = [s.strip() for s in args.agents.split(",") if s.strip()]
    lb = run_leaderboard(specs, runner, max_steps=args.max_steps)
    print(render_leaderboard(lb))
    if args.out:
        with open(args.out, "w") as fh:
            _json.dump(lb.to_dict(), fh, indent=2, default=str)
        print(f"\nLeaderboard JSON written to {args.out}")
    return 0


def cmd_rl_build(args) -> int:
    from .rl import (build_dataset, run_rollouts, OracleSolver,
                     to_sft_jsonl, to_preference_jsonl, to_rlvr_jsonl, NullSolver)
    ds = build_dataset(
        n_static=args.n_static, seed=args.seed,
        include_agentic=not args.no_agentic,
        agentic_seeds=_int_list(args.agentic_seeds),
    )
    print(f"Built {len(ds)} verifiable tasks. By domain: {ds.by_domain()}")
    ds.save_jsonl(f"{args.out_prefix}.tasks.jsonl")
    to_rlvr_jsonl(ds, f"{args.out_prefix}.rlvr.jsonl")
    print(f"  wrote {args.out_prefix}.tasks.jsonl and {args.out_prefix}.rlvr.jsonl")
    if args.rollouts:
        oracle = run_rollouts(ds, OracleSolver())
        null = run_rollouts(ds, NullSolver())
        n_sft = to_sft_jsonl(oracle, f"{args.out_prefix}.sft.jsonl")
        n_pref = to_preference_jsonl(oracle + null, f"{args.out_prefix}.pref.jsonl")
        import statistics
        print(f"  oracle mean reward={statistics.mean(r.reward for r in oracle):.3f} "
              f"null={statistics.mean(r.reward for r in null):.3f}")
        print(f"  wrote {n_sft} SFT and {n_pref} preference examples")
    return 0


def cmd_data_query(args) -> int:
    from .data_sources import database_tools
    reg = database_tools()
    res = reg.dispatch(args.tool, dict(a.split("=", 1) for a in args.arg))
    print(res.to_text())
    return 0


def cmd_research_validate(args) -> int:
    from .research.validate_adaptive_design import main as validate
    validate()
    return 0


def cmd_lab_tools(args) -> int:
    from .toolkits import lab_bench
    reg = lab_bench(with_databases=not args.no_databases)
    print(f"Lab bench: {len(reg.names())} tools\n")
    for name in reg.names():
        print(f"  {name:26} {reg.get(name).description[:70]}")
    if getattr(reg, "_workspace", None):
        reg._workspace.cleanup()
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

    bcmp = bn_sub.add_parser("compare", help="rank several agents/models on the suite")
    bcmp.add_argument("--agents", required=True,
                      help="comma list of specs: heuristic,random,"
                           "openrouter:tencent/hy3:free,claude:claude-fable-5")
    bcmp.add_argument("--envs", default="", help="comma list; default all")
    bcmp.add_argument("--seeds", default="0")
    bcmp.add_argument("--difficulties", default="low")
    bcmp.add_argument("--max-steps", type=int, default=12, dest="max_steps")
    bcmp.add_argument("--out", default="", help="write leaderboard JSON here")
    bcmp.set_defaults(func=cmd_bench_compare)

    # rl build
    rl = sub.add_parser("rl", help="verifiable-task datasets for training/RL")
    rl_sub = rl.add_subparsers(dest="rl_cmd", required=True)
    rb = rl_sub.add_parser("build", help="build a verifiable-task dataset + exports")
    rb.add_argument("--n-static", type=int, default=60, dest="n_static")
    rb.add_argument("--seed", type=int, default=0)
    rb.add_argument("--agentic-seeds", default="0,1", dest="agentic_seeds")
    rb.add_argument("--no-agentic", action="store_true", dest="no_agentic")
    rb.add_argument("--rollouts", action="store_true",
                    help="also run oracle/null solvers and export SFT+preference")
    rb.add_argument("--out-prefix", default="dataset", dest="out_prefix")
    rb.set_defaults(func=cmd_rl_build)

    # data query
    dq = sub.add_parser("data", help="query public bio/chem databases")
    dq_sub = dq.add_subparsers(dest="data_cmd", required=True)
    q = dq_sub.add_parser("query", help="call a database tool")
    q.add_argument("tool", help="pubchem_compound | chembl_molecule | "
                   "chembl_target_activities | uniprot_protein | pdb_entry")
    q.add_argument("arg", nargs="+", help="key=value tool arguments")
    q.set_defaults(func=cmd_data_query)

    # research validate
    rs = sub.add_parser("research", help="reproduce novel-algorithm validations")
    rs_sub = rs.add_subparsers(dest="research_cmd", required=True)
    rs_sub.add_parser("validate-design",
                      help="adaptive vs fixed IC50 design Monte-Carlo").set_defaults(
        func=cmd_research_validate)

    # lab tools
    lab = sub.add_parser("lab", help="the composed simulated-laboratory toolkit")
    lab_sub = lab.add_subparsers(dest="lab_cmd", required=True)
    lt = lab_sub.add_parser("tools", help="list the lab-bench agent tools")
    lt.add_argument("--no-databases", action="store_true", dest="no_databases")
    lt.set_defaults(func=cmd_lab_tools)

    return p


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
