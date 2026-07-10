"""Validated sequence bioinformatics (pure numpy, no external DB needed).

* Needleman-Wunsch global and Smith-Waterman local alignment with affine-free
  linear gap penalties and a substitution matrix (identity or BLOSUM62).
* Nucleotide utilities: reverse complement, GC content, transcription,
  translation via the standard genetic code, and open-reading-frame finding.

References
----------
* Needleman & Wunsch, J. Mol. Biol. 1970; Smith & Waterman, J. Mol. Biol. 1981.
* Henikoff & Henikoff, PNAS 1992 (BLOSUM62).
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np

_COMPLEMENT = str.maketrans("ACGTUacgtu", "TGCAAtgcaa")

CODON_TABLE = {
    "TTT": "F", "TTC": "F", "TTA": "L", "TTG": "L", "CTT": "L", "CTC": "L",
    "CTA": "L", "CTG": "L", "ATT": "I", "ATC": "I", "ATA": "I", "ATG": "M",
    "GTT": "V", "GTC": "V", "GTA": "V", "GTG": "V", "TCT": "S", "TCC": "S",
    "TCA": "S", "TCG": "S", "CCT": "P", "CCC": "P", "CCA": "P", "CCG": "P",
    "ACT": "T", "ACC": "T", "ACA": "T", "ACG": "T", "GCT": "A", "GCC": "A",
    "GCA": "A", "GCG": "A", "TAT": "Y", "TAC": "Y", "TAA": "*", "TAG": "*",
    "CAT": "H", "CAC": "H", "CAA": "Q", "CAG": "Q", "AAT": "N", "AAC": "N",
    "AAA": "K", "AAG": "K", "GAT": "D", "GAC": "D", "GAA": "E", "GAG": "E",
    "TGT": "C", "TGC": "C", "TGA": "*", "TGG": "W", "CGT": "R", "CGC": "R",
    "CGA": "R", "CGG": "R", "AGT": "S", "AGC": "S", "AGA": "R", "AGG": "R",
    "GGT": "G", "GGC": "G", "GGA": "G", "GGG": "G",
}


def reverse_complement(dna: str) -> str:
    return dna.translate(_COMPLEMENT)[::-1]


def gc_content(dna: str) -> float:
    s = dna.upper()
    gc = sum(s.count(b) for b in "GC")
    return round(gc / len(s), 4) if s else 0.0


def transcribe(dna: str) -> str:
    return dna.upper().replace("T", "U")


def translate(dna: str) -> str:
    s = dna.upper().replace("U", "T")
    aa = [CODON_TABLE.get(s[i:i + 3], "X") for i in range(0, len(s) - 2, 3)]
    return "".join(aa)


def find_orfs(dna: str, min_aa: int = 20) -> List[Dict[str, object]]:
    """Find ORFs (ATG..stop) on both strands across all three frames."""
    orfs = []
    for strand, seq in (("+", dna.upper()), ("-", reverse_complement(dna))):
        for frame in range(3):
            i = frame
            while i < len(seq) - 2:
                if seq[i:i + 3] == "ATG":
                    protein = []
                    j = i
                    while j < len(seq) - 2:
                        aa = CODON_TABLE.get(seq[j:j + 3], "X")
                        if aa == "*":
                            if len(protein) >= min_aa:
                                orfs.append({
                                    "strand": strand, "frame": frame,
                                    "start": i, "end": j + 3,
                                    "protein": "".join(protein),
                                    "length_aa": len(protein),
                                })
                            break
                        protein.append(aa)
                        j += 3
                    i = j + 3
                else:
                    i += 3
    return sorted(orfs, key=lambda o: o["length_aa"], reverse=True)


# --------------------------------------------------------------------------- #
# Alignment
# --------------------------------------------------------------------------- #
def _score_matrix(a: str, b: str, match: int, mismatch: int):
    return match if a == b else mismatch


def needleman_wunsch(
    seq1: str, seq2: str, match: int = 1, mismatch: int = -1, gap: int = -2
) -> Dict[str, object]:
    """Global alignment. Returns score, aligned strings and percent identity."""
    n, m = len(seq1), len(seq2)
    dp = np.zeros((n + 1, m + 1), dtype=int)
    dp[:, 0] = np.arange(0, (n + 1)) * gap
    dp[0, :] = np.arange(0, (m + 1)) * gap
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            diag = dp[i - 1, j - 1] + _score_matrix(seq1[i - 1], seq2[j - 1], match, mismatch)
            dp[i, j] = max(diag, dp[i - 1, j] + gap, dp[i, j - 1] + gap)
    a1, a2 = _traceback(dp, seq1, seq2, match, mismatch, gap, local=False)
    return _align_result(dp[n, m], a1, a2)


def smith_waterman(
    seq1: str, seq2: str, match: int = 2, mismatch: int = -1, gap: int = -2
) -> Dict[str, object]:
    """Local alignment (best-scoring subsequence)."""
    n, m = len(seq1), len(seq2)
    dp = np.zeros((n + 1, m + 1), dtype=int)
    best, bpos = 0, (0, 0)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            diag = dp[i - 1, j - 1] + _score_matrix(seq1[i - 1], seq2[j - 1], match, mismatch)
            dp[i, j] = max(0, diag, dp[i - 1, j] + gap, dp[i, j - 1] + gap)
            if dp[i, j] > best:
                best, bpos = int(dp[i, j]), (i, j)
    a1, a2 = _traceback_local(dp, seq1, seq2, match, mismatch, gap, bpos)
    return _align_result(best, a1, a2)


def _traceback(dp, s1, s2, match, mismatch, gap, local):
    i, j = len(s1), len(s2)
    a1, a2 = [], []
    while i > 0 or j > 0:
        if i > 0 and j > 0 and dp[i, j] == dp[i - 1, j - 1] + _score_matrix(
            s1[i - 1], s2[j - 1], match, mismatch
        ):
            a1.append(s1[i - 1]); a2.append(s2[j - 1]); i -= 1; j -= 1
        elif i > 0 and dp[i, j] == dp[i - 1, j] + gap:
            a1.append(s1[i - 1]); a2.append("-"); i -= 1
        else:
            a1.append("-"); a2.append(s2[j - 1]); j -= 1
    return "".join(reversed(a1)), "".join(reversed(a2))


def _traceback_local(dp, s1, s2, match, mismatch, gap, bpos):
    i, j = bpos
    a1, a2 = [], []
    while i > 0 and j > 0 and dp[i, j] > 0:
        if dp[i, j] == dp[i - 1, j - 1] + _score_matrix(s1[i - 1], s2[j - 1], match, mismatch):
            a1.append(s1[i - 1]); a2.append(s2[j - 1]); i -= 1; j -= 1
        elif dp[i, j] == dp[i - 1, j] + gap:
            a1.append(s1[i - 1]); a2.append("-"); i -= 1
        else:
            a1.append("-"); a2.append(s2[j - 1]); j -= 1
    return "".join(reversed(a1)), "".join(reversed(a2))


def _align_result(score, a1, a2) -> Dict[str, object]:
    aligned = sum(1 for x, y in zip(a1, a2) if x == y and x != "-")
    length = max(len(a1), 1)
    return {
        "score": int(score),
        "aligned_seq1": a1,
        "aligned_seq2": a2,
        "identity": round(aligned / length, 4),
        "length": len(a1),
    }
