"""PK/PD dose-finding environment (real one-compartment model + NCA).

A one-compartment first-order oral absorption model (hidden F, ka, ke, V)
governs plasma concentration. The agent administers doses in silico, receives a
noisy concentration-time profile, may run non-compartmental analysis (real NCA
tool) to derive Cmax/AUC/half-life, and must pick a dose whose steady peak lands
on an efficacy target without crossing toxicity. Probes quantitative PK reasoning.
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np

from .base import Environment
from ..science import pk


class PKPDEnv(Environment):
    key = "pkpd"
    title = "PK/PD oral dose finding (one-compartment model + NCA)"
    capability = "quantitative-pharmacology"

    def _build(self) -> None:
        r = self.rng
        self.F = round(r.uniform(0.5, 0.95), 3)
        self.ka = round(r.uniform(0.8, 2.5), 3)
        self.ke = round(r.uniform(0.08, 0.35), 3)
        self.V = round(r.uniform(20.0, 60.0), 2)
        self.target_cmax = round(r.uniform(4.0, 12.0), 2)
        self.toxic_cmax = round(self.target_cmax * r.uniform(1.6, 2.2), 2)
        self.noise = {"low": 0.01, "medium": 0.05, "high": 0.12}.get(self.difficulty, 0.05)
        self.sample_times = [0.25, 0.5, 1, 1.5, 2, 3, 4, 6, 8, 12, 16, 24]
        self._register_domain_tools()

    def _profile(self, dose: float) -> Dict[str, List[float]]:
        t = np.array(self.sample_times, dtype=float)
        c = pk.conc_one_compartment_oral(t, dose, self.F, self.ka, self.ke, self.V)
        noise = 1.0 + self.rng.gauss(0, self.noise)
        return {"times_h": self.sample_times,
                "conc_mg_L": [round(float(x) * noise, 4) for x in c]}

    def _cmax(self, dose: float) -> float:
        prof = pk.conc_one_compartment_oral(
            np.linspace(0.05, 24, 400), dose, self.F, self.ka, self.ke, self.V)
        return float(prof.max())

    def _register_domain_tools(self) -> None:
        def simulate_dose(dose_mg: float) -> Dict[str, Any]:
            if dose_mg <= 0:
                raise ValueError("dose_mg must be > 0")
            self._record("simulate_dose", dose_mg)
            prof = self._profile(dose_mg)
            prof["dose_mg"] = dose_mg
            return prof

        def run_nca(times_h: List[float], conc_mg_L: List[float],
                    dose_mg: float) -> Dict[str, Any]:
            self._record("nca", dose_mg)
            return pk.nca(times_h, conc_mg_L, dose=dose_mg)

        self._registry.add(
            name="simulate_dose",
            description=(
                "Administer a single oral dose (mg) and return the sampled "
                "plasma concentration-time profile (noisy)."
            ),
            parameters={
                "type": "object",
                "properties": {"dose_mg": {"type": "number", "minimum": 0,
                                           "maximum": 2000}},
                "required": ["dose_mg"],
            },
            handler=simulate_dose,
        )
        self._registry.add(
            name="run_nca",
            description=(
                "Non-compartmental analysis of a concentration-time profile: "
                "returns Cmax, Tmax, AUC(last/inf), terminal half-life, CL/F, Vz/F."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "times_h": {"type": "array", "items": {"type": "number"}},
                    "conc_mg_L": {"type": "array", "items": {"type": "number"}},
                    "dose_mg": {"type": "number"},
                },
                "required": ["times_h", "conc_mg_L", "dose_mg"],
            },
            handler=run_nca,
        )

    def submit_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "dose_mg": {"type": "number", "minimum": 0, "maximum": 2000,
                            "description": "Recommended oral dose in mg."}
            },
            "required": ["dose_mg"],
        }

    def task_prompt(self) -> str:
        return (
            "Find the oral dose (mg) whose peak plasma concentration (Cmax) is as "
            f"close as possible to the efficacy target of {self.target_cmax} mg/L "
            f"while staying strictly below the toxicity threshold of "
            f"{self.toxic_cmax} mg/L. Use `simulate_dose` to obtain a "
            "concentration-time profile and `run_nca` to derive Cmax/AUC, then "
            "`submit` your dose. Cmax is linear in dose."
        )

    def score(self, payload: Dict[str, Any]) -> float:
        dose = float(payload.get("dose_mg", 0.0))
        if dose <= 0:
            return 0.0
        cmax = self._cmax(dose)
        if cmax >= self.toxic_cmax:
            return 0.0
        return self.clamp01(1.0 - abs(cmax - self.target_cmax) / self.target_cmax)

    def reference_policy(self) -> List[Dict[str, Any]]:
        probe = 100.0
        cmax = self._cmax(probe)
        required = probe * (self.target_cmax / cmax)
        return [
            {"tool": "simulate_dose", "args": {"dose_mg": probe}},
            {"tool": "submit", "args": {"dose_mg": round(required, 2)}},
        ]
