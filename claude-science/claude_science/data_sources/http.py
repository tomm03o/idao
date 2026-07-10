"""Small cached HTTP layer shared by the database connectors.

Responses are cached on disk (keyed by URL) so repeated queries -- common in an
agent loop -- are instant and offline-reproducible. This is deliberately
dependency-free (urllib) so the connectors work anywhere the core installs.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict

CACHE_DIR = os.environ.get(
    "CLAUDE_SCIENCE_CACHE",
    os.path.join(os.path.expanduser("~"), ".cache", "claude_science"),
)
_UA = "claude-science/0.3 (research harness; +https://github.com/)"


def _cache_path(url: str) -> str:
    h = hashlib.sha256(url.encode()).hexdigest()[:24]
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, h + ".cache")


def fetch(url: str, *, timeout: int = 20, retries: int = 3,
          use_cache: bool = True) -> bytes:
    """GET a URL with on-disk caching and exponential backoff."""
    path = _cache_path(url)
    if use_cache and os.path.exists(path):
        with open(path, "rb") as fh:
            return fh.read()

    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
            if use_cache:
                with open(path, "wb") as fh:
                    fh.write(body)
            return body
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
            time.sleep(2 ** attempt)
    raise ConnectionError(f"failed to fetch {url}: {last}")


def fetch_json(url: str, **kw: Any) -> Dict[str, Any]:
    return json.loads(fetch(url, **kw).decode("utf-8", errors="replace"))


def fetch_text(url: str, **kw: Any) -> str:
    return fetch(url, **kw).decode("utf-8", errors="replace")
