"""Structural computational resources for agents.

LLMs are weak at exact arithmetic, lose long-horizon state, and self-verify
inconsistently. This module hands them *external* structures that offload those
failure modes — cognition tools that raise reliability without any retraining:

* :class:`Blackboard` — a persistent, typed working memory (hypotheses /
  observations / candidates / decisions) the agent reads and writes across
  steps, so a long episode does not lose state.
* :class:`Critic` — deterministic self-verification: run a real check from the
  science layer against the agent's claim before it commits (e.g. "does this
  SMILES actually pass Lipinski and have no structural alerts?").
* ``calc`` — a safe exact-arithmetic evaluator (no LLM mental math).

Exposed as agent tools via :func:`cognition_tools`, and mergeable into the lab
bench.
"""

from __future__ import annotations

import ast
import math
import operator
from typing import Any, Dict, List

from .tools import ToolRegistry


# --------------------------------------------------------------------------- #
# Working memory
# --------------------------------------------------------------------------- #
class Blackboard:
    SLOTS = ("hypotheses", "observations", "candidates", "decisions", "notes")

    def __init__(self):
        self._mem: Dict[str, List[str]] = {s: [] for s in self.SLOTS}

    def write(self, slot: str, content: str) -> str:
        if slot not in self._mem:
            raise ValueError(f"unknown slot {slot!r}; use {list(self.SLOTS)}")
        self._mem[slot].append(content)
        return f"wrote to {slot} (now {len(self._mem[slot])} entries)"

    def read(self, slot: str) -> List[str]:
        if slot not in self._mem:
            raise ValueError(f"unknown slot {slot!r}; use {list(self.SLOTS)}")
        return list(self._mem[slot])

    def dump(self) -> Dict[str, List[str]]:
        return {s: list(v) for s, v in self._mem.items() if v}


# --------------------------------------------------------------------------- #
# Critic (deterministic self-verification)
# --------------------------------------------------------------------------- #
class Critic:
    @staticmethod
    def verify_druglike(smiles: str) -> Dict[str, Any]:
        from ..science import chem
        try:
            lip = chem.lipinski(smiles)
            alerts = chem.structural_alerts(smiles)
        except Exception as exc:
            return {"ok": False, "reason": f"invalid SMILES: {exc}"}
        ok = lip["pass"] and not alerts
        return {"ok": ok, "lipinski_pass": lip["pass"],
                "lipinski_violations": lip["violations"],
                "structural_alerts": alerts,
                "verdict": "drug-like" if ok else "NOT drug-like"}

    @staticmethod
    def verify_claim(claim: str, value: float, operator_str: str,
                     threshold: float) -> Dict[str, Any]:
        ops = {"<": operator.lt, "<=": operator.le, ">": operator.gt,
               ">=": operator.ge, "==": operator.eq}
        fn = ops.get(operator_str)
        if fn is None:
            return {"ok": False, "reason": f"bad operator {operator_str!r}"}
        holds = bool(fn(value, threshold))
        return {"ok": holds, "claim": claim,
                "checked": f"{value} {operator_str} {threshold}", "holds": holds}


# --------------------------------------------------------------------------- #
# Exact calculator (safe eval)
# --------------------------------------------------------------------------- #
_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
        ast.FloorDiv: operator.floordiv}
_UN = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {k: getattr(math, k) for k in
          ("sqrt", "log", "log10", "log2", "exp", "sin", "cos", "tan", "pi",
           "e", "floor", "ceil", "fabs")}


def _safe_eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        return _BIN[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UN:
        return _UN[type(node.op)](_safe_eval(node.operand))
    if isinstance(node, ast.Name) and node.id in _FUNCS:
        return _FUNCS[node.id]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        fn = _FUNCS.get(node.func.id)
        if fn is None:
            raise ValueError(f"function not allowed: {node.func.id}")
        return fn(*[_safe_eval(a) for a in node.args])
    raise ValueError("unsupported expression")


def calc(expression: str) -> Dict[str, Any]:
    """Evaluate an arithmetic expression exactly (offloads LLM mental math)."""
    try:
        val = _safe_eval(ast.parse(expression, mode="eval"))
        return {"expression": expression, "result": val}
    except Exception as exc:
        return {"expression": expression, "error": str(exc)}


# --------------------------------------------------------------------------- #
def cognition_tools(blackboard: Blackboard | None = None) -> ToolRegistry:
    bb = blackboard or Blackboard()
    reg = ToolRegistry()
    reg.add("memory_write",
            "Write a note to your structured working memory. slot is one of "
            "hypotheses / observations / candidates / decisions / notes.",
            {"type": "object", "properties": {
                "slot": {"type": "string",
                         "enum": list(Blackboard.SLOTS)},
                "content": {"type": "string"}}, "required": ["slot", "content"]},
            bb.write)
    reg.add("memory_read",
            "Read back everything written to a working-memory slot.",
            {"type": "object", "properties": {
                "slot": {"type": "string", "enum": list(Blackboard.SLOTS)}},
             "required": ["slot"]},
            bb.read)
    reg.add("critic_verify_druglike",
            "Deterministically verify whether a molecule is drug-like (Lipinski + "
            "no structural alerts) BEFORE you commit to it.",
            {"type": "object", "properties": {"smiles": {"type": "string"}},
             "required": ["smiles"]},
            Critic.verify_druglike)
    reg.add("calc",
            "Evaluate an arithmetic expression exactly (+, -, *, /, **, sqrt, log, "
            "exp, ...). Use instead of doing math yourself.",
            {"type": "object", "properties": {"expression": {"type": "string"}},
             "required": ["expression"]},
            calc)
    reg._blackboard = bb
    return reg
