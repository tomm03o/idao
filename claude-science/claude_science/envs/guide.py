"""CRISPR guide-selection environment (verifiable gene-editing design).

Given a target DNA locus, the agent must select the sgRNA protospacer with the
highest on-target efficiency. It can list candidate PAM sites and score guides
(budget-limited), then submit its choice — scored against the true best guide.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List

from .base import Environment
from ..science import crispr


class GuideEnv(Environment):
    key = "guide"
    title = "CRISPR sgRNA selection: pick the highest-efficiency guide"
    capability = "gene-editing"
    domain = "life-sciences"

    def _build(self) -> None:
        r = self.rng
        self.dna = self._random_locus(r)
        self.guides = crispr.find_guides(self.dna)
        # ensure a solvable instance
        while len(self.guides) < 4:
            self.dna = self._random_locus(r)
            self.guides = crispr.find_guides(self.dna)
        self.best = max(self.guides, key=lambda g: g.on_target)
        self.best_score = self.best.on_target
        self.valid = {g.protospacer for g in self.guides}
        self.budget = {"low": 40, "medium": 25, "high": 15}.get(self.difficulty, 25)
        self.scored = 0
        self._register_domain_tools()

    @staticmethod
    def _random_locus(r: random.Random) -> str:
        # random DNA with several GG dinucleotides to yield NGG PAMs
        bases = "ACGT"
        chunks = []
        for _ in range(12):
            chunks.append("".join(r.choice(bases) for _ in range(r.randint(6, 12))))
            chunks.append("GG")  # seed PAMs
        return "".join(chunks)

    def _register_domain_tools(self) -> None:
        def list_pam_sites() -> List[Dict[str, Any]]:
            self._record("list", None)
            return [{"protospacer": g.protospacer, "pam": g.pam,
                     "strand": g.strand, "start": g.start} for g in self.guides]

        def score_guide(protospacer: str) -> Dict[str, Any]:
            if self.scored >= self.budget:
                raise RuntimeError(f"scoring budget exhausted ({self.budget})")
            self.scored += 1
            valid = protospacer.upper() in self.valid
            return {"protospacer": protospacer.upper(),
                    "valid_site_in_target": valid,
                    "on_target_score": round(crispr.on_target_score(protospacer), 4),
                    "scores_left": self.budget - self.scored}

        self._registry.add(
            "list_pam_sites",
            "List all candidate sgRNA protospacers (20 nt) with an NGG PAM in the "
            "target locus, on both strands.",
            {"type": "object", "properties": {}, "required": []}, list_pam_sites)
        self._registry.add(
            "score_guide",
            "Return the on-target efficiency (0-1) of a protospacer and whether it "
            "is a valid PAM site in the target. Budget-limited.",
            {"type": "object", "properties": {"protospacer": {"type": "string"}},
             "required": ["protospacer"]}, score_guide)

    def submit_schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {"protospacer": {"type": "string",
                "description": "The chosen 20 nt sgRNA protospacer."}},
                "required": ["protospacer"]}

    def task_prompt(self) -> str:
        return (
            "Select the best CRISPR-Cas9 sgRNA for this target locus: the 20 nt "
            "protospacer (immediately 5' of an NGG PAM) with the HIGHEST on-target "
            "efficiency. Use `list_pam_sites` to enumerate candidates and "
            f"`score_guide` to rank them (budget {self.budget}), then `submit` the "
            f"best protospacer. It must be a real PAM site in the target.\n\n"
            f"Target locus:\n{self.dna}")

    def score(self, payload: Dict[str, Any]) -> float:
        proto = str(payload.get("protospacer", "")).upper()
        if proto not in self.valid:
            return 0.0
        if self.best_score <= 0:
            return 1.0
        return self.clamp01(crispr.on_target_score(proto) / self.best_score)

    def reference_policy(self) -> List[Dict[str, Any]]:
        calls = [{"tool": "list_pam_sites", "args": {}}]
        for g in sorted(self.guides, key=lambda x: x.on_target,
                        reverse=True)[:min(5, self.budget)]:
            calls.append({"tool": "score_guide", "args": {"protospacer": g.protospacer}})
        calls.append({"tool": "submit", "args": {"protospacer": self.best.protospacer}})
        return calls
