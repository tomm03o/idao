"""Lead-optimisation / docking environment.

A candidate ligand is described by interpretable physicochemical descriptors.
A hidden binding pocket has an optimal descriptor profile; predicted affinity
(pKd) is highest when the ligand complements it. But affinity is not the only
objective: the molecule must remain drug-like (Lipinski's rule of five). The
agent proposes ligands, reads back predicted pKd, and submits its best
drug-like candidate. This probes multi-objective optimisation under constraints.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

from .base import Environment

DESCRIPTORS = ["mw", "logp", "hbd", "hba", "tpsa", "rot_bonds"]


class DockingEnv(Environment):
    key = "docking"
    title = "Ligand lead optimisation (binding vs drug-likeness)"
    capability = "multi-objective-optimization"

    def _build(self) -> None:
        r = self.rng
        # hidden pocket-optimal profile and per-descriptor tolerance
        self.optimum = {
            "mw": r.uniform(300, 460),
            "logp": r.uniform(1.5, 3.8),
            "hbd": r.uniform(1, 3),
            "hba": r.uniform(3, 7),
            "tpsa": r.uniform(60, 110),
            "rot_bonds": r.uniform(3, 7),
        }
        self.width = {
            "mw": 120, "logp": 2.0, "hbd": 2.0,
            "hba": 3.0, "tpsa": 45, "rot_bonds": 3.0,
        }
        self.noise = {"low": 0.05, "medium": 0.15, "high": 0.35}.get(
            self.difficulty, 0.15
        )
        self.best_pkd = self._pkd(self.optimum)
        self._registry_domain_tools()

    def _pkd(self, lig: Dict[str, float]) -> float:
        # gaussian complementarity across descriptors -> pKd in ~[4, 11]
        s = 0.0
        for d in DESCRIPTORS:
            z = (float(lig.get(d, 0)) - self.optimum[d]) / self.width[d]
            s += math.exp(-0.5 * z * z)
        return 4.0 + 7.0 * (s / len(DESCRIPTORS))

    @staticmethod
    def lipinski_violations(lig: Dict[str, float]) -> List[str]:
        v = []
        if lig.get("mw", 0) > 500:
            v.append("MW>500")
        if lig.get("logp", 0) > 5:
            v.append("logP>5")
        if lig.get("hbd", 0) > 5:
            v.append("HBD>5")
        if lig.get("hba", 0) > 10:
            v.append("HBA>10")
        return v

    def _registry_domain_tools(self) -> None:
        def dock(mw: float, logp: float, hbd: float, hba: float,
                 tpsa: float, rot_bonds: float) -> Dict[str, Any]:
            lig = dict(mw=mw, logp=logp, hbd=hbd, hba=hba,
                       tpsa=tpsa, rot_bonds=rot_bonds)
            pkd = self._pkd(lig) + self.rng.gauss(0, self.noise)
            self._record("dock", lig)
            return {
                "predicted_pKd": round(pkd, 3),
                "lipinski_violations": self.lipinski_violations(lig),
                "drug_like": not self.lipinski_violations(lig),
            }

        self._registry.add(
            name="dock",
            description=(
                "Score a candidate ligand against the target pocket. Returns "
                "predicted binding affinity (pKd; higher is tighter) and any "
                "Lipinski rule-of-five violations."
            ),
            parameters={
                "type": "object",
                "properties": {d: {"type": "number"} for d in DESCRIPTORS},
                "required": DESCRIPTORS,
            },
            handler=dock,
        )

    def submit_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {d: {"type": "number"} for d in DESCRIPTORS},
            "required": DESCRIPTORS,
        }

    def task_prompt(self) -> str:
        return (
            "Optimise a small-molecule ligand for a target pocket. Use `dock` to "
            "evaluate candidate descriptor sets (mw, logp, hbd, hba, tpsa, "
            "rot_bonds) and maximise predicted binding affinity (pKd) while "
            "keeping the molecule drug-like (no Lipinski violations). Then "
            "`submit` your best drug-like candidate. Iterate: adjust one "
            "descriptor at a time to learn the response surface."
        )

    def score(self, payload: Dict[str, Any]) -> float:
        lig = {d: float(payload.get(d, 0)) for d in DESCRIPTORS}
        if self.lipinski_violations(lig):
            return 0.0
        pkd = self._pkd(lig)
        # normalise against achievable range [4, best]
        return self.clamp01((pkd - 4.0) / (self.best_pkd - 4.0))

    def reference_policy(self) -> List[Dict[str, Any]]:
        opt = {d: round(self.optimum[d], 2) for d in DESCRIPTORS}
        return [
            {"tool": "dock", "args": opt},
            {"tool": "submit", "args": opt},
        ]
