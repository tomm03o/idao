"""Tanimoto-kernel Gaussian-process Bayesian optimisation for hit discovery,
with conformal prediction intervals.

This module targets the question a screening team actually asks: *given a large
virtual library and a fixed budget of expensive assays, how do we find the most
potent compounds with the fewest experiments?* -- not "minimise global RMSE",
which is the wrong objective and one where naive active learning does not beat
random selection (a known result we reproduce honestly in the validation script).

Components
----------
* :class:`TanimotoGP` -- a Gaussian process over ECFP4 fingerprints with the
  Tanimoto (Jaccard) kernel, the state-of-the-art low-data surrogate for
  molecular property prediction (Griffiths et al., GAUCHE, NeurIPS 2023). It
  gives a posterior mean *and* variance in closed form.
* acquisition functions ``greedy`` (pure exploitation of predicted potency) and
  ``ucb`` (mean + beta*std) for the hit-finding objective, plus a ``random``
  baseline.
* :func:`screen_campaign` -- simulate a sequential screening campaign and report
  top-k recall vs assays spent.
* :class:`ConformalRegressor` -- split conformal prediction on top of the GP,
  giving prediction intervals with a *distribution-free, finite-sample* coverage
  guarantee (Vovk; Lei et al., 2018), unlike heuristic model confidence.

Everything is validated on real ChEMBL bioactivity data; see
``research/validate_molecular_bo.py``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Dict, List, Sequence, Tuple

import numpy as np
from rdkit import DataStructs
from scipy.linalg import cho_factor, cho_solve

from ..science.chem import fingerprint


# --------------------------------------------------------------------------- #
# Tanimoto kernel
# --------------------------------------------------------------------------- #
def _fps(smiles: Sequence[str]):
    return [fingerprint(s) for s in smiles]


def tanimoto_kernel(fps_a, fps_b) -> np.ndarray:
    """Tanimoto (Jaccard) similarity matrix -- a valid PSD kernel on bit vectors."""
    return np.array([DataStructs.BulkTanimotoSimilarity(a, list(fps_b))
                     for a in fps_a])


# --------------------------------------------------------------------------- #
# Gaussian process
# --------------------------------------------------------------------------- #
class TanimotoGP:
    """Exact GP regression with the Tanimoto kernel; k(x,x)=1 for any molecule."""

    def __init__(self, noise: float = 0.4):
        self.noise = noise
        self._fps = None
        self._chol = None
        self._alpha = None
        self._mu = 0.0

    def fit(self, smiles: Sequence[str], y: Sequence[float]) -> "TanimotoGP":
        self._fps = _fps(smiles)
        y = np.asarray(y, dtype=float)
        self._mu = float(y.mean())
        K = tanimoto_kernel(self._fps, self._fps)
        K[np.diag_indices_from(K)] += self.noise ** 2
        self._chol = cho_factor(K, lower=True)
        self._alpha = cho_solve(self._chol, y - self._mu)
        return self

    def predict(self, smiles: Sequence[str], with_noise: bool = False
                ) -> Tuple[np.ndarray, np.ndarray]:
        """Posterior mean and variance. Variance in [0,1] (+ noise if requested)."""
        fq = _fps(smiles)
        Ks = tanimoto_kernel(fq, self._fps)
        mean = Ks @ self._alpha + self._mu
        var = 1.0 - np.einsum("ij,ji->i", Ks, cho_solve(self._chol, Ks.T))
        var = np.clip(var, 1e-9, None)
        if with_noise:
            var = var + self.noise ** 2
        return mean, var


# --------------------------------------------------------------------------- #
# Acquisition functions (hit-finding objective)
# --------------------------------------------------------------------------- #
def acq_greedy(mean: np.ndarray, std: np.ndarray, beta: float = 0.0) -> np.ndarray:
    return mean


def acq_ucb(mean: np.ndarray, std: np.ndarray, beta: float = 1.0) -> np.ndarray:
    return mean + beta * std


ACQUISITIONS: Dict[str, Callable] = {"greedy": acq_greedy, "ucb": acq_ucb}


# --------------------------------------------------------------------------- #
# Screening campaign simulation
# --------------------------------------------------------------------------- #
@dataclass
class CampaignResult:
    strategy: str
    assays: List[int]
    topk_recall: List[float]

    def final_recall(self) -> float:
        return self.topk_recall[-1] if self.topk_recall else 0.0


def screen_campaign(smiles: Sequence[str], y: Sequence[float], *,
                    strategy: str = "greedy", top_k: int = 30,
                    n_init: int = 15, batch: int = 15, rounds: int = 12,
                    noise: float = 0.4, beta: float = 1.0,
                    seed: int = 0) -> CampaignResult:
    """Simulate a sequential screen; return top-k recall vs number of assays.

    ``strategy`` is 'greedy', 'ucb', or 'random'. Recall = fraction of the true
    top-``top_k`` most-potent library members whose assay has been run so far.
    """
    y = np.asarray(y, dtype=float)
    n = len(y)
    rng = np.random.default_rng(seed)
    true_top = set(np.argsort(-y)[:top_k].tolist())

    labeled = list(rng.choice(n, n_init, replace=False))
    pool = [i for i in range(n) if i not in set(labeled)]
    assays, recall = [], []

    for _ in range(rounds):
        assays.append(len(labeled))
        recall.append(len(true_top & set(labeled)) / top_k)
        if len(pool) < batch:
            break
        if strategy == "random":
            order = rng.permutation(len(pool))
        else:
            gp = TanimotoGP(noise=noise).fit([smiles[i] for i in labeled], y[labeled])
            mean, var = gp.predict([smiles[i] for i in pool])
            score = ACQUISITIONS[strategy](mean, np.sqrt(var), beta)
            order = np.argsort(-score)
        chosen = [pool[j] for j in order[:batch]]
        for x in chosen:
            labeled.append(x)
            pool.remove(x)
    return CampaignResult(strategy, assays, recall)


def compare_strategies(smiles, y, strategies=("greedy", "ucb", "random"),
                       **kw) -> Dict[str, CampaignResult]:
    return {s: screen_campaign(smiles, y, strategy=s, **kw) for s in strategies}


# --------------------------------------------------------------------------- #
# Conformal prediction (distribution-free coverage guarantee)
# --------------------------------------------------------------------------- #
class ConformalRegressor:
    """Split conformal on a fitted TanimotoGP with variance-normalised scores.

    Guarantees ``P(y in interval) >= 1 - alpha`` (marginal, finite-sample) for
    exchangeable data, regardless of whether the GP is well-specified.
    """

    def __init__(self, gp: TanimotoGP):
        self.gp = gp
        self._scores = None

    def calibrate(self, smiles: Sequence[str], y: Sequence[float]
                  ) -> "ConformalRegressor":
        mean, var = self.gp.predict(smiles, with_noise=True)
        y = np.asarray(y, dtype=float)
        self._scores = np.abs(y - mean) / np.sqrt(var)
        return self

    def interval(self, smiles: Sequence[str], alpha: float = 0.1
                 ) -> Tuple[np.ndarray, np.ndarray]:
        n = len(self._scores)
        level = math.ceil((n + 1) * (1 - alpha)) / n
        q = float(np.quantile(self._scores, min(level, 1.0), method="higher"))
        mean, var = self.gp.predict(smiles, with_noise=True)
        half = q * np.sqrt(var)
        return mean - half, mean + half

    @staticmethod
    def coverage(lo: np.ndarray, hi: np.ndarray, y: Sequence[float]) -> float:
        y = np.asarray(y, dtype=float)
        return float(np.mean((y >= lo) & (y <= hi)))
