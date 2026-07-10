"""Claude Science — an agent harness and benchmark for biological and
pharmaceutical simulation tasks.

Quick start::

    from claude_science import make_env, HeuristicAgent
    env = make_env("assay", seed=0)
    tr = HeuristicAgent().run(env)
    print(env.result().score)

See ``claude_science.cli`` (``python -m claude_science ...``) for the CLI.
"""

from .envs import ENVIRONMENTS, make_env, list_envs
from .harness import Agent, AnthropicAgent, HeuristicAgent, RandomAgent
from .benchmark import BenchmarkRunner, render_scorecard

__version__ = "0.1.0"

__all__ = [
    "ENVIRONMENTS",
    "make_env",
    "list_envs",
    "Agent",
    "AnthropicAgent",
    "HeuristicAgent",
    "RandomAgent",
    "BenchmarkRunner",
    "render_scorecard",
    "__version__",
]
