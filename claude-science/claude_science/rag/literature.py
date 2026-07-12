"""Literature RAG — BM25 retrieval over text, with Europe PMC ingestion.

Wraps the validated BM25 :class:`claude_science.retrieval.Corpus` (the right
retrieval for prose) and can auto-ingest real biomedical abstracts from Europe
PMC so an agent's literature searches return cited, real sources.
"""

from __future__ import annotations

from typing import Dict, List

from ..retrieval import Corpus


class LiteratureRAG:
    kind = "literature"

    def __init__(self):
        self.corpus = Corpus()

    def add(self, doc_id: str, text: str, **meta) -> None:
        self.corpus.add(doc_id, text, **meta)

    def add_many(self, items) -> None:
        self.corpus.add_many(items)

    def __len__(self) -> int:
        return len(self.corpus)

    def search(self, query: str, k: int = 5) -> List[Dict]:
        return self.corpus.search(query, k)

    def ingest_europepmc(self, query: str, limit: int = 10) -> int:
        """Fetch real abstracts from Europe PMC and add them (returns count)."""
        from ..data_sources import web
        hits = web.literature_search(query, limit=limit)
        n = 0
        for h in hits:
            text = f"{h.get('title', '')}. {h.get('abstract', '') or ''}".strip()
            if not text:
                continue
            doc_id = h.get("id") or h.get("doi") or f"epmc-{n}"
            self.add(doc_id, text, source=h.get("source"),
                     title=h.get("title"), year=h.get("year"),
                     authors=h.get("authors"))
            n += 1
        return n
