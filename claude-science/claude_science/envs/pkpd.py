"""PK/PD dose-finding environment.

A one-compartment model with first-order oral absorption governs plasma
concentration::

    C(t) = F*Dose*ka / (V*(ka-ke)) * (exp(-ke*t) - exp(-ka*t))

The agent cannot see F, ka, ke, V. It must run simulated dose administrations
(noisy Cmax / AUC read-outs) and pick a dose whose peak concentration lands in
the therapeutic window and near the efficacy target, without crossing the
toxicity threshold. This probes experiment design + quantitative extrapolation.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

from .base import Environment


class PKPDEnv(Environment):
    key = "pkpd"
    title = "PK/PD oral dose finding (one-compartment model)"
    capability = "quantitative-pharmacology"

    def _build(self) -> None:
        r = self.rng
        self.F = round(r.uniform(0.5, 0.95), 3)          # bioavailability
        self.ka = round(r.uniform(0.8, 2.5), 3)          # 1/h absorption
        self.ke = round(r.uniform(0.08, 0.35), 3)        # 1/h elimination
        self.V = round(r.uniform(20.0, 60.0), 2)         # L volume of distribution
        self.target_cmax = round(r.uniform(4.0, 12.0), 2)  # mg/L efficacy target
        self.toxic_cmax = round(self.target_cmax * r.uniform(1.6, 2.2), 2)
        self.noise = {"low": 0.01, "medium": 0.05, "high": 0.12}.get(
            self.difficulty, 0.05
        )
        self._registry_domain_tools()

    def _cmax_auc(self, dose: float) -> tuple[float, float]:
        ka, ke, V, F = self.ka, self.ke, self.V, self.F
        tmax = math.log(ka / ke) / (ka - ke)
        cmax = (F * dose * ka) / (V * (ka - ke)) * (
            math.exp(-ke * tmax) - math.exp(-ka * tmax)
        )
        auc = (F * dose) / (V * ke)
        return cmax, auc

    def _registry_domain_tools(self) -> None:
        def simulate_dose(dose_mg: float) -> Dict[str, Any]:
            if dose_mg <= 0:
                raise ValueError("dose_mg must be > 0")
            cmax, auc = self._cmax_auc(dose_mg)
            n = 1.0 + self.rng.gauss(0, self.noise)
            self._record("simulate_dose", {"dose_mg": dose_mg})
            return {
                "dose_mg": dose_mg,
                "cmax_mg_L": round(cmax * n, 3),
                "auc_mg_h_L": round(auc * n, 3),
                "tmax_h": round(math.log(self.ka / self.ke) / (self.ka - self.ke), 3),
                "note": "read-outs include assay noise",
            }

        self._registry.add(
            name="simulate_dose",
            description=(
                "Administer a single oral dose (mg) in silico and measure peak "
                "plasma concentration (Cmax), area-under-curve (AUC) and time to "
                "peak. Read-outs are noisy."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "dose_mg": {"type": "number", "minimum": 0, "maximum": 2000}
                },
                "required": ["dose_mg"],
            },
            handler=simulate_dose,
        )

    def submit_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "dose_mg": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 2000,
                    "description": "Recommended oral dose in mg.",
                }
            },
            "required": ["dose_mg"],
        }

    def task_prompt(self) -> str:
        return (
            "Find the oral dose (mg) that produces a peak plasma concentration "
            f"(Cmax) as close as possible to the efficacy target of "
            f"{self.target_cmax} mg/L, while staying strictly below the toxicity "
            f"threshold of {self.toxic_cmax} mg/L. Use `simulate_dose` to probe, "
            "then `submit` your recommended dose_mg. Doses have an (unknown) "
            "linear relationship to Cmax."
        )

    def score(self, payload: Dict[str, Any]) -> float:
        dose = float(payload.get("dose_mg", 0.0))
        if dose <= 0:
            return 0.0
        cmax, _ = self._cmax_auc(dose)
        if cmax >= self.toxic_cmax:
            return 0.0  # toxic => task failed regardless of efficacy
        rel_err = abs(cmax - self.target_cmax) / self.target_cmax
        return self.clamp01(1.0 - rel_err)

    def reference_policy(self) -> List[Dict[str, Any]]:
        probe = 100.0
        cmax, _ = self._cmax_auc(probe)
        required = probe * (self.target_cmax / cmax)
        return [
            {"tool": "simulate_dose", "args": {"dose_mg": probe}},
            {"tool": "submit", "args": {"dose_mg": round(required, 2)}},
        ]
