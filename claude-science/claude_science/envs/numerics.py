"""Numerical-computing environments — the platform beyond biology.

These prove the harness generalises to *any* computational-research domain: the
same Environment contract (hidden ground truth + tool oracles + verifiable
scorer + expert reference policy) now covers applied mathematics. Each probes a
distinct numerical-methods capability an agent must execute deliberately:

* ``rootfind``   — locate a root of a hidden function from an evaluation oracle
* ``optimize``   — minimise a hidden 1-D function under a query budget
* ``quadrature`` — estimate a definite integral from point samples
* ``eigenvalue`` — recover a matrix's dominant eigenvalue from a matvec oracle

All are backed by numpy, deterministic per seed, and each ships the classical
algorithm (bisection, golden-section, Simpson, power iteration) as its expert
reference policy.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

import numpy as np

from .base import Environment


# --------------------------------------------------------------------------- #
class RootFindEnv(Environment):
    key = "rootfind"
    title = "Root finding: locate a zero of a hidden function"
    capability = "numerical-root-finding"
    domain = "numerics"

    def _build(self) -> None:
        r = self.rng
        self.lo, self.hi = -5.0, 5.0
        self.root = round(r.uniform(-3.5, 3.5), 4)
        self.p = round(r.uniform(0.5, 3.0), 3)      # x^2+p > 0 → unique real root
        self.scale = round(r.uniform(0.5, 2.0), 3)
        self.calls = 0
        self.budget = {"low": 40, "medium": 25, "high": 15}.get(self.difficulty, 25)

        def f(x):
            return self.scale * (x - self.root) * (x * x + self.p)

        self._f = f

        def evaluate(x: float) -> Dict[str, Any]:
            if self.calls >= self.budget:
                raise RuntimeError(f"evaluation budget exhausted ({self.budget})")
            self.calls += 1
            self._record("evaluate", x)
            return {"x": x, "f_x": round(self._f(x), 6),
                    "evaluations_left": self.budget - self.calls}

        self._registry.add(
            "evaluate", "Evaluate the hidden function f at x. f is continuous "
            "with a single real root in [-5, 5].",
            {"type": "object", "properties": {"x": {"type": "number",
             "minimum": -5, "maximum": 5}}, "required": ["x"]}, evaluate)

    def submit_schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {"root": {"type": "number",
                "description": "Your estimate of the root x* where f(x*)=0."}},
                "required": ["root"]}

    def task_prompt(self) -> str:
        return ("Find the root x* in [-5, 5] of a hidden continuous function f "
                "(one real root). Use `evaluate` to sample f at points you "
                f"choose (budget {self.budget}); exploit sign changes "
                "(bisection). Then `submit` your root estimate.")

    def score(self, payload: Dict[str, Any]) -> float:
        x = payload.get("root")
        if x is None:
            return 0.0
        return self.clamp01(1.0 - abs(float(x) - self.root) / 0.5)  # 1 within ~0.5

    def reference_policy(self) -> List[Dict[str, Any]]:
        lo, hi = self.lo, self.hi
        calls = []
        for _ in range(30):
            mid = (lo + hi) / 2
            calls.append({"tool": "evaluate", "args": {"x": round(mid, 5)}})
            if self._f(lo) * self._f(mid) <= 0:
                hi = mid
            else:
                lo = mid
            if hi - lo < 1e-4:
                break
        calls.append({"tool": "submit", "args": {"root": round((lo + hi) / 2, 5)}})
        return calls


# --------------------------------------------------------------------------- #
class OptimizeEnv(Environment):
    key = "optimize"
    title = "1-D minimisation of a hidden unimodal function"
    capability = "numerical-optimization"
    domain = "numerics"

    def _build(self) -> None:
        r = self.rng
        self.lo, self.hi = 0.0, 10.0
        self.xmin = round(r.uniform(1.5, 8.5), 4)
        self.curv = round(r.uniform(0.5, 2.5), 3)
        self.offset = round(r.uniform(-2, 2), 3)
        self.calls = 0
        self.budget = {"low": 30, "medium": 20, "high": 12}.get(self.difficulty, 20)

        def f(x):
            return self.curv * (x - self.xmin) ** 2 + self.offset

        self._f = f

        def evaluate(x: float) -> Dict[str, Any]:
            if self.calls >= self.budget:
                raise RuntimeError(f"evaluation budget exhausted ({self.budget})")
            self.calls += 1
            self._record("evaluate", x)
            return {"x": x, "f_x": round(self._f(x), 6),
                    "evaluations_left": self.budget - self.calls}

        self._registry.add(
            "evaluate", "Evaluate the hidden unimodal (single-minimum) function "
            "f at x in [0, 10].",
            {"type": "object", "properties": {"x": {"type": "number",
             "minimum": 0, "maximum": 10}}, "required": ["x"]}, evaluate)

    def submit_schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {"x_min": {"type": "number",
                "description": "Location of the minimum."}}, "required": ["x_min"]}

    def task_prompt(self) -> str:
        return ("Find the minimiser x* of a hidden unimodal function f on "
                f"[0, 10] using `evaluate` (budget {self.budget}). A "
                "golden-section / ternary search is efficient. Then `submit` x_min.")

    def score(self, payload: Dict[str, Any]) -> float:
        x = payload.get("x_min")
        if x is None:
            return 0.0
        return self.clamp01(1.0 - abs(float(x) - self.xmin) / 0.5)

    def reference_policy(self) -> List[Dict[str, Any]]:
        gr = (math.sqrt(5) - 1) / 2
        a, b = self.lo, self.hi
        c, d = b - gr * (b - a), a + gr * (b - a)
        calls = []
        for _ in range(25):
            calls.append({"tool": "evaluate", "args": {"x": round(c, 5)}})
            calls.append({"tool": "evaluate", "args": {"x": round(d, 5)}})
            if self._f(c) < self._f(d):
                b = d
            else:
                a = c
            c, d = b - gr * (b - a), a + gr * (b - a)
            if b - a < 1e-4:
                break
        calls.append({"tool": "submit", "args": {"x_min": round((a + b) / 2, 5)}})
        return calls


# --------------------------------------------------------------------------- #
class QuadratureEnv(Environment):
    key = "quadrature"
    title = "Numerical integration of a hidden function under a sample budget"
    capability = "numerical-integration"
    domain = "numerics"

    def _build(self) -> None:
        r = self.rng
        self.a, self.b = 0.0, round(r.uniform(2.0, 6.0), 3)
        self.c1 = round(r.uniform(0.5, 2.0), 3)
        self.c2 = round(r.uniform(0.3, 1.5), 3)
        self.w = round(r.uniform(0.5, 2.0), 3)
        self.calls = 0
        self.budget = {"low": 25, "medium": 15, "high": 9}.get(self.difficulty, 15)

        def f(x):
            return self.c1 * math.sin(self.w * x) + self.c2 * x

        self._f = f
        # analytic integral: -c1/w cos(wx) + c2 x^2/2
        F = lambda x: -self.c1 / self.w * math.cos(self.w * x) + self.c2 * x * x / 2
        self.true_integral = F(self.b) - F(self.a)

        def sample(x: float) -> Dict[str, Any]:
            if self.calls >= self.budget:
                raise RuntimeError(f"sample budget exhausted ({self.budget})")
            self.calls += 1
            self._record("sample", x)
            return {"x": x, "f_x": round(self._f(x), 6),
                    "samples_left": self.budget - self.calls}

        self._registry.add(
            "sample", f"Evaluate the hidden integrand f at x in [{self.a}, "
            f"{self.b}] (budget {self.budget}).",
            {"type": "object", "properties": {"x": {"type": "number"}},
             "required": ["x"]}, sample)

    def submit_schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {"integral": {"type": "number",
                "description": f"Estimate of ∫f dx over [{self.a}, {self.b}]."}},
                "required": ["integral"]}

    def task_prompt(self) -> str:
        return (f"Estimate the definite integral of a hidden smooth function f "
                f"over [{self.a}, {self.b}]. Sample f at up to {self.budget} "
                "points (use an evenly spaced grid + Simpson's rule) via "
                "`sample`, then `submit` the integral.")

    def score(self, payload: Dict[str, Any]) -> float:
        est = payload.get("integral")
        if est is None:
            return 0.0
        denom = abs(self.true_integral) or 1.0
        return self.clamp01(1.0 - abs(float(est) - self.true_integral) / denom / 0.1)

    def reference_policy(self) -> List[Dict[str, Any]]:
        n = min(self.budget - 1, 12)
        if n % 2 == 1:
            n -= 1
        xs = np.linspace(self.a, self.b, n + 1)
        calls = [{"tool": "sample", "args": {"x": round(float(x), 5)}} for x in xs]
        ys = [self._f(float(x)) for x in xs]
        h = (self.b - self.a) / n
        simp = ys[0] + ys[-1] + 4 * sum(ys[1:-1:2]) + 2 * sum(ys[2:-1:2])
        est = h / 3 * simp
        calls.append({"tool": "submit", "args": {"integral": round(est, 5)}})
        return calls


# --------------------------------------------------------------------------- #
class EigenvalueEnv(Environment):
    key = "eigenvalue"
    title = "Dominant eigenvalue from a matrix-vector-product oracle"
    capability = "numerical-linear-algebra"
    domain = "numerics"

    def _build(self) -> None:
        r = self.rng
        self.n = {"low": 4, "medium": 6, "high": 8}.get(self.difficulty, 6)
        rng = np.random.default_rng(self.seed)
        Q, _ = np.linalg.qr(rng.standard_normal((self.n, self.n)))
        eigs = np.sort(rng.uniform(1.0, 10.0, self.n))
        eigs[-1] *= 1.5  # ensure a clear dominant eigenvalue (power iteration)
        self.A = Q @ np.diag(eigs) @ Q.T
        self.dominant = float(np.max(np.abs(np.linalg.eigvalsh(self.A))))
        self.calls = 0
        self.budget = {"low": 40, "medium": 30, "high": 20}.get(self.difficulty, 30)

        def matvec(vector: List[float]) -> Dict[str, Any]:
            if self.calls >= self.budget:
                raise RuntimeError(f"matvec budget exhausted ({self.budget})")
            v = np.asarray(vector, dtype=float)
            if v.shape != (self.n,):
                raise ValueError(f"vector must have length {self.n}")
            self.calls += 1
            self._record("matvec", None)
            return {"result": [round(float(z), 6) for z in (self.A @ v)],
                    "calls_left": self.budget - self.calls}

        self._registry.add(
            "matvec", f"Return the matrix-vector product A·v for a hidden "
            f"symmetric {self.n}×{self.n} matrix A. Provide v as a length-"
            f"{self.n} list.",
            {"type": "object", "properties": {"vector": {"type": "array",
             "items": {"type": "number"}}}, "required": ["vector"]}, matvec)

    def submit_schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {"eigenvalue": {"type": "number",
                "description": "Dominant (largest-magnitude) eigenvalue of A."}},
                "required": ["eigenvalue"]}

    def task_prompt(self) -> str:
        return (f"A hidden symmetric {self.n}×{self.n} matrix A is accessible "
                "only through the `matvec` oracle (returns A·v). Recover its "
                "dominant eigenvalue by power iteration: repeatedly multiply, "
                "normalise, and track the Rayleigh quotient. Then `submit` it. "
                f"Budget {self.budget} matvecs.")

    def score(self, payload: Dict[str, Any]) -> float:
        est = payload.get("eigenvalue")
        if est is None:
            return 0.0
        return self.clamp01(1.0 - abs(abs(float(est)) - self.dominant)
                            / self.dominant / 0.05)

    def reference_policy(self) -> List[Dict[str, Any]]:
        v = np.ones(self.n) / math.sqrt(self.n)
        calls = []
        lam = 0.0
        for _ in range(min(self.budget - 1, 25)):
            calls.append({"tool": "matvec", "args": {"vector": [round(float(z), 6)
                          for z in v]}})
            Av = self.A @ v
            lam = float(v @ Av)
            nrm = np.linalg.norm(Av)
            if nrm < 1e-12:
                break
            v = Av / nrm
        calls.append({"tool": "submit", "args": {"eigenvalue": round(abs(lam), 5)}})
        return calls
