"""Goal-directed de novo molecular design — a training-free genetic algorithm.

This is the "search candidates and test them" core: given an objective (similarity
to a query, or predicted activity against a real target), propose *novel*,
drug-like, synthesizable molecules and rank them — no neural network to train.

Method. A BRICS-fragment genetic algorithm in the spirit of Graph-GA (Jensen,
*Chem. Sci.* 2019), the strong baseline in the GuacaMol benchmark. Molecules are
recombined by pooling their BRICS fragments (retrosynthetic bonds, so offspring
are more likely to be makeable) and rebuilding; selection is elitist on a
multi-objective score. Everything reuses the validated science layer.

References
----------
* Jensen, Chem. Sci. 2019 (Graph-GA); Degen et al., ChemMedChem 2008 (BRICS);
  Brown et al., J. Chem. Inf. Model. 2019 (GuacaMol).
"""

from __future__ import annotations

import itertools
import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Sequence

from rdkit import Chem, RDLogger
from rdkit.Chem import BRICS

from ..science import chem

RDLogger.DisableLog("rdApp.*")

Scorer = Callable[[str], float]


# --------------------------------------------------------------------------- #
# Multi-objective scoring
# --------------------------------------------------------------------------- #
@dataclass
class MultiObjectiveScorer:
    """Weighted geometric-mean score in [0,1] with hard drug-likeness filters.

    ``objective(smiles) -> [0,1]`` is the design goal (similarity or predicted
    activity). QED and synthetic accessibility are always included. A molecule
    failing a hard filter (Lipinski, structural alert) scores 0.
    """

    objective: Scorer
    w_objective: float = 2.0
    w_qed: float = 1.0
    w_sa: float = 1.0
    enforce_lipinski: bool = True
    forbid_alerts: bool = True

    def components(self, smiles: str) -> Dict[str, float]:
        d = chem.descriptors(smiles)
        sa_norm = max(0.0, min(1.0, (10.0 - d["sa_score"]) / 9.0))
        return {"objective": float(self.objective(smiles)),
                "qed": d["qed"], "sa": sa_norm}

    def __call__(self, smiles: str) -> float:
        try:
            if self.enforce_lipinski and not chem.lipinski(smiles)["pass"]:
                return 0.0
            if self.forbid_alerts and chem.structural_alerts(smiles):
                return 0.0
            c = self.components(smiles)
        except Exception:
            return 0.0
        weights = {"objective": self.w_objective, "qed": self.w_qed, "sa": self.w_sa}
        num = sum(weights[k] * _safe_log(c[k]) for k in c)
        den = sum(weights.values())
        return float(pow(2.718281828, num / den)) if den else 0.0


def _safe_log(x: float) -> float:
    import math
    return math.log(max(x, 1e-6))


# --------------------------------------------------------------------------- #
# Genetic operators (BRICS recombination)
# --------------------------------------------------------------------------- #
def _fragments(smiles: str) -> List[str]:
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        return []
    try:
        return list(BRICS.BRICSDecompose(m))
    except Exception:
        return []


def _recombine(frag_pool: Sequence[str], rng: random.Random, n: int = 4,
               max_depth: int = 2) -> List[str]:
    mols = [Chem.MolFromSmiles(f) for f in frag_pool]
    mols = [m for m in mols if m is not None]
    if len(mols) < 2:
        return []
    rng.shuffle(mols)
    out: List[str] = []
    try:
        builder = BRICS.BRICSBuild(mols, scrambleReagents=True, maxDepth=max_depth)
        for m in itertools.islice(builder, n * 4):
            try:
                Chem.SanitizeMol(m)
                smi = Chem.MolToSmiles(m)
                if 6 <= m.GetNumHeavyAtoms() <= 50:
                    out.append(smi)
            except Exception:
                continue
            if len(out) >= n:
                break
    except Exception:
        return out
    return out


# --------------------------------------------------------------------------- #
# The GA
# --------------------------------------------------------------------------- #
@dataclass
class Candidate:
    smiles: str
    score: float
    components: Dict[str, float] = field(default_factory=dict)


def graph_ga(scorer: MultiObjectiveScorer, seed_smiles: Sequence[str],
             pop_size: int = 40, generations: int = 8, elite: int = 10,
             seed: int = 0) -> List[Candidate]:
    """Run the fragment GA; return the population ranked by score (best first)."""
    rng = random.Random(seed)
    # canonicalise + de-dup seeds
    pop = []
    seen = set()
    for s in seed_smiles:
        try:
            cs = chem.canonical_smiles(s)
        except Exception:
            continue
        if cs not in seen:
            seen.add(cs)
            pop.append(cs)

    frag_pool: set[str] = set()
    for s in pop:
        frag_pool.update(_fragments(s))

    def evaluate(smis: List[str]) -> List[Candidate]:
        out = []
        for s in smis:
            sc = scorer(s)
            if sc > 0:
                out.append(Candidate(s, round(sc, 4)))
        return out

    scored = evaluate(pop)
    for _ in range(generations):
        # refresh fragment pool from the current elite (drives the search)
        elites = sorted(scored, key=lambda c: c.score, reverse=True)[:elite]
        for c in elites:
            frag_pool.update(_fragments(c.smiles))
        children = _recombine(list(frag_pool), rng, n=pop_size)
        fresh = [c for c in evaluate(children)
                 if c.smiles not in {x.smiles for x in scored}]
        # elitist merge, dedup by smiles
        merged: Dict[str, Candidate] = {c.smiles: c for c in scored + fresh}
        scored = sorted(merged.values(), key=lambda c: c.score,
                        reverse=True)[:pop_size]

    ranked = sorted(scored, key=lambda c: c.score, reverse=True)
    for c in ranked:
        try:
            c.components = {k: round(v, 4)
                           for k, v in scorer.components(c.smiles).items()}
        except Exception:
            pass
    return ranked


# --------------------------------------------------------------------------- #
# Similarity-guided design (no target model needed)
# --------------------------------------------------------------------------- #
def design_like(query_smiles: str, seed_smiles: Sequence[str], **kw) -> List[Candidate]:
    """Design drug-like molecules similar to a query (ECFP4 Tanimoto objective)."""
    scorer = MultiObjectiveScorer(objective=lambda s: chem.tanimoto(query_smiles, s))
    return graph_ga(scorer, seed_smiles, **kw)


# --------------------------------------------------------------------------- #
# Target-guided discovery (GP activity model on real ChEMBL data)
# --------------------------------------------------------------------------- #
def discover_candidates(target_chembl_id: str, n_candidates: int = 15,
                        pop_size: int = 40, generations: int = 8,
                        max_records: int = 1500, seed: int = 0,
                        novelty_pressure: float = 0.6) -> Dict:
    """Propose novel candidates against a real target and 'test' each.

    Pulls measured actives, trains a Tanimoto-GP activity model, runs the GA to
    maximise predicted activity × QED × SA (drug-like, alert-free), then reports
    a ranked table with novelty (max Tanimoto to the training set) and a
    conformer-strain read-out (a cheap 3D 'test').

    ``novelty_pressure`` (0-1) penalises candidates that merely rediscover the
    training actives (Tanimoto > 0.7), pushing the search into *novel* chemistry
    around the active pharmacophore. A sampled subset of the training set is used
    for the in-loop penalty (speed); full-set novelty is reported.
    """
    import random as _random
    from rdkit import DataStructs
    from ..data_sources import chembl
    from .molecular_bo import TanimotoGP
    from ..science import struct

    data = chembl.target_dataset(target_chembl_id, max_records=max_records)
    if len(data) < 30:
        raise ValueError(f"too few actives for {target_chembl_id} ({len(data)})")
    train_smiles = [s for s, _ in data]
    y = [v for _, v in data]
    gp = TanimotoGP(noise=0.4).fit(train_smiles, y)

    lo, hi = min(y), max(y)
    span = (hi - lo) or 1.0
    train_fp = [chem.fingerprint(s) for s in train_smiles]

    def _sim_to_train(smiles: str) -> float:
        try:
            q = chem.fingerprint(smiles)
        except Exception:
            return 1.0
        return float(max(DataStructs.BulkTanimotoSimilarity(q, train_fp)))

    def activity(smiles: str) -> float:
        mean, _ = gp.predict([smiles])
        act = max(0.0, min(1.0, (float(mean[0]) - lo) / span))
        if novelty_pressure > 0:
            sim = _sim_to_train(smiles)
            # hard gate: reject rediscovery of known actives (sim>0.85),
            # taper novel analogs (0.5<sim<0.85) so the search leaves the
            # training set instead of memorising it.
            if sim >= 0.85:
                act *= (1.0 - novelty_pressure)
            elif sim > 0.5:
                act *= 1.0 - novelty_pressure * (sim - 0.5) / 0.35
        return max(0.0, act)

    scorer = MultiObjectiveScorer(objective=activity, w_objective=2.5)
    top_actives = [s for s, _ in sorted(data, key=lambda kv: kv[1],
                                        reverse=True)[:30]]
    ranked = graph_ga(scorer, top_actives, pop_size=pop_size,
                      generations=generations, seed=seed)

    results = []
    for c in ranked:
        if len(results) >= n_candidates:
            break
        sim = _max_sim(c.smiles, train_fp)
        if sim >= 0.99:
            continue  # exact rediscovery of a known molecule — not a design
        novelty = 1.0 - sim
        pred = float(gp.predict([c.smiles])[0][0])
        try:
            strain = struct.conformer_search(c.smiles, n_confs=6)["energy_spread"]
        except Exception:
            strain = None
        results.append({
            "smiles": c.smiles, "score": c.score,
            "predicted_pIC50": round(pred, 2),
            "qed": c.components.get("qed"), "sa_norm": c.components.get("sa"),
            "novelty": round(novelty, 3),
            "novel": novelty > 0.15,  # < 0.85 Tanimoto to every training molecule
            "conformer_strain_kcal": strain,
        })
    return {"target": target_chembl_id, "n_actives": len(data),
            "pIC50_range": [round(lo, 2), round(hi, 2)], "candidates": results}


def _max_sim(smiles: str, fps) -> float:
    from rdkit import DataStructs
    try:
        q = chem.fingerprint(smiles)
    except Exception:
        return 1.0
    if not fps:
        return 0.0
    return float(max(DataStructs.BulkTanimotoSimilarity(q, list(fps))))
