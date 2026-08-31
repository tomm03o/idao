"""Dose-response / potency environment (real 4PL fitting).

A compound inhibits a target following a Hill curve. The agent runs a limited
number of noisy assay measurements at concentrations it chooses, then fits a
four-parameter logistic model (real scipy nonlinear least squares, exposed as a
tool) to estimate IC50. Probes experiment design under a budget + curve fitting.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

from .base import Environment
from ..science import pk


class IC50Env(Environment):
    key = "ic50"
    title = "Dose-response IC50 estimation (4-parameter logistic fit)"
    capability = "pharmacology-assay"

    def _build(self) -> None:
        r = self.rng
        self.log_ic50 = r.uniform(math.log10(5), math.log10(5000))  # nM
        self.ic50 = 10 ** self.log_ic50
        self.hill = round(r.uniform(0.8, 1.8), 2)
        self.top = round(r.uniform(95, 100), 1)
        self.bottom = round(r.uniform(0, 5), 1)
        self.noise = {"low": 1.5, "medium": 4.0, "high": 8.0}.get(self.difficulty, 4.0)
        self.max_reads = {"low": 12, "medium": 10, "high": 8}.get(self.difficulty, 10)
        self.reads_used = 0
        self._register_domain_tools()

    def _true_response(self, conc: float) -> float:
        return float(pk.four_pl(conc, self.bottom, self.top, self.ic50, self.hill))

    def _register_domain_tools(self) -> None:
        def run_assay(concentration_nM: float) -> Dict[str, Any]:
            if self.reads_used >= self.max_reads:
                raise RuntimeError(f"assay budget exhausted ({self.max_reads}); submit")
            self.reads_used += 1
            resp = self._true_response(concentration_nM) + self.rng.gauss(0, self.noise)
            self._record("run_assay", concentration_nM)
            return {
                "concentration_nM": concentration_nM,
                "percent_inhibition": round(max(0.0, min(100.0, resp)), 2),
                "reads_remaining": self.max_reads - self.reads_used,
            }

        def fit_curve(concentrations_nM: List[float],
                      responses: List[float]) -> Dict[str, Any]:
            self._record("fit", len(concentrations_nM))
            return pk.fit_dose_response(concentrations_nM, responses)

        self._registry.add(
            name="run_assay",
            description=(
                "Measure percent inhibition at one concentration (nM). Noisy; "
                "limited number of reads."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "concentration_nM": {"type": "number", "minimum": 0.01,
                                         "maximum": 1_000_000}
                },
                "required": ["concentration_nM"],
            },
            handler=run_assay,
        )
        self._registry.add(
            name="fit_curve",
            description=(
                "Fit a 4-parameter logistic (Hill) model to your collected "
                "(concentration, response) pairs and return IC50 with standard "
                "error, Hill slope and R^2. Needs >= 4 points."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "concentrations_nM": {"type": "array", "items": {"type": "number"}},
                    "responses": {"type": "array", "items": {"type": "number"}},
                },
                "required": ["concentrations_nM", "responses"],
            },
            handler=fit_curve,
        )

    def submit_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "ic50_nM": {"type": "number", "minimum": 0,
                            "description": "Estimated IC50 in nM."}
            },
            "required": ["ic50_nM"],
        }

    def task_prompt(self) -> str:
        return (
            "Estimate the IC50 (nM) of a compound against its target. Use "
            f"`run_assay` (max {self.max_reads} reads) to sample the dose-response "
            "curve at concentrations you choose -- bracket the 50% inhibition "
            "point across several log-spaced doses -- then `fit_curve` on your "
            "data and `submit` the IC50. Inhibition ranges ~0-100% (Hill model)."
        )

    def score(self, payload: Dict[str, Any]) -> float:
        est = float(payload.get("ic50_nM", 0.0))
        if est <= 0:
            return 0.0
        fold = abs(math.log10(est / self.ic50))
        return self.clamp01(1.0 - fold)  # within ~1.25x -> ~0.9; 10x off -> 0

    def reference_policy(self) -> List[Dict[str, Any]]:
        decades = [self.ic50 / 10, self.ic50 / 3, self.ic50,
                   self.ic50 * 3, self.ic50 * 10, self.ic50 * 30]
        calls = [{"tool": "run_assay", "args": {"concentration_nM": round(c, 3)}}
                 for c in decades]
        calls.append({"tool": "submit", "args": {"ic50_nM": round(self.ic50, 2)}})
        return calls
