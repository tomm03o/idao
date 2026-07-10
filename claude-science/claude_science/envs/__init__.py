"""Environment registry.

Six environments spanning the real Claude Science domains: cheminformatics,
virtual screening, assay pharmacology, quantitative PK, bioinformatics, and
computational chemistry. Each is backed by a validated algorithm (RDKit / scipy
/ numpy), not a surrogate.
"""

from __future__ import annotations

from typing import Dict, List, Type

from .base import Environment
from .admet import ADMETEnv
from .screen import ScreenEnv
from .ic50 import IC50Env
from .pkpd import PKPDEnv
from .variant import VariantEnv
from .conformer import ConformerEnv

ENVIRONMENTS: Dict[str, Type[Environment]] = {
    cls.key: cls
    for cls in (ADMETEnv, ScreenEnv, IC50Env, PKPDEnv, VariantEnv, ConformerEnv)
}


def make_env(key: str, seed: int = 0, difficulty: str = "medium") -> Environment:
    if key not in ENVIRONMENTS:
        raise KeyError(f"unknown env {key!r}; available: {list(ENVIRONMENTS)}")
    return ENVIRONMENTS[key](seed=seed, difficulty=difficulty)


def list_envs() -> List[Type[Environment]]:
    return list(ENVIRONMENTS.values())


__all__ = ["ENVIRONMENTS", "make_env", "list_envs", "Environment"]
