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
from . import science
from . import data_sources
from . import rl
from . import research
from .workspace import Workspace, workspace_tools
from .toolkits import lab_bench, science_tools
from .retrieval import Corpus, retrieval_tools
from . import rag

__version__ = "0.4.0"

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
    "science",
    "data_sources",
    "rl",
    "research",
    "Workspace",
    "workspace_tools",
    "lab_bench",
    "science_tools",
    "Corpus",
    "retrieval_tools",
    "rag",
    "__version__",
]
