"""Dose-response assay environment (IC50 estimation).

A compound inhibits a target following a Hill curve::

    response(c) = bottom + (top - bottom) / (1 + (IC50 / c) ** hill)

The agent runs the assay at concentrations of its choosing (each measurement
is noisy and costs a call from its budget), then estimates IC50. This probes
experiment design under a budget and curve-fitting / interpolation reasoning.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

from .base import Environment


class AssayEnv(Environment):
    key = "assay"
    title = "Dose-response assay: estimate IC50"
    capability = "experiment-design"

    def _build(self) -> None:
        r = self.rng
        # IC50 sampled log-uniformly across a wide (nM) range
        self.log_ic50 = r.uniform(math.log10(5), math.log10(5000))  # nM
        self.ic50 = 10 ** self.log_ic50
        self.hill = round(r.uniform(0.8, 2.0), 2)
        self.top = round(r.uniform(95, 100), 1)      # % inhibition plateau
        self.bottom = round(r.uniform(0, 5), 1)
        self.noise = {"low": 1.5, "medium": 4.0, "high": 8.0}.get(
            self.difficulty, 4.0
        )
        self.max_reads = {"low": 12, "medium": 8, "high": 6}.get(self.difficulty, 8)
        self.reads_used = 0
        self._registry_domain_tools()

    def _response(self, conc_nM: float) -> float:
        c = max(conc_nM, 1e-9)
        return self.bottom + (self.top - self.bottom) / (
            1 + (self.ic50 / c) ** self.hill
        )

    def _registry_domain_tools(self) -> None:
        def run_assay(concentration_nM: float) -> Dict[str, Any]:
            if self.reads_used >= self.max_reads:
                raise RuntimeError(
                    f"assay budget exhausted ({self.max_reads} reads); submit now"
                )
            self.reads_used += 1
            resp = self._response(concentration_nM) + self.rng.gauss(0, self.noise)
            resp = max(0.0, min(100.0, resp))
            self._record("run_assay", {"conc_nM": concentration_nM})
            return {
                "concentration_nM": concentration_nM,
                "percent_inhibition": round(resp, 2),
                "reads_remaining": self.max_reads - self.reads_used,
            }

        self._registry.add(
            name="run_assay",
            description=(
                "Measure percent inhibition at a single compound concentration "
                "(nM). Noisy; limited number of reads available."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "concentration_nM": {
                        "type": "number",
                        "minimum": 0.01,
                        "maximum": 1_000_000,
                    }
                },
                "required": ["concentration_nM"],
            },
            handler=run_assay,
        )

    def submit_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "ic50_nM": {
                    "type": "number",
                    "minimum": 0,
                    "description": "Estimated half-maximal inhibitory conc (nM).",
                }
            },
            "required": ["ic50_nM"],
        }

    def task_prompt(self) -> str:
        return (
            "Estimate the IC50 (nM) of a compound against its target. Use "
            f"`run_assay` (max {self.max_reads} reads) to sample the dose-response "
            "curve at concentrations you choose, then `submit` your IC50 estimate. "
            "Inhibition ranges roughly 0-100%; the curve follows a Hill model. "
            "Bracket the 50% inhibition point to locate IC50 efficiently."
        )

    def score(self, payload: Dict[str, Any]) -> float:
        est = float(payload.get("ic50_nM", 0.0))
        if est <= 0:
            return 0.0
        # score on log-fold error: within 1.5x -> ~1.0, 10x off -> ~0
        fold = abs(math.log10(est / self.ic50))
        return self.clamp01(1.0 - fold / 1.0)

    def reference_policy(self) -> List[Dict[str, Any]]:
        # Log-spaced sweep bracketing the true IC50, then submit the true value
        decades = [self.ic50 / 10, self.ic50 / 3, self.ic50, self.ic50 * 3, self.ic50 * 10]
        calls = [
            {"tool": "run_assay", "args": {"concentration_nM": round(c, 3)}}
            for c in decades
        ]
        calls.append({"tool": "submit", "args": {"ic50_nM": round(self.ic50, 2)}})
        return calls
