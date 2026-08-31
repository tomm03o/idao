"""Molecular design environment (verifiable de novo design).

A hidden objective (drug-likeness × similarity to a hidden reference pharmacophore)
acts as a black-box assay. The agent proposes candidate molecules, reads back their
score, and must submit a molecule that maximises the objective — genuine
goal-directed design under a black-box, exactly like optimising against a hidden
QSAR/assay. Scored by the real multi-objective function (RDKit).
"""

from __future__ import annotations

from typing import Any, Dict, List

from .base import Environment
from .data import DRUGS
from ..research.molecular_design import MultiObjectiveScorer
from ..science import chem


class DesignEnv(Environment):
    key = "design"
    title = "De novo molecular design against a hidden objective"
    capability = "molecular-design"
    domain = "life-sciences"

    def _build(self) -> None:
        r = self.rng
        self.ref_name, self.ref_smiles = r.choice(DRUGS)
        self.scorer = MultiObjectiveScorer(
            objective=lambda s: chem.tanimoto(self.ref_smiles, s))
        self.budget = {"low": 20, "medium": 12, "high": 8}.get(self.difficulty, 12)
        self.tests_used = 0
        self.best_seen = 0.0
        self._register_domain_tools()

    def _register_domain_tools(self) -> None:
        def test_molecule(smiles: str) -> Dict[str, Any]:
            if self.tests_used >= self.budget:
                raise RuntimeError(f"assay budget exhausted ({self.budget})")
            try:
                chem.parse(smiles)
            except Exception as exc:
                return {"error": f"invalid SMILES: {exc}"}
            self.tests_used += 1
            score = self.scorer(smiles)
            self.best_seen = max(self.best_seen, score)
            comp = {}
            try:
                comp = {k: round(v, 3) for k, v in self.scorer.components(smiles).items()}
            except Exception:
                pass
            return {"smiles": smiles, "objective_score": round(score, 4),
                    "components": comp, "tests_left": self.budget - self.tests_used}

        self._registry.add(
            "test_molecule",
            "Assay a candidate molecule against the hidden objective; returns a "
            "score in [0,1] (higher is better) and its QED / SA / objective "
            "components. Budget-limited.",
            {"type": "object", "properties": {"smiles": {"type": "string"}},
             "required": ["smiles"]},
            test_molecule)

    def submit_schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {"smiles": {"type": "string",
                "description": "SMILES of your best designed molecule."}},
                "required": ["smiles"]}

    def task_prompt(self) -> str:
        return (
            "Design a drug-like molecule that maximises a hidden objective (a "
            "black-box assay combining drug-likeness with similarity to an unknown "
            "reference pharmacophore). Use `test_molecule` to score candidates "
            f"(budget {self.budget}) — start from known drug scaffolds, read the "
            "component breakdown, and iterate toward higher scores. Then `submit` "
            "your best molecule. The score is 0 for non-drug-like molecules "
            "(Lipinski / reactive alerts).")

    def score(self, payload: Dict[str, Any]) -> float:
        smi = payload.get("smiles", "")
        try:
            chem.parse(smi)
        except Exception:
            return 0.0
        return self.clamp01(self.scorer(smi))

    def reference_policy(self) -> List[Dict[str, Any]]:
        # an expert seeds from known drugs and submits the reference scaffold,
        # which maximises the similarity component while staying drug-like
        probes = [s for _, s in self.rng.sample(DRUGS, min(3, self.budget))]
        calls = [{"tool": "test_molecule", "args": {"smiles": s}} for s in probes]
        calls.append({"tool": "submit", "args": {"smiles": self.ref_smiles}})
        return calls
