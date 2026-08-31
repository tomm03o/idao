"""Sequence RAG — retrieval by biological sequence similarity, not text.

Indexes sequences by a k-mer profile and retrieves nearest sequences by k-mer
Jaccard similarity, with an optional Smith-Waterman local-alignment rerank of the
top hits (reusing :func:`claude_science.science.seq.smith_waterman`). Right for
"find sequences similar to this one" — homology, not keywords.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set

from ..science import seq as _seq


def _kmers(sequence: str, k: int = 4) -> Set[str]:
    s = sequence.upper()
    return {s[i:i + k] for i in range(len(s) - k + 1)} if len(s) >= k else {s}


@dataclass
class _Entry:
    doc_id: str
    sequence: str
    kmers: Set[str]
    meta: Dict = field(default_factory=dict)


class SequenceRAG:
    kind = "sequence"

    def __init__(self, k: int = 4):
        self.k = k
        self._entries: List[_Entry] = []

    def add(self, doc_id: str, sequence: str, **meta) -> None:
        self._entries.append(_Entry(doc_id, sequence.upper(),
                                    _kmers(sequence, self.k), meta))

    def add_many(self, items) -> None:
        for doc_id, sequence in items:
            self.add(doc_id, sequence)

    def __len__(self) -> int:
        return len(self._entries)

    def search(self, query: str, k: int = 5, rerank: bool = True) -> List[Dict]:
        if not self._entries:
            return []
        qk = _kmers(query, self.k)
        scored = []
        for e in self._entries:
            inter = len(qk & e.kmers)
            union = len(qk | e.kmers) or 1
            scored.append((inter / union, e))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[: max(k * 3, k)]

        results = []
        for jac, e in top:
            row = {"doc_id": e.doc_id, "kmer_jaccard": round(jac, 4),
                   "length": len(e.sequence), "meta": e.meta}
            if rerank:
                aln = _seq.smith_waterman(query.upper(), e.sequence)
                row["local_align_score"] = aln["score"]
                row["identity"] = aln["identity"]
            results.append(row)
        key = "local_align_score" if rerank else "kmer_jaccard"
        results.sort(key=lambda r: r[key], reverse=True)
        return results[:k]
