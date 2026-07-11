"""Environment registry.

Environments span multiple computational-research domains. Life sciences:
cheminformatics, virtual screening, assay pharmacology, quantitative PK,
bioinformatics, computational chemistry. Numerics: root-finding, optimisation,
quadrature, linear algebra. Each is backed by a validated algorithm (RDKit /
scipy / numpy), not a surrogate, and ships an expert reference policy.
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
from .numerics import (RootFindEnv, OptimizeEnv, QuadratureEnv, EigenvalueEnv)

ENVIRONMENTS: Dict[str, Type[Environment]] = {
    cls.key: cls
    for cls in (ADMETEnv, ScreenEnv, IC50Env, PKPDEnv, VariantEnv, ConformerEnv,
                RootFindEnv, OptimizeEnv, QuadratureEnv, EigenvalueEnv)
}


def envs_by_domain() -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for cls in ENVIRONMENTS.values():
        out.setdefault(cls.domain, []).append(cls.key)
    return out


def make_env(key: str, seed: int = 0, difficulty: str = "medium") -> Environment:
    if key not in ENVIRONMENTS:
        raise KeyError(f"unknown env {key!r}; available: {list(ENVIRONMENTS)}")
    return ENVIRONMENTS[key](seed=seed, difficulty=difficulty)


def list_envs() -> List[Type[Environment]]:
    return list(ENVIRONMENTS.values())


__all__ = ["ENVIRONMENTS", "make_env", "list_envs", "envs_by_domain", "Environment"]
