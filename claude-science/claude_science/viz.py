"""Render a self-contained HTML dashboard from live harness output.

Runs the baseline benchmarks, measures the verifiable-task dataset composition,
and injects the numbers into ``dashboard/template.html`` -- a theme-aware
evaluation & experiment-planning console. Produces one standalone .html file
(no external assets) suitable for sharing or publishing as an artifact.

    python -m claude_science.viz --out dashboard.html
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List

_TEMPLATE = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                         "dashboard", "template.html")

_ADAPTIVE_DEFAULT: List[Dict[str, Any]] = [
    {"range": "4 decades", "n": 6, "fixed": 0.103, "adaptive": 0.145},
    {"range": "7 decades", "n": 6, "fixed": 0.156, "adaptive": 0.157},
    {"range": "10 decades", "n": 6, "fixed": 0.284, "adaptive": 0.215},
    {"range": "10 decades", "n": 8, "fixed": 0.150, "adaptive": 0.106},
]


def collect(seeds: List[int] | None = None, difficulty: str = "low",
            n_static: int = 120) -> Dict[str, Any]:
    """Run baselines + build a dataset and return the dashboard data payload."""
    from .benchmark import BenchmarkRunner
    from .envs import ENVIRONMENTS
    from .harness import HeuristicAgent, RandomAgent
    from .rl import build_dataset

    runner = BenchmarkRunner(seeds=seeds or [0, 1, 2], difficulties=[difficulty])
    rep_h = runner.run(HeuristicAgent())
    rep_r = runner.run(RandomAgent(seed=3))
    ds = build_dataset(n_static=n_static, seed=0, agentic_seeds=[0, 1])
    return {
        "envs": [{"key": c.key, "title": c.title, "capability": c.capability}
                 for c in ENVIRONMENTS.values()],
        "heuristic": {"overall": rep_h.overall(), "by_cap": rep_h.by_capability(),
                      "by_env": rep_h.by_env()},
        "random": {"overall": rep_r.overall(), "by_cap": rep_r.by_capability(),
                   "by_env": rep_r.by_env()},
        "rl_domains": ds.by_domain(), "rl_total": len(ds),
        "adaptive": _ADAPTIVE_DEFAULT,
    }


def render(data: Dict[str, Any], out_path: str) -> str:
    with open(_TEMPLATE) as fh:
        template = fh.read()
    html = template.replace("__DATA__", json.dumps(data))
    with open(out_path, "w") as fh:
        fh.write(html)
    return out_path


_WORKBENCH_TEMPLATE = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                   "dashboard", "workbench_template.html")

_WORKBENCH_MOLS = [
    ("Aspirin", "CC(=O)Oc1ccccc1C(=O)O"),
    ("Imatinib", "Cc1ccc(cc1Nc1nccc(n1)-c1cccnc1)NC(=O)c1ccc(CN2CCN(C)CC2)cc1"),
    ("Gefitinib", "COc1cc2ncnc(Nc3ccc(F)c(Cl)c3)c2cc1OCCCN1CCOCC1"),
    ("Caffeine", "Cn1cnc2c1c(=O)n(C)c(=O)n2C"),
    ("Sildenafil", "CCCc1nn(C)c2c1nc([nH]c2=O)-c1cc(ccc1OCC)S(=O)(=O)N1CCN(C)CC1"),
    ("Ibuprofen", "CC(C)Cc1ccc(cc1)C(C)C(=O)O"),
]


def collect_workbench() -> Dict[str, Any]:
    """Assemble the workbench payload: real molecule depictions + platform state."""
    from .science import chem
    from .envs import ENVIRONMENTS, envs_by_domain, make_env
    from .harness import HeuristicAgent

    molecules = []
    for name, smi in _WORKBENCH_MOLS:
        d = chem.descriptors(smi)
        molecules.append({
            "name": name, "smiles": smi, "svg": chem.to_svg(smi, 260, 190),
            "mw": d["mol_weight"], "clogp": d["clogp"], "qed": d["qed"],
            "tpsa": d["tpsa"], "hbd": d["h_bond_donors"], "hba": d["h_bond_acceptors"],
            "sa": d["sa_score"], "lipinski": d["lipinski_pass"],
        })
    tree = {dom: [{"key": k, "title": ENVIRONMENTS[k].title,
                   "cap": ENVIRONMENTS[k].capability} for k in keys]
            for dom, keys in envs_by_domain().items()}
    env = make_env("rootfind", seed=0, difficulty="low")
    tr = HeuristicAgent().run(env)
    transcript = [{"kind": s.kind,
                   "content": (s.content if isinstance(s.content, str)
                               else json.dumps(s.content))[:120]}
                  for s in tr.steps[:10]]
    return {
        "molecules": molecules, "tree": tree, "transcript": transcript,
        "task": env.task_prompt(),
        "leaderboard": [
            {"spec": "heuristic (expert)", "score": 1.00},
            {"spec": "poolside/laguna-xs-2.1", "score": 0.50},
            {"spec": "tencent/hy3", "score": 0.50},
            {"spec": "random (floor)", "score": 0.00}],
        "stats": {"domains": len(tree), "envs": len(ENVIRONMENTS),
                  "tools": len(_lab_bench_tool_count()), "tests": _test_count()},
    }


def _lab_bench_tool_count():
    from .toolkits import lab_bench
    reg = lab_bench(with_databases=True)
    names = reg.names()
    if getattr(reg, "_workspace", None):
        reg._workspace.cleanup()
    return names


def _test_count() -> int:
    import glob
    import os
    here = os.path.dirname(os.path.dirname(__file__))
    n = 0
    for path in glob.glob(os.path.join(here, "tests", "test_*.py")):
        with open(path) as fh:
            n += sum(1 for line in fh if line.lstrip().startswith("def test_"))
    return n


def render_workbench(out_path: str) -> str:
    with open(_WORKBENCH_TEMPLATE) as fh:
        template = fh.read()
    html = template.replace("__DATA__", json.dumps(collect_workbench()))
    with open(out_path, "w") as fh:
        fh.write(html)
    return out_path


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="claude-science-viz", description=__doc__)
    p.add_argument("--out", default="dashboard.html")
    p.add_argument("--difficulty", default="low")
    p.add_argument("--n-static", type=int, default=120, dest="n_static")
    p.add_argument("--workbench", action="store_true",
                   help="render the Cursor-style research workbench instead")
    args = p.parse_args(argv)
    if args.workbench:
        render_workbench(args.out)
        print(f"wrote workbench → {args.out}")
        return 0
    data = collect(difficulty=args.difficulty, n_static=args.n_static)
    render(data, args.out)
    print(f"wrote {args.out}  (expert {data['heuristic']['overall']:.2f} / "
          f"floor {data['random']['overall']:.2f}, {data['rl_total']} tasks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
