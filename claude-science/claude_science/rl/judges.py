"""Verifiers ("judges"): cheap, deterministic functions that turn a model's
answer into a scalar reward in [0, 1].

Verifiable rewards are the whole point of cheap-but-impactful RL: no human
labeller and no expensive reward model, just a programmatic check the answer is
correct. Each judge has the signature ``judge(prediction, gold, **params) ->
Verdict`` and is registered by name so a task can reference it as data.

Included judges span the domains in this package:

* ``exact``        -- normalised string equality
* ``numeric``      -- absolute/relative numeric tolerance
* ``log_fold``     -- potency-style agreement (|log10(pred/gold)| bands)
* ``set_overlap``  -- fraction of a gold set recovered (screening / retrieval)
* ``smiles``       -- RDKit canonical-SMILES equality (chemistry-aware)
* ``regex``        -- answer matches a pattern
* ``env_score``    -- reconstruct a benchmark environment and score a submission
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict


@dataclass
class Verdict:
    reward: float          # in [0, 1]
    passed: bool
    detail: str = ""


JudgeFn = Callable[..., Verdict]
_REGISTRY: Dict[str, JudgeFn] = {}


def register(name: str):
    def deco(fn: JudgeFn) -> JudgeFn:
        _REGISTRY[name] = fn
        return fn
    return deco


def get_judge(name: str) -> JudgeFn:
    if name not in _REGISTRY:
        raise KeyError(f"unknown judge {name!r}; have {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def judge_names():
    return sorted(_REGISTRY)


def _norm(s: Any) -> str:
    return str(s).strip().lower().replace(" ", "")


@register("exact")
def exact(prediction: Any, gold: Any, **_: Any) -> Verdict:
    ok = _norm(prediction) == _norm(gold)
    return Verdict(1.0 if ok else 0.0, ok)


@register("numeric")
def numeric(prediction: Any, gold: Any, abs_tol: float = 0.0,
            rel_tol: float = 0.02, **_: Any) -> Verdict:
    try:
        p, g = float(prediction), float(gold)
    except (TypeError, ValueError):
        return Verdict(0.0, False, "non-numeric prediction")
    tol = max(abs_tol, rel_tol * abs(g))
    err = abs(p - g)
    ok = err <= tol
    reward = 1.0 if ok else max(0.0, 1.0 - (err - tol) / (abs(g) + 1e-9))
    return Verdict(round(reward, 4), ok, f"err={err:.4g} tol={tol:.4g}")


@register("log_fold")
def log_fold(prediction: Any, gold: Any, max_fold: float = 10.0, **_: Any) -> Verdict:
    try:
        p, g = float(prediction), float(gold)
    except (TypeError, ValueError):
        return Verdict(0.0, False, "non-numeric")
    if p <= 0 or g <= 0:
        return Verdict(0.0, False, "non-positive")
    fold = abs(math.log10(p / g))
    reward = max(0.0, 1.0 - fold / math.log10(max_fold))
    return Verdict(round(reward, 4), fold <= math.log10(2.0), f"fold=10^{fold:.2f}")


@register("set_overlap")
def set_overlap(prediction: Any, gold: Any, **_: Any) -> Verdict:
    pred = {_norm(x) for x in (prediction or [])}
    goldset = {_norm(x) for x in (gold or [])}
    if not goldset:
        return Verdict(1.0, True)
    recovered = len(pred & goldset) / len(goldset)
    return Verdict(round(recovered, 4), recovered >= 0.999,
                   f"{len(pred & goldset)}/{len(goldset)}")


@register("smiles")
def smiles(prediction: Any, gold: Any, **_: Any) -> Verdict:
    from ..science import chem
    try:
        ok = chem.canonical_smiles(str(prediction)) == chem.canonical_smiles(str(gold))
    except Exception:
        return Verdict(0.0, False, "unparseable SMILES")
    return Verdict(1.0 if ok else 0.0, ok)


@register("regex")
def regex(prediction: Any, gold: Any, pattern: str = "", **_: Any) -> Verdict:
    ok = re.fullmatch(pattern or str(gold), str(prediction).strip()) is not None
    return Verdict(1.0 if ok else 0.0, ok)


@register("env_score")
def env_score(prediction: Any, gold: Any, env_key: str = "", seed: int = 0,
              difficulty: str = "medium", **_: Any) -> Verdict:
    """Reconstruct a benchmark environment and score a submission payload.

    ``prediction`` is the submit-payload dict. Deterministic given
    (env_key, seed, difficulty), so it is a fully verifiable reward.
    """
    from ..envs import make_env
    env = make_env(env_key, seed=seed, difficulty=difficulty)
    reward = float(env.score(prediction if isinstance(prediction, dict) else {}))
    return Verdict(round(reward, 4), reward >= 0.999, f"env={env_key}")
