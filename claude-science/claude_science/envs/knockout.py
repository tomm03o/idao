"""Gene-knockout target-identification environment.

A small feed-forward gene regulatory network produces a disease marker. The
agent can knock out one gene at a time (a CRISPR-style intervention) and read
the resulting marker level. Because the network propagates, a knockout's effect
is not obvious from the wiring alone -- the agent must intervene and observe.
Goal: identify the single knockout that most reduces the disease marker. This
probes causal intervention reasoning and search under a budget.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .base import Environment


class KnockoutEnv(Environment):
    key = "knockout"
    title = "Gene knockout: find the best therapeutic target"
    capability = "causal-intervention"

    def _build(self) -> None:
        r = self.rng
        self.n = {"low": 5, "medium": 7, "high": 9}.get(self.difficulty, 7)
        self.genes = [f"G{i}" for i in range(self.n)]
        self.base = {g: round(r.uniform(0.4, 1.0), 3) for g in self.genes}
        # feed-forward weights: gene i may regulate gene j>i
        self.W: Dict[str, Dict[str, float]] = {g: {} for g in self.genes}
        for i in range(self.n):
            for j in range(i + 1, self.n):
                if r.random() < 0.45:
                    self.W[self.genes[i]][self.genes[j]] = round(
                        r.uniform(-0.8, 0.9), 3
                    )
        self.marker_w = {g: round(r.uniform(-0.5, 1.0), 3) for g in self.genes}
        self.noise = {"low": 0.01, "medium": 0.04, "high": 0.10}.get(
            self.difficulty, 0.04
        )
        self.baseline_marker = self._marker(set())
        self._effects = {g: self._marker({g}) for g in self.genes}
        self.best_gene = min(self._effects, key=self._effects.get)
        self.best_marker = self._effects[self.best_gene]
        self._registry_domain_tools()

    def _express(self, knocked: set[str]) -> Dict[str, float]:
        expr: Dict[str, float] = {}
        for g in self.genes:  # topological order G0..Gn
            if g in knocked:
                expr[g] = 0.0
                continue
            val = self.base[g]
            for src in self.genes:
                if src in knocked:
                    continue
                w = self.W[src].get(g)
                if w:
                    val += w * expr.get(src, 0.0)
            expr[g] = max(0.0, val)
        return expr

    def _marker(self, knocked: set[str]) -> float:
        expr = self._express(knocked)
        return round(sum(self.marker_w[g] * expr[g] for g in self.genes), 4)

    def _registry_domain_tools(self) -> None:
        def knockout(gene: str) -> Dict[str, Any]:
            if gene not in self.base:
                raise ValueError(f"unknown gene {gene!r}; choose from {self.genes}")
            marker = self._marker({gene}) + self.rng.gauss(0, self.noise)
            self._record("knockout", {"gene": gene})
            return {
                "gene": gene,
                "disease_marker": round(marker, 4),
                "baseline_marker": self.baseline_marker,
                "delta": round(marker - self.baseline_marker, 4),
            }

        self._registry.add(
            name="knockout",
            description=(
                "Knock out a single gene and measure the resulting disease "
                "marker level (lower is better). Baseline marker is provided for "
                "reference. Noisy read-out."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "gene": {"type": "string", "enum": self.genes}
                },
                "required": ["gene"],
            },
            handler=knockout,
        )

    def submit_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "gene": {
                    "type": "string",
                    "enum": self.genes,
                    "description": "The gene whose knockout best lowers the marker.",
                }
            },
            "required": ["gene"],
        }

    def task_prompt(self) -> str:
        return (
            "A gene regulatory network drives a disease marker. Identify the "
            "single gene knockout that most reduces the marker (lower is better). "
            f"Genes: {', '.join(self.genes)}. Baseline marker = "
            f"{self.baseline_marker}. Use `knockout` to test interventions, then "
            "`submit` the best target gene. Effects propagate through the network, "
            "so test empirically rather than guessing from names."
        )

    def score(self, payload: Dict[str, Any]) -> float:
        gene = payload.get("gene")
        if gene not in self._effects:
            return 0.0
        chosen = self._effects[gene]
        span = self.baseline_marker - self.best_marker
        if span <= 1e-9:
            return 1.0 if gene == self.best_gene else 0.5
        return self.clamp01((self.baseline_marker - chosen) / span)

    def reference_policy(self) -> List[Dict[str, Any]]:
        calls = [{"tool": "knockout", "args": {"gene": g}} for g in self.genes]
        calls.append({"tool": "submit", "args": {"gene": self.best_gene}})
        return calls
