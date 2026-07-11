"""Lightweight retrieval (RAG) over a document corpus — pure Python BM25.

No external index or embedding service: an agent can ingest documents (pasted
text, fetched web pages, database records, its own notes) and query them by
relevance. BM25 is the standard sparse-retrieval baseline and needs no model,
so it runs anywhere and is fully deterministic/verifiable.

    from claude_science.retrieval import Corpus
    c = Corpus()
    c.add("doc1", "Imatinib inhibits BCR-ABL tyrosine kinase ...")
    c.search("kinase inhibitor", k=3)
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from .harness.tools import ToolRegistry

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> List[str]:
    return _TOKEN.findall(text.lower())


@dataclass
class Document:
    doc_id: str
    text: str
    tokens: List[str] = field(default_factory=list)
    meta: Dict = field(default_factory=dict)


class Corpus:
    """A BM25-ranked document store."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs: List[Document] = []
        self._df: Counter = Counter()
        self._avgdl: float = 0.0

    def add(self, doc_id: str, text: str, **meta) -> None:
        toks = _tokenize(text)
        self.docs.append(Document(doc_id, text, toks, meta))
        for t in set(toks):
            self._df[t] += 1
        self._avgdl = sum(len(d.tokens) for d in self.docs) / len(self.docs)

    def add_many(self, items: List[Tuple[str, str]]) -> None:
        for doc_id, text in items:
            self.add(doc_id, text)

    def __len__(self) -> int:
        return len(self.docs)

    def _idf(self, term: str) -> float:
        n, df = len(self.docs), self._df.get(term, 0)
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def search(self, query: str, k: int = 5) -> List[Dict]:
        if not self.docs:
            return []
        q = _tokenize(query)
        scored = []
        for d in self.docs:
            tf = Counter(d.tokens)
            dl = len(d.tokens) or 1
            s = 0.0
            for term in q:
                if term not in tf:
                    continue
                idf = self._idf(term)
                num = tf[term] * (self.k1 + 1)
                den = tf[term] + self.k1 * (1 - self.b + self.b * dl / (self._avgdl or 1))
                s += idf * num / den
            if s > 0:
                scored.append((s, d))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {"doc_id": d.doc_id, "score": round(s, 4),
             "snippet": d.text[:280], "meta": d.meta}
            for s, d in scored[:k]
        ]


def retrieval_tools(corpus: Corpus | None = None) -> ToolRegistry:
    """Expose a Corpus as agent tools: rag_add and rag_search."""
    corpus = corpus or Corpus()
    reg = ToolRegistry()
    reg.add("rag_add",
            "Add a document to the retrieval corpus for later search.",
            {"type": "object", "properties": {"doc_id": {"type": "string"},
             "text": {"type": "string"}}, "required": ["doc_id", "text"]},
            lambda doc_id, text: (corpus.add(doc_id, text),
                                  f"added {doc_id} ({len(corpus)} docs)")[1])
    reg.add("rag_search",
            "Retrieve the most relevant documents from the corpus (BM25).",
            {"type": "object", "properties": {"query": {"type": "string"},
             "k": {"type": "integer", "minimum": 1, "maximum": 20}},
             "required": ["query"]},
            lambda query, k=5: corpus.search(query, k))
    reg._corpus = corpus
    return reg
