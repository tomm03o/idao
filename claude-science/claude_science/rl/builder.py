"""Build datasets of verifiable tasks.

Two families are produced:

* **static QA** -- single-shot questions whose gold answer is computed by the
  validated science layer, graded by a cheap deterministic judge (numeric /
  exact / smiles / set_overlap). No agent loop needed; ideal for SFT and for
  fast RL reward signals.
* **agentic** -- a benchmark environment instance graded by the ``env_score``
  judge (reconstructed deterministically from key/seed/difficulty).

Together they give a spread of difficulties and a fully automatic reward for
every item -- the substrate for cheap RL with verifiable rewards (RLVR).
"""

from __future__ import annotations

import random
from typing import List

from ..envs import ENVIRONMENTS
from ..envs.data import DRUGS, DECOYS, REF_CDS
from ..science import chem, pk, seq
from .tasks import TaskDataset, VerifiableTask

_ALL = DRUGS + DECOYS


def _qed_task(name: str, smi: str, i: int) -> VerifiableTask:
    gold = chem.descriptors(smi)["qed"]
    return VerifiableTask(
        task_id=f"qa-qed-{i}",
        domain="cheminformatics",
        prompt=(f"Compute the QED (quantitative estimate of drug-likeness) of "
                f"the molecule with SMILES {smi}. Answer with a single number "
                f"rounded to 3 decimals."),
        judge="numeric", gold=gold,
        judge_params={"abs_tol": 0.02},
        meta={"name": name, "smiles": smi},
    )


def _logp_task(name: str, smi: str, i: int) -> VerifiableTask:
    gold = chem.descriptors(smi)["clogp"]
    return VerifiableTask(
        task_id=f"qa-logp-{i}", domain="cheminformatics",
        prompt=(f"Compute the Crippen cLogP of SMILES {smi}. "
                f"Answer with a single number."),
        judge="numeric", gold=gold, judge_params={"abs_tol": 0.2},
        meta={"name": name, "smiles": smi},
    )


def _druglike_task(cands: List[str], i: int) -> VerifiableTask:
    def qual(s: str) -> float:
        d = chem.descriptors(s)
        if not d["lipinski_pass"] or not d["veber_pass"] or chem.structural_alerts(s):
            return -1.0
        return d["qed"]
    best = max(cands, key=qual)
    listing = ", ".join(cands)
    return VerifiableTask(
        task_id=f"qa-druglike-{i}", domain="cheminformatics",
        prompt=(f"Which of these molecules is the best oral drug candidate "
                f"(drug-like, no structural alerts, highest QED)? Answer with "
                f"its SMILES.\nCandidates: {listing}"),
        judge="smiles", gold=best,
        meta={"candidates": cands},
    )


def _translate_task(rng: random.Random, i: int) -> VerifiableTask:
    start = rng.randrange(0, len(REF_CDS) - 30) // 3 * 3
    frag = REF_CDS[start:start + rng.choice([18, 21, 24])]
    gold = seq.translate(frag)
    return VerifiableTask(
        task_id=f"qa-translate-{i}", domain="bioinformatics",
        prompt=(f"Translate this DNA coding sequence to a one-letter amino-acid "
                f"string (standard genetic code): {frag}"),
        judge="exact", gold=gold, meta={"dna": frag},
    )


def _gc_task(rng: random.Random, i: int) -> VerifiableTask:
    start = rng.randrange(0, len(REF_CDS) - 40)
    frag = REF_CDS[start:start + 40]
    gold = seq.gc_content(frag)
    return VerifiableTask(
        task_id=f"qa-gc-{i}", domain="bioinformatics",
        prompt=(f"What is the GC content (fraction, 0-1) of this sequence? "
                f"{frag}"),
        judge="numeric", gold=gold, judge_params={"abs_tol": 0.01},
        meta={"dna": frag},
    )


def _ic50_fit_task(rng: random.Random, i: int) -> VerifiableTask:
    true_ic50 = 10 ** rng.uniform(1, 3.5)
    x = [true_ic50 / 10, true_ic50 / 3, true_ic50, true_ic50 * 3, true_ic50 * 10]
    y = [round(float(pk.four_pl(c, 0, 100, true_ic50, 1.0)), 2) for c in x]
    pairs = ", ".join(f"({round(c,1)}nM,{r}%)" for c, r in zip(x, y))
    gold = pk.fit_dose_response(x, y)["ic50"]
    return VerifiableTask(
        task_id=f"qa-ic50-{i}", domain="pharmacology",
        prompt=(f"Given these (concentration, % inhibition) dose-response "
                f"points, estimate the IC50 in nM: {pairs}"),
        judge="log_fold", gold=gold, judge_params={"max_fold": 10.0},
        meta={"x": x, "y": y},
    )


def _agentic_task(env_key: str, seed: int, difficulty: str) -> VerifiableTask:
    from ..envs import make_env
    env = make_env(env_key, seed=seed, difficulty=difficulty)
    return VerifiableTask(
        task_id=f"agentic-{env.task_id}",
        domain=env.capability,
        prompt=env.task_prompt(),
        system=env.system_prompt(),
        judge="env_score", gold=None,
        judge_params={"env_key": env_key, "seed": seed, "difficulty": difficulty},
        meta={"env": env_key, "note": "prediction = submit-payload dict"},
    )


def build_dataset(n_static: int = 60, seed: int = 0,
                  include_agentic: bool = True,
                  agentic_seeds: List[int] | None = None) -> TaskDataset:
    """Assemble a mixed verifiable-task dataset."""
    rng = random.Random(seed)
    ds = TaskDataset()

    generators = [
        lambda i: _qed_task(*rng.choice(_ALL), i),
        lambda i: _logp_task(*rng.choice(_ALL), i),
        lambda i: _druglike_task(
            [s for _, s in rng.sample(DRUGS, 3)] + [rng.choice(DECOYS)[1]], i),
        lambda i: _translate_task(rng, i),
        lambda i: _gc_task(rng, i),
        lambda i: _ic50_fit_task(rng, i),
    ]
    for i in range(n_static):
        ds.add(generators[i % len(generators)](i))

    if include_agentic:
        for s in (agentic_seeds or [0, 1]):
            for key in ENVIRONMENTS:
                ds.add(_agentic_task(key, s, "medium"))
    return ds
