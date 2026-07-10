"""Virtual screening environment (real ECFP4 similarity).

Given a query molecule and a compound library, the agent must return the top-k
most similar drug-like hits -- the core of ligand-based virtual screening. The
similarity metric is genuine Morgan/ECFP4 Tanimoto (RDKit); the score is the
overlap of the agent's picks with the true top-k.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .base import Environment
from .data import DRUGS
from ..science import chem


class ScreenEnv(Environment):
    key = "screen"
    title = "Ligand-based virtual screening (ECFP4 Tanimoto)"
    capability = "virtual-screening"

    def _build(self) -> None:
        r = self.rng
        self.top_k = {"low": 2, "medium": 3, "high": 3}.get(self.difficulty, 3)
        names = [n for n, _ in DRUGS]
        self.query_name = r.choice(names)
        self.query = dict(DRUGS)[self.query_name]
        # library = everything except the query itself
        self.library = [smi for n, smi in DRUGS if n != self.query_name]
        ranked = chem.similarity_search(self.query, self.library, top_k=len(self.library))
        self.true_top = [chem.canonical_smiles(h["smiles"]) for h in ranked[: self.top_k]]
        self._register_domain_tools()

    def _register_domain_tools(self) -> None:
        def tanimoto(smiles_a: str, smiles_b: str) -> float:
            self._record("tanimoto", (smiles_a, smiles_b))
            return chem.tanimoto(smiles_a, smiles_b)

        def screen_library(top_k: int = 5) -> List[Dict[str, Any]]:
            self._record("screen", top_k)
            return chem.similarity_search(self.query, self.library, top_k=top_k)

        self._registry.add(
            name="tanimoto_similarity",
            description="ECFP4 Tanimoto similarity between two SMILES (0-1).",
            parameters={
                "type": "object",
                "properties": {
                    "smiles_a": {"type": "string"},
                    "smiles_b": {"type": "string"},
                },
                "required": ["smiles_a", "smiles_b"],
            },
            handler=tanimoto,
        )
        self._registry.add(
            name="screen_library",
            description=(
                "Rank the whole library by ECFP4 Tanimoto similarity to the "
                "query and return the top_k hits."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 25}
                },
                "required": [],
            },
            handler=screen_library,
        )

    def submit_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "hits": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": f"SMILES of your top-{self.top_k} most similar hits.",
                }
            },
            "required": ["hits"],
        }

    def task_prompt(self) -> str:
        lib = "\n".join(f"  - {s}" for s in self.library)
        return (
            f"Query molecule: {self.query}\n\n"
            f"From the library below, return the {self.top_k} compounds most "
            "similar to the query by ECFP4 Tanimoto similarity. Use "
            "`tanimoto_similarity` or `screen_library`, then `submit` the list "
            f"of {self.top_k} SMILES.\n\nLibrary:\n{lib}"
        )

    def score(self, payload: Dict[str, Any]) -> float:
        hits = payload.get("hits", []) or []
        picked = set()
        for h in hits[: self.top_k]:
            try:
                picked.add(chem.canonical_smiles(h))
            except Exception:
                continue
        correct = len(picked & set(self.true_top))
        return self.clamp01(correct / self.top_k)

    def reference_policy(self) -> List[Dict[str, Any]]:
        return [
            {"tool": "screen_library", "args": {"top_k": self.top_k}},
            {"tool": "submit", "args": {"hits": self.true_top}},
        ]
