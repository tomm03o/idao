"""Environment registry."""

from __future__ import annotations

from typing import Dict, List, Type

from .base import Environment
from .assay import AssayEnv
from .docking import DockingEnv
from .knockout import KnockoutEnv
from .pkpd import PKPDEnv

ENVIRONMENTS: Dict[str, Type[Environment]] = {
    cls.key: cls for cls in (PKPDEnv, AssayEnv, DockingEnv, KnockoutEnv)
}


def make_env(key: str, seed: int = 0, difficulty: str = "medium") -> Environment:
    if key not in ENVIRONMENTS:
        raise KeyError(f"unknown env {key!r}; available: {list(ENVIRONMENTS)}")
    return ENVIRONMENTS[key](seed=seed, difficulty=difficulty)


def list_envs() -> List[Type[Environment]]:
    return list(ENVIRONMENTS.values())


__all__ = ["ENVIRONMENTS", "make_env", "list_envs", "Environment"]
