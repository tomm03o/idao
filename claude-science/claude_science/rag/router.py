"""RAG router — one entry point over type-specialized retrievers.

Each data type gets the retrieval it deserves: molecules by Tanimoto, sequences
by k-mer/alignment, literature by BM25. The router dispatches by declared kind
and exposes per-type agent tools.
"""

from __future__ import annotations

from typing import Dict, List

from ..harness.tools import ToolRegistry
from .literature import LiteratureRAG
from .molecule import MoleculeRAG
from .sequence import SequenceRAG


class RAGRouter:
    def __init__(self):
        self.literature = LiteratureRAG()
        self.molecule = MoleculeRAG()
        self.sequence = SequenceRAG()
        self._by_kind = {"literature": self.literature,
                         "molecule": self.molecule,
                         "sequence": self.sequence}

    def add(self, kind: str, doc_id: str, content: str, **meta) -> str:
        rag = self._by_kind.get(kind)
        if rag is None:
            raise KeyError(f"unknown kind {kind!r}; use {list(self._by_kind)}")
        rag.add(doc_id, content, **meta)
        return f"added {doc_id} to {kind} index ({len(rag)} items)"

    def search(self, kind: str, query: str, k: int = 5) -> List[Dict]:
        rag = self._by_kind.get(kind)
        if rag is None:
            raise KeyError(f"unknown kind {kind!r}; use {list(self._by_kind)}")
        return rag.search(query, k)

    def stats(self) -> Dict[str, int]:
        return {kind: len(rag) for kind, rag in self._by_kind.items()}


def rag_tools(router: RAGRouter | None = None) -> ToolRegistry:
    """Expose the type-specialized RAGs as agent tools."""
    router = router or RAGRouter()
    reg = ToolRegistry()

    reg.add("rag_add",
            "Add a document to a type-specialized retrieval index. kind is one of "
            "'literature' (text), 'molecule' (SMILES), 'sequence' (DNA/protein).",
            {"type": "object", "properties": {
                "kind": {"type": "string", "enum": ["literature", "molecule", "sequence"]},
                "doc_id": {"type": "string"}, "content": {"type": "string"}},
             "required": ["kind", "doc_id", "content"]},
            router.add)
    reg.add("rag_literature_search",
            "Retrieve the most relevant papers/notes by BM25 (text query).",
            {"type": "object", "properties": {"query": {"type": "string"},
             "k": {"type": "integer", "minimum": 1, "maximum": 20}},
             "required": ["query"]},
            lambda query, k=5: router.literature.search(query, k))
    reg.add("rag_molecule_search",
            "Retrieve the structurally most similar molecules to a SMILES query "
            "(ECFP4 Tanimoto), not text matching.",
            {"type": "object", "properties": {"smiles": {"type": "string"},
             "k": {"type": "integer", "minimum": 1, "maximum": 20}},
             "required": ["smiles"]},
            lambda smiles, k=5: router.molecule.search(smiles, k))
    reg.add("rag_sequence_search",
            "Retrieve the most similar biological sequences to a query (k-mer + "
            "Smith-Waterman rerank).",
            {"type": "object", "properties": {"sequence": {"type": "string"},
             "k": {"type": "integer", "minimum": 1, "maximum": 20}},
             "required": ["sequence"]},
            lambda sequence, k=5: router.sequence.search(sequence, k))
    reg.add("rag_literature_ingest",
            "Fetch real biomedical abstracts from Europe PMC for a query and add "
            "them to the literature index (returns count).",
            {"type": "object", "properties": {"query": {"type": "string"},
             "limit": {"type": "integer", "minimum": 1, "maximum": 25}},
             "required": ["query"]},
            lambda query, limit=10: router.literature.ingest_europepmc(query, limit))
    reg._router = router
    return reg
