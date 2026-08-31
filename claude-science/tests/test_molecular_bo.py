"""Tests for the Tanimoto-GP Bayesian-optimisation module.

Uses a deterministic synthetic library (no network): alkane/alcohol/acid/amine
chains whose 'potency' is the carbon count -- a smooth structure-activity signal
the Tanimoto kernel can learn. The real-data validation lives in
research/validate_molecular_bo.py.
"""

import statistics

import numpy as np
import pytest

from claude_science.research.molecular_bo import (
    TanimotoGP, ConformalRegressor, tanimoto_kernel, screen_campaign,
    compare_strategies,
)
from claude_science.science.chem import fingerprint


def _synthetic():
    smiles, y = [], []
    for tail, bump in (("", 0.0), ("O", 0.25), ("C(=O)O", 0.5), ("N", 0.15)):
        for n in range(1, 18):
            smiles.append("C" * n + tail)
            y.append(n + bump)
    return smiles, np.array(y, dtype=float)


def test_tanimoto_kernel_is_valid():
    smiles, _ = _synthetic()
    fps = [fingerprint(s) for s in smiles[:30]]
    K = tanimoto_kernel(fps, fps)
    assert np.allclose(np.diag(K), 1.0)          # self-similarity = 1
    assert np.allclose(K, K.T)                    # symmetric
    assert K.min() >= 0.0 and K.max() <= 1.0      # bounded
    assert np.linalg.eigvalsh(K).min() > -1e-6    # PSD


def test_gp_learns_structure_activity():
    smiles, y = _synthetic()
    rng = np.random.default_rng(0)
    idx = rng.permutation(len(smiles))
    tr, te = idx[:45], idx[45:]
    gp = TanimotoGP(noise=0.3).fit([smiles[i] for i in tr], y[tr])
    mean, var = gp.predict([smiles[i] for i in te])
    assert np.corrcoef(mean, y[te])[0, 1] > 0.4   # predicts held-out potency
    assert np.all(var >= 0)


def test_bo_greedy_beats_random_on_hit_discovery():
    smiles, y = _synthetic()
    kw = dict(top_k=10, n_init=8, batch=5, rounds=7)
    greedy = statistics.mean(
        screen_campaign(smiles, y, strategy="greedy", seed=s, **kw).final_recall()
        for s in range(5))
    random = statistics.mean(
        screen_campaign(smiles, y, strategy="random", seed=s, **kw).final_recall()
        for s in range(5))
    assert greedy > random                        # BO finds hits faster


def test_conformal_coverage_meets_target():
    smiles, y = _synthetic()
    rng = np.random.default_rng(3)
    idx = rng.permutation(len(smiles))
    tr, cal, te = idx[:34], idx[34:51], idx[51:]
    gp = TanimotoGP(noise=0.4).fit([smiles[i] for i in tr], y[tr])
    cp = ConformalRegressor(gp).calibrate([smiles[i] for i in cal], y[cal])
    lo, hi = cp.interval([smiles[i] for i in te], alpha=0.2)
    # marginal guarantee is 1-alpha=0.8; allow finite-sample slack
    assert cp.coverage(lo, hi, y[te]) >= 0.65
    assert np.all(hi >= lo)


def test_compare_strategies_returns_all():
    smiles, y = _synthetic()
    res = compare_strategies(smiles, y, strategies=("greedy", "ucb", "random"),
                             top_k=8, n_init=6, batch=5, rounds=4, seed=0)
    assert set(res) == {"greedy", "ucb", "random"}
    assert all(len(r.topk_recall) >= 1 for r in res.values())
