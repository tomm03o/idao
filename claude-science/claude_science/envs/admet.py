"""ADMET triage environment (real cheminformatics).

The agent is handed a set of real candidate molecules (SMILES) and must pick
the best oral development candidate: drug-like (Lipinski + Veber), free of
reactive structural alerts, with the best overall quality (QED) at acceptable
synthetic accessibility. All chemistry is computed by RDKit -- no surrogate.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .base import Environment
from .data import DRUGS, DECOYS
from ..science import chem


class ADMETEnv(Environment):
    key = "admet"
    title = "ADMET candidate triage (RDKit drug-likeness)"
    capability = "cheminformatics"

    def _build(self) -> None:
        r = self.rng
        n_decoy = {"low": 2, "medium": 2, "high": 3}.get(self.difficulty, 2)
        n_drug = {"low": 4, "medium": 5, "high": 6}.get(self.difficulty, 5)
        pool = r.sample(DRUGS, n_drug) + r.sample(DECOYS, n_decoy)
        r.shuffle(pool)
        self.candidates = [smi for _, smi in pool]
        self._quality = {smi: self._composite(smi) for smi in self.candidates}
        self.best_smiles = max(self._quality, key=self._quality.get)
        self.best_quality = self._quality[self.best_smiles]
        self._register_domain_tools()

    def _composite(self, smiles: str) -> float:
        """Development-candidate quality in [0,1]; disqualify on hard failures."""
        d = chem.descriptors(smiles)
        if not d["lipinski_pass"] or not d["veber_pass"]:
            return 0.0
        if chem.structural_alerts(smiles):
            return 0.0
        # QED already blends the key properties; lightly penalise hard synthesis
        sa_penalty = max(0.0, (d["sa_score"] - 6.0) / 4.0)  # SA>6 starts to hurt
        return max(0.0, d["qed"] - sa_penalty)

    def _register_domain_tools(self) -> None:
        def analyze_molecule(smiles: str) -> Dict[str, Any]:
            self._record("analyze", smiles)
            d = chem.descriptors(smiles)
            d["structural_alerts"] = chem.structural_alerts(smiles)
            return d

        self._registry.add(
            name="analyze_molecule",
            description=(
                "Compute the full physicochemical / drug-likeness profile of a "
                "SMILES: MW, cLogP, TPSA, HBD/HBA, rotatable bonds, QED, SA "
                "score, Lipinski & Veber pass/fail, and reactive structural "
                "alerts (RDKit)."
            ),
            parameters={
                "type": "object",
                "properties": {"smiles": {"type": "string"}},
                "required": ["smiles"],
            },
            handler=analyze_molecule,
        )

    def submit_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "smiles": {
                    "type": "string",
                    "description": "SMILES of the chosen best candidate.",
                }
            },
            "required": ["smiles"],
        }

    def task_prompt(self) -> str:
        listing = "\n".join(f"  - {s}" for s in self.candidates)
        return (
            "Select the single best oral drug-development candidate from this "
            "set. A candidate must be drug-like (Lipinski and Veber) and free of "
            "reactive structural alerts; among those, prefer the highest overall "
            "quality (QED) at reasonable synthetic accessibility. Use "
            "`analyze_molecule` on each, then `submit` the winning SMILES.\n\n"
            f"Candidates:\n{listing}"
        )

    def score(self, payload: Dict[str, Any]) -> float:
        smi = payload.get("smiles", "")
        try:
            smi_canon = chem.canonical_smiles(smi)
        except Exception:
            return 0.0
        lut = {chem.canonical_smiles(s): self._quality[s] for s in self.candidates}
        if smi_canon not in lut:
            return 0.0  # must choose from the provided set
        if self.best_quality <= 1e-9:
            return 1.0
        return self.clamp01(lut[smi_canon] / self.best_quality)

    def reference_policy(self) -> List[Dict[str, Any]]:
        calls = [
            {"tool": "analyze_molecule", "args": {"smiles": s}}
            for s in self.candidates
        ]
        calls.append({"tool": "submit", "args": {"smiles": self.best_smiles}})
        return calls
