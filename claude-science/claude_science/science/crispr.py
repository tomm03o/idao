"""CRISPR-Cas9 guide RNA design (gene editing done from published principles).

Two scores, following the standard design workflow (Doench, Fusi et al.,
*Nat. Biotechnol.* 2016):

* **on-target** activity — how efficiently a 20 nt protospacer directs cutting,
* **off-target** risk — how likely the guide cuts an imperfectly-matched site,
  quantified by the Cutting-Frequency-Determination (CFD) principle.

Honesty about scope. The published CFD score uses a proprietary
saturating-mismatch activity table (percent activity retained per position ×
mismatch identity) and Rule Set 2 uses a gradient-boosted model. We do **not**
ship those exact fitted tables. Instead this module implements *principled
reimplementations* that reproduce their well-established qualitative behaviour:

* seed-region (PAM-proximal, positions ~11-20) mismatches are strongly
  penalising while PAM-distal mismatches are largely tolerated,
* PAM identity gates activity (NGG ≫ NAG ≫ others),
* GC content, a poly-T Pol-III terminator, and position preferences shape
  on-target efficiency.

The API and outputs match what a design pipeline expects; swap in the exact
published tables (e.g. via the `crisprScore` data) for production scoring.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional

from . import seq as _seq

_COMPLEMENT = str.maketrans("ACGT", "TGCA")


def _revcomp(dna: str) -> str:
    return dna.upper().translate(_COMPLEMENT)[::-1]


# --------------------------------------------------------------------------- #
# Guide enumeration
# --------------------------------------------------------------------------- #
@dataclass
class Guide:
    protospacer: str      # 20 nt, 5'->3', PAM-adjacent 3' end
    pam: str              # 3 nt PAM
    strand: str           # "+" or "-"
    start: int            # 0-based start on the (+) strand
    on_target: float = 0.0


def _pam_matches(triplet: str, pattern: str = "NGG") -> bool:
    if len(triplet) != len(pattern):
        return False
    for t, p in zip(triplet, pattern):
        if p == "N":
            continue
        if p != t:
            return False
    return True


def find_guides(dna: str, pam: str = "NGG", length: int = 20) -> List[Guide]:
    """Enumerate all protospacers with an ``NGG``-type PAM on both strands."""
    dna = dna.upper()
    guides: List[Guide] = []
    for strand, seqx in (("+", dna), ("-", _revcomp(dna))):
        n = len(seqx)
        for i in range(0, n - length - len(pam) + 1):
            proto = seqx[i:i + length]
            pam_seq = seqx[i + length:i + length + len(pam)]
            if set(proto) <= set("ACGT") and _pam_matches(pam_seq, pam):
                start = i if strand == "+" else n - (i + length + len(pam))
                guides.append(Guide(proto, pam_seq, strand, start))
    for g in guides:
        g.on_target = on_target_score(g.protospacer)
    return guides


# --------------------------------------------------------------------------- #
# On-target activity (Rule-Set-2-spirit heuristic)
# --------------------------------------------------------------------------- #
def on_target_score(protospacer: str) -> float:
    """Heuristic on-target efficiency in [0, 1] (documented reimplementation)."""
    g = protospacer.upper()
    if len(g) != 20 or set(g) - set("ACGT"):
        return 0.0
    gc = (g.count("G") + g.count("C")) / 20.0
    # GC sweet spot ~0.4-0.6 (Doench 2014/2016)
    gc_term = math.exp(-((gc - 0.5) ** 2) / (2 * 0.17 ** 2))
    # Pol-III terminator: a run of >=4 T kills transcription
    polyt = 0.25 if "TTTT" in g else 1.0
    # position preferences: G favoured at the PAM-proximal position 20
    pos20 = 1.08 if g[19] == "G" else (0.9 if g[19] == "C" else 1.0)
    # disfavour extreme homopolymers elsewhere
    homo = 0.8 if any(b * 5 in g for b in "ACGT") else 1.0
    score = gc_term * polyt * pos20 * homo
    return max(0.0, min(1.0, score))


# --------------------------------------------------------------------------- #
# Off-target CFD-style score
# --------------------------------------------------------------------------- #
# Per-position tolerance to a single mismatch, 5'(pos1) .. 3'(pos20, PAM-side).
# Monotonic: distal mismatches tolerated (~0.85), seed mismatches penalising
# (~0.15) — the published qualitative CFD pattern.
def _position_tolerance(pos: int) -> float:
    # pos is 1..20; PAM-proximal seed = high pos
    frac = (pos - 1) / 19.0
    return 0.9 - 0.78 / (1.0 + math.exp(-(frac - 0.62) * 9.0))


# wobble-ish mismatch identities are slightly better tolerated
_MM_FACTOR = {("G", "T"): 1.15, ("T", "G"): 1.1, ("A", "C"): 1.05,
              ("C", "A"): 1.05, ("G", "A"): 1.0, ("A", "G"): 1.0}

_PAM_ACTIVITY = {"GG": 1.0, "AG": 0.26, "GA": 0.07, "GT": 0.02, "GC": 0.02}


def cfd_off_target(guide: str, off_target: str, off_pam: str = "GG") -> float:
    """CFD-style off-target activity in [0, 1] (1 = as active as the on-target).

    ``guide`` and ``off_target`` are 20 nt; ``off_pam`` is the last 2 nt of the
    off-target PAM (the 'GG' of NGG). More mismatches — especially in the seed —
    lower the score multiplicatively.
    """
    guide, off_target = guide.upper(), off_target.upper()
    if len(guide) != 20 or len(off_target) != 20:
        raise ValueError("guide and off_target must both be 20 nt")
    score = _PAM_ACTIVITY.get(off_pam.upper(), 0.0)
    for i, (a, b) in enumerate(zip(guide, off_target), start=1):
        if a == b:
            continue
        tol = _position_tolerance(i) * _MM_FACTOR.get((a, b), 0.95)
        score *= max(0.0, min(1.0, tol))
    return round(score, 5)


# --------------------------------------------------------------------------- #
# Design report
# --------------------------------------------------------------------------- #
def design_guides(dna: str, off_target_context: Optional[List[str]] = None,
                  top_n: int = 5) -> Dict:
    """Rank guides by on-target and flag off-target risk against a context.

    ``off_target_context`` is a list of 23 nt genomic sites (20 nt + 3 nt PAM) to
    screen each guide against; the worst (highest) CFD is reported as risk.
    """
    guides = sorted(find_guides(dna), key=lambda g: g.on_target, reverse=True)
    context = off_target_context or []
    report = []
    for g in guides[:top_n]:
        worst = 0.0
        for site in context:
            site = site.upper()
            if len(site) < 23:
                continue
            off, pam = site[:20], site[21:23]
            try:
                cfd = cfd_off_target(g.protospacer, off, pam)
            except ValueError:
                continue
            worst = max(worst, cfd)
        report.append({
            "protospacer": g.protospacer, "pam": g.pam, "strand": g.strand,
            "start": g.start, "on_target": round(g.on_target, 3),
            "max_off_target_cfd": round(worst, 4),
            "specific": worst < 0.2,
        })
    return {"n_guides": len(guides), "top": report}


def _demo() -> None:  # worked examples (python -m claude_science.science.crispr)
    guide = "GTCACCTCCAATGACTAGGG"
    print("On-target of an example guide:", round(on_target_score(guide), 3))
    print("CFD, perfect match (NGG)     :", cfd_off_target(guide, guide, "GG"))
    seed_mm = guide[:19] + ("A" if guide[19] != "A" else "C")
    print("CFD, single SEED mismatch    :", cfd_off_target(guide, seed_mm, "GG"))
    distal_mm = ("A" if guide[0] != "A" else "C") + guide[1:]
    print("CFD, single DISTAL mismatch  :", cfd_off_target(guide, distal_mm, "GG"))
    print("CFD, perfect match, NAG PAM  :", cfd_off_target(guide, guide, "AG"))
    dna = "GGGACCTAGTCATTGGAGGTGACCCGGGATCGGACTGACGTGGTACCGATGCTAGCTAGG" * 2
    rep = design_guides(dna, top_n=3)
    print(f"\nfound {rep['n_guides']} guides; top by on-target:")
    for r in rep["top"]:
        print(f"  {r['protospacer']} {r['pam']} ({r['strand']}) "
              f"on-target={r['on_target']}")


if __name__ == "__main__":
    _demo()
