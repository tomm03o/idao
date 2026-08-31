"""Training-free reliability layer: verifier-guided test-time compute.

No gradient updates — pure test-time scaling. Given a *verifiable* reward (the
environment's own scorer, or an ``rl.judges`` judge), sampling several rollouts
and keeping the best measurably raises the pass rate. This is the standard,
defensible way to turn a weak model into a reliable one when correctness is
checkable (RLVR-style selection; AVA-style anytime budget).

* :class:`VerifiedBestOfN` — sample up to N rollouts of a base agent on fresh
  copies of the task, score each with the verifiable reward, keep the best.
  Anytime: stop early as soon as a rollout verifies (reward ≥ ``target``), so
  easy tasks cost one sample and only hard tasks spend the full budget.

Wraps any agent and any environment through the same ``run(env) -> Transcript``
contract, so it composes with ``ScientistAgent`` and the leaderboard
(spec ``verified:<n>:<agent-spec>``).
"""

from __future__ import annotations

from typing import Any, List

from .agent import Agent
from .transcript import Transcript


class VerifiedBestOfN(Agent):
    def __init__(self, base: Agent, n: int = 5, target: float = 0.999,
                 sample_temperature: float = 0.7):
        self.base = base
        self.n = max(1, int(n))
        self.target = target
        # best-of-N only helps if rollouts differ; raise a deterministic
        # backend's temperature so the N samples explore different solutions.
        if getattr(base, "temperature", None) == 0.0:
            base.temperature = sample_temperature
        self.max_steps = getattr(base, "max_steps", 12)
        self.name = f"verified{self.n}:{base.name}"

    def run(self, env: Any) -> Transcript:
        from ..envs import make_env

        key = getattr(env, "key", None)
        seed = getattr(env, "seed", 0)
        difficulty = getattr(env, "difficulty", "medium")

        best_score = -1.0
        best_tr: Transcript | None = None
        best_payload = None
        samples = 0

        for _ in range(self.n):
            # fresh, identical copy of the task per sample
            e = make_env(key, seed=seed, difficulty=difficulty) if key else env
            tr = self.base.run(e)
            samples += 1
            sub = e.result()
            score = sub.score if sub and sub.score is not None else 0.0
            if score > best_score:
                best_score, best_tr = score, tr
                best_payload = sub.payload if sub else None
            if score >= self.target:      # anytime: verified, stop early
                break

        # replay the best submission onto the caller's environment so the
        # benchmark scores the selected rollout
        if best_payload is not None and not env.is_done():
            try:
                env.tools().dispatch("submit", best_payload)
            except Exception:
                pass

        tr = best_tr or Transcript(getattr(env, "task_id", "task"), self.name)
        tr.agent = self.name
        tr.log("message", f"verified best-of-{self.n}: selected reward "
                          f"{best_score:.3f} after {samples} sample(s)")
        return tr
