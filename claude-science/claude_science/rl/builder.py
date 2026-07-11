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


def _mw_task(name: str, smi: str, i: int) -> VerifiableTask:
    gold = chem.descriptors(smi)["mol_weight"]
    return VerifiableTask(
        task_id=f"qa-mw-{i}", domain="cheminformatics",
        prompt=(f"Compute the molecular weight (g/mol) of SMILES {smi}. "
                f"Answer with a single number."),
        judge="numeric", gold=gold, judge_params={"rel_tol": 0.01},
        meta={"name": name, "smiles": smi},
    )


def _tpsa_task(name: str, smi: str, i: int) -> VerifiableTask:
    gold = chem.descriptors(smi)["tpsa"]
    return VerifiableTask(
        task_id=f"qa-tpsa-{i}", domain="cheminformatics",
        prompt=(f"Compute the topological polar surface area (TPSA, in "
                f"angstrom^2) of SMILES {smi}. Answer with a single number."),
        judge="numeric", gold=gold, judge_params={"abs_tol": 1.0},
        meta={"name": name, "smiles": smi},
    )


def _lipinski_task(name: str, smi: str, i: int) -> VerifiableTask:
    gold = "yes" if chem.lipinski(smi)["pass"] else "no"
    return VerifiableTask(
        task_id=f"qa-lipinski-{i}", domain="cheminformatics",
        prompt=(f"Does the molecule {smi} pass Lipinski's rule of five "
                f"(fewer than 2 violations)? Answer 'yes' or 'no'."),
        judge="exact", gold=gold, meta={"name": name, "smiles": smi},
    )


def _alert_task(rng: random.Random, i: int) -> VerifiableTask:
    name, smi = rng.choice(_ALL)
    has = bool(chem.structural_alerts(smi))
    gold = "yes" if has else "no"
    return VerifiableTask(
        task_id=f"qa-alert-{i}", domain="cheminformatics",
        prompt=(f"Does the molecule {smi} contain any reactive structural alert "
                f"(e.g. Michael acceptor, quinone, aldehyde, nitro-aromatic)? "
                f"Answer 'yes' or 'no'."),
        judge="exact", gold=gold, meta={"smiles": smi},
    )


def _tanimoto_task(rng: random.Random, i: int) -> VerifiableTask:
    (na, a), (nb, b) = rng.sample(DRUGS, 2)
    gold = chem.tanimoto(a, b)
    return VerifiableTask(
        task_id=f"qa-tanimoto-{i}", domain="cheminformatics",
        prompt=(f"Compute the ECFP4 (Morgan radius 2, 2048-bit) Tanimoto "
                f"similarity between these two molecules (0-1):\n  A: {a}\n"
                f"  B: {b}\nAnswer with a single number."),
        judge="numeric", gold=gold, judge_params={"abs_tol": 0.03},
        meta={"a": a, "b": b},
    )


def _revcomp_task(rng: random.Random, i: int) -> VerifiableTask:
    start = rng.randrange(0, len(REF_CDS) - 24)
    frag = REF_CDS[start:start + rng.choice([12, 15, 18])]
    gold = seq.reverse_complement(frag)
    return VerifiableTask(
        task_id=f"qa-revcomp-{i}", domain="bioinformatics",
        prompt=(f"Give the reverse complement of this DNA sequence: {frag}"),
        judge="exact", gold=gold, meta={"dna": frag},
    )


def _orf_task(rng: random.Random, i: int) -> VerifiableTask:
    orfs = seq.find_orfs(REF_CDS, min_aa=10)
    protein = orfs[0]["protein"] if orfs else seq.translate(REF_CDS).rstrip("*")
    return VerifiableTask(
        task_id=f"qa-orf-{i}", domain="bioinformatics",
        prompt=(f"Find the longest open reading frame (ATG...stop) in this "
                f"sequence and give its translated protein (1-letter, no stop "
                f"codon):\n{REF_CDS}"),
        judge="exact", gold=protein, meta={},
    )


def _halflife_task(rng: random.Random, i: int) -> VerifiableTask:
    import numpy as np
    ke = round(rng.uniform(0.05, 0.4), 3)
    t = list(np.linspace(0.5, 24, 24))
    c = list(pk.conc_one_compartment_oral(np.array(t), 100, 0.8,
                                          rng.uniform(1.0, 2.0), ke, 30))
    gold = pk.nca(t, c)["half_life"]
    pts = ", ".join(f"({round(ti,1)}h,{round(ci,3)})" for ti, ci in
                    list(zip(t, c))[::3])
    return VerifiableTask(
        task_id=f"qa-halflife-{i}", domain="pharmacology",
        prompt=(f"From this plasma concentration-time profile, estimate the "
                f"terminal elimination half-life in hours: {pts}"),
        judge="numeric", gold=gold, judge_params={"rel_tol": 0.15},
        meta={"ke": ke},
    )


def _formula_task(name: str, smi: str, i: int) -> VerifiableTask:
    from rdkit import Chem
    from rdkit.Chem import rdMolDescriptors
    gold = rdMolDescriptors.CalcMolFormula(Chem.MolFromSmiles(smi))
    return VerifiableTask(
        task_id=f"qa-formula-{i}", domain="cheminformatics",
        prompt=(f"Give the molecular formula (Hill notation, e.g. C9H8O4) of "
                f"SMILES {smi}."),
        judge="exact", gold=gold, meta={"name": name, "smiles": smi},
    )


def _rings_task(name: str, smi: str, i: int) -> VerifiableTask:
    gold = chem.descriptors(smi)["aromatic_rings"]
    return VerifiableTask(
        task_id=f"qa-rings-{i}", domain="cheminformatics",
        prompt=(f"How many aromatic rings does {smi} contain? Answer with an "
                f"integer."),
        judge="numeric", gold=gold, judge_params={"abs_tol": 0.5},
        meta={"name": name, "smiles": smi},
    )


def _rotbonds_task(name: str, smi: str, i: int) -> VerifiableTask:
    gold = chem.descriptors(smi)["rotatable_bonds"]
    return VerifiableTask(
        task_id=f"qa-rotbonds-{i}", domain="cheminformatics",
        prompt=(f"How many rotatable bonds does {smi} have? Answer with an "
                f"integer."),
        judge="numeric", gold=gold, judge_params={"abs_tol": 0.5},
        meta={"name": name, "smiles": smi},
    )


def _most_similar_task(rng: random.Random, i: int) -> VerifiableTask:
    query_name, query = rng.choice(DRUGS)
    library = [s for n, s in DRUGS if n != query_name]
    best = chem.similarity_search(query, library, top_k=1)[0]["smiles"]
    lib = ", ".join(rng.sample(library, min(8, len(library))) + [best])
    return VerifiableTask(
        task_id=f"qa-similar-{i}", domain="virtual-screening",
        prompt=(f"Which molecule in this set is most similar (ECFP4 Tanimoto) to "
                f"the query {query}? Answer with its SMILES.\nSet: {lib}"),
        judge="smiles", gold=best, meta={"query": query},
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
        lambda i: _mw_task(*rng.choice(_ALL), i),
        lambda i: _tpsa_task(*rng.choice(_ALL), i),
        lambda i: _lipinski_task(*rng.choice(_ALL), i),
        lambda i: _alert_task(rng, i),
        lambda i: _tanimoto_task(rng, i),
        lambda i: _druglike_task(
            [s for _, s in rng.sample(DRUGS, 3)] + [rng.choice(DECOYS)[1]], i),
        lambda i: _translate_task(rng, i),
        lambda i: _revcomp_task(rng, i),
        lambda i: _gc_task(rng, i),
        lambda i: _orf_task(rng, i),
        lambda i: _ic50_fit_task(rng, i),
        lambda i: _halflife_task(rng, i),
        lambda i: _formula_task(*rng.choice(_ALL), i),
        lambda i: _rings_task(*rng.choice(_ALL), i),
        lambda i: _rotbonds_task(*rng.choice(_ALL), i),
        lambda i: _most_similar_task(rng, i),
    ]
    for i in range(n_static):
        ds.add(generators[i % len(generators)](i))

    if include_agentic:
        for s in (agentic_seeds or [0, 1]):
            for key in ENVIRONMENTS:
                ds.add(_agentic_task(key, s, "medium"))
    return ds
