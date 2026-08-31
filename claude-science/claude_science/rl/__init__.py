"""Verifiable-task datasets and RL/fine-tuning data pipeline.

Build a dataset of tasks that grade themselves, run agents/solvers over it to
produce reward-labelled rollouts, and export SFT / preference (DPO) / RLVR data.

    from claude_science.rl import build_dataset, run_rollouts, OracleSolver
    ds = build_dataset(n_static=60)
    recs = run_rollouts(ds, OracleSolver())
"""

from .judges import Verdict, get_judge, judge_names, register
from .tasks import TaskDataset, VerifiableTask
from .builder import build_dataset
from .rollout import (
    AgentSolver,
    NullSolver,
    OracleSolver,
    RolloutRecord,
    run_rollouts,
    to_preference_jsonl,
    to_rlvr_jsonl,
    to_sft_jsonl,
)

__all__ = [
    "Verdict", "get_judge", "judge_names", "register",
    "TaskDataset", "VerifiableTask", "build_dataset",
    "AgentSolver", "NullSolver", "OracleSolver", "RolloutRecord",
    "run_rollouts", "to_preference_jsonl", "to_rlvr_jsonl", "to_sft_jsonl",
]
