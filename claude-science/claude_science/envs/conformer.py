"""Conformational analysis environment (real MMFF94 force field).

The agent must find the lowest-energy 3D conformer of a flexible molecule. It
can embed and minimise individual conformers (real ETKDG + MMFF94, seeded) or
run a multi-start search. Because conformer generation is stochastic in the
starting seed, finding the global minimum requires deliberate sampling. Probes
computational-chemistry reasoning and search.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .base import Environment
from ..science import struct

# flexible, MMFF-parameterisable molecules (rotatable bonds make the search real)
_MOLECULES = {
    "low": ["CCCCCC(=O)O", "OCCCCO", "CCCCCCN"],
    "medium": ["CCCCCCCC(=O)O", "OCCOCCOCCO", "c1ccccc1CCCCC(=O)O"],
    "high": ["CCCCCCCCCCC(=O)O", "O=C(O)CCCCCCCCN", "c1ccc(cc1)OCCCCCCC(=O)O"],
}


class ConformerEnv(Environment):
    key = "conformer"
    title = "Conformer search: find the global-minimum MMFF94 energy"
    capability = "computational-chemistry"

    def _build(self) -> None:
        r = self.rng
        pool = _MOLECULES.get(self.difficulty, _MOLECULES["medium"])
        self.smiles = r.choice(pool)
        # ground-truth global minimum from a large reference search
        ref = struct.conformer_search(self.smiles, n_confs=60)
        self.global_min = ref["energy_min"]
        self.tolerance = {"low": 1.0, "medium": 2.0, "high": 3.0}.get(
            self.difficulty, 2.0
        )
        self._register_domain_tools()

    def _register_domain_tools(self) -> None:
        def minimize(seed: int = 0) -> Dict[str, Any]:
            self._record("minimize", seed)
            return struct.mmff_energy(self.smiles, seed=seed, minimize=True)

        def search(n_conformers: int = 20) -> Dict[str, Any]:
            self._record("search", n_conformers)
            return struct.conformer_search(self.smiles, n_confs=n_conformers)

        self._registry.add(
            name="embed_and_minimize",
            description=(
                "Generate one 3D conformer from a random seed and MMFF94-minimise "
                "it; returns the minimised energy (kcal/mol). Different seeds find "
                "different local minima."
            ),
            parameters={
                "type": "object",
                "properties": {"seed": {"type": "integer", "minimum": 0,
                                        "maximum": 100000}},
                "required": [],
            },
            handler=minimize,
        )
        self._registry.add(
            name="conformer_search",
            description=(
                "Run a multi-start ETKDG + MMFF94 conformer search and return the "
                "min/max/spread of minimised energies."
            ),
            parameters={
                "type": "object",
                "properties": {"n_conformers": {"type": "integer", "minimum": 1,
                                                "maximum": 100}},
                "required": [],
            },
            handler=search,
        )

    def submit_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "energy_kcal_mol": {
                    "type": "number",
                    "description": "Lowest MMFF94 conformer energy you found.",
                }
            },
            "required": ["energy_kcal_mol"],
        }

    def task_prompt(self) -> str:
        return (
            f"Find the global-minimum MMFF94 conformer energy (kcal/mol) of this "
            f"molecule: {self.smiles}\n\nUse `embed_and_minimize` with several "
            "different seeds and/or `conformer_search`, then `submit` the lowest "
            f"energy you found. You must get within {self.tolerance} kcal/mol of "
            "the true global minimum."
        )

    def score(self, payload: Dict[str, Any]) -> float:
        e = payload.get("energy_kcal_mol")
        if e is None:
            return 0.0
        gap = float(e) - self.global_min
        if gap < -0.5:
            return 0.0  # below reference => not a real minimised conformer
        return self.clamp01(1.0 - max(0.0, gap) / (self.tolerance * 2))

    def reference_policy(self) -> List[Dict[str, Any]]:
        return [
            {"tool": "conformer_search", "args": {"n_conformers": 40}},
            {"tool": "submit", "args": {"energy_kcal_mol": self.global_min}},
        ]
