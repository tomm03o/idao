"""Type-specialized RAG suite.

Each retriever is *ad hoc for its data type* — molecules by ECFP4/Tanimoto,
sequences by k-mer/alignment, literature by BM25 — behind one router.

    from claude_science.rag import RAGRouter, rag_tools
    r = RAGRouter()
    r.add("molecule", "aspirin", "CC(=O)Oc1ccccc1C(=O)O")
    r.search("molecule", "OC(=O)c1ccccc1O")   # Tanimoto-nearest
"""

from .literature import LiteratureRAG
from .molecule import MoleculeRAG
from .sequence import SequenceRAG
from .router import RAGRouter, rag_tools

__all__ = ["LiteratureRAG", "MoleculeRAG", "SequenceRAG", "RAGRouter", "rag_tools"]
