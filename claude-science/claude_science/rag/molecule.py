"""Molecule RAG — retrieval by chemical similarity, not text.

Indexes molecules by ECFP4 fingerprint and retrieves the nearest structures to a
SMILES query by Tanimoto. This is the right retrieval for chemistry: "find me
molecules like this one" is a structural question, not a keyword one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from rdkit import DataStructs

from ..science import chem


@dataclass
class _Entry:
    doc_id: str
    smiles: str
    fp: object
    meta: Dict = field(default_factory=dict)


class MoleculeRAG:
    kind = "molecule"

    def __init__(self):
        self._entries: List[_Entry] = []

    def add(self, doc_id: str, smiles: str, **meta) -> None:
        canon = chem.canonical_smiles(smiles)   # raises on invalid
        self._entries.append(_Entry(doc_id, canon, chem.fingerprint(canon), meta))

    def add_many(self, items) -> None:
        for doc_id, smiles in items:
            try:
                self.add(doc_id, smiles)
            except Exception:
                continue

    def __len__(self) -> int:
        return len(self._entries)

    def search(self, query_smiles: str, k: int = 5) -> List[Dict]:
        if not self._entries:
            return []
        q = chem.fingerprint(query_smiles)
        sims = DataStructs.BulkTanimotoSimilarity(q, [e.fp for e in self._entries])
        ranked = sorted(zip(sims, self._entries), key=lambda x: x[0], reverse=True)
        return [{"doc_id": e.doc_id, "smiles": e.smiles,
                 "tanimoto": round(float(s), 4), "meta": e.meta}
                for s, e in ranked[:k]]
