"""Internet access for agents: literature search + generic web fetch.

* ``literature_search`` — Europe PMC REST (covers PubMed/MEDLINE, preprints).
  Public, no key; returns title, authors, journal, year, abstract snippet, IDs.
* ``web_fetch`` — retrieve a URL as text (cached, capped) for the agent to read.

Both are real network calls (independent of any LLM provider quota).
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any, Dict, List

from .http import fetch_json, fetch_text

_EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_TAG = re.compile(r"<[^>]+>")


def literature_search(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Search the biomedical literature via Europe PMC."""
    q = urllib.parse.quote(query)
    url = f"{_EPMC}?query={q}&format=json&pageSize={limit}&resultType=core"
    data = fetch_json(url)
    out = []
    for r in data.get("resultList", {}).get("result", [])[:limit]:
        abstract = _TAG.sub("", r.get("abstractText", "") or "")
        out.append({
            "id": r.get("id"),
            "source": r.get("source"),
            "title": r.get("title"),
            "authors": r.get("authorString"),
            "journal": (r.get("journalInfo", {}) or {}).get("journal", {}).get("title"),
            "year": r.get("pubYear"),
            "doi": r.get("doi"),
            "citations": r.get("citedByCount"),
            "abstract": abstract[:600],
        })
    return out


def web_fetch(url: str, max_chars: int = 4000) -> Dict[str, Any]:
    """Fetch a URL and return de-tagged text (capped)."""
    if not url.startswith(("http://", "https://")):
        raise ValueError("url must start with http:// or https://")
    raw = fetch_text(url)
    text = _TAG.sub(" ", raw)
    text = re.sub(r"\s+", " ", text).strip()
    return {"url": url, "chars": len(text), "text": text[:max_chars]}


def web_tools():
    """Expose internet access as agent tools."""
    from ..harness.tools import ToolRegistry
    reg = ToolRegistry()
    reg.add("literature_search",
            "Search the biomedical literature (Europe PMC / PubMed): titles, "
            "abstracts, authors, DOIs.",
            {"type": "object", "properties": {"query": {"type": "string"},
             "limit": {"type": "integer", "minimum": 1, "maximum": 20}},
             "required": ["query"]},
            lambda query, limit=5: literature_search(query, limit))
    reg.add("web_fetch",
            "Fetch a web page and return its text content (capped).",
            {"type": "object", "properties": {"url": {"type": "string"},
             "max_chars": {"type": "integer"}}, "required": ["url"]},
            lambda url, max_chars=4000: web_fetch(url, max_chars))
    return reg
