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


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="claude-science-viz", description=__doc__)
    p.add_argument("--out", default="dashboard.html")
    p.add_argument("--difficulty", default="low")
    p.add_argument("--n-static", type=int, default=120, dest="n_static")
    args = p.parse_args(argv)
    data = collect(difficulty=args.difficulty, n_static=args.n_static)
    render(data, args.out)
    print(f"wrote {args.out}  (expert {data['heuristic']['overall']:.2f} / "
          f"floor {data['random']['overall']:.2f}, {data['rl_total']} tasks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
