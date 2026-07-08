"""
cache.py

Two independent in-memory caches used by the LLM backend module:

1. ArtifactCache
   Keeps already-loaded ML/explainability artifacts (predictions, SHAP
   explanations, important nodes/edges, feature categories, graph JSON) in
   memory for the lifetime of the backend process, so CSV/JSON files are not
   re-read from disk on every node click or request.

2. ExecutiveSummaryCache
   Temporarily stores the LLM-generated initial-analysis text ("Executive
   Summary") for a specific (session_id, transaction_id) pair, so the PDF
   report can reuse it without calling Azure OpenAI a second time. Entries
   expire after a TTL (default 30 minutes) since a summary should not be
   reused indefinitely across unrelated sessions.

Both caches are plain in-memory dicts guarded by a lock -- no external
dependency (e.g. cachetools, redis) is introduced, keeping this module
consistent with the rest of the backend.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple


# ---------------------------------------------------------------------------
# 1. Artifact cache (process-lifetime, no expiration)
# ---------------------------------------------------------------------------

class ArtifactCache:
    """
    Generic get-or-load cache for offline artifacts (predictions, SHAP
    explanations, important nodes/edges, feature categories, graph JSON).

    Entries live for the lifetime of the backend process. There is no size
    limit or eviction policy -- the artifacts involved are small, finite,
    pre-computed files, not unbounded request data.
    """

    def __init__(self) -> None:
        self._store: Dict[str, Any] = {}
        self._lock = threading.RLock()

    def get_or_load(self, key: str, loader_fn: Callable[[], Any]) -> Any:
        """Return the cached value for `key`, computing and storing it via
        `loader_fn()` on first access only."""
        with self._lock:
            if key not in self._store:
                self._store[key] = loader_fn()
            return self._store[key]

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            return self._store.get(key)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._store[key] = value

    def contains(self, key: str) -> bool:
        with self._lock:
            return key in self._store

    def clear(self) -> None:
        """Clear all cached artifacts. Used by tests and hot-reloading."""
        with self._lock:
            self._store.clear()


# ---------------------------------------------------------------------------
# 2. Executive Summary cache (TTL-based)
# ---------------------------------------------------------------------------

DEFAULT_EXECUTIVE_SUMMARY_TTL_SECONDS = 30 * 60  # 30 minutes


class ExecutiveSummaryCache:
    """
    Session + transaction scoped cache for LLM-generated Executive Summaries
    (the initial_analysis explanation reused by the PDF report).

    Entries expire after `ttl_seconds`. This is intentionally short-lived:
    a summary is only valid for the duration of an investigator's active
    session, not indefinitely, since underlying artifacts could change
    between sessions (e.g. re-run offline pipeline).
    """

    def __init__(self, ttl_seconds: int = DEFAULT_EXECUTIVE_SUMMARY_TTL_SECONDS) -> None:
        self.ttl_seconds = ttl_seconds
        # key -> (stored_at_epoch_seconds, text)
        self._store: Dict[Tuple[str, str], Tuple[float, str]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _make_key(session_id: str, transaction_id: str) -> Tuple[str, str]:
        return (str(session_id), str(transaction_id))

    def get(self, session_id: str, transaction_id: str) -> Optional[str]:
        """Return the cached Executive Summary text, or None if missing or
        expired. Expired entries are evicted on read."""
        key = self._make_key(session_id, transaction_id)
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            stored_at, text = entry
            if time.time() - stored_at > self.ttl_seconds:
                del self._store[key]
                return None
            return text

    def set(self, session_id: str, transaction_id: str, text: str) -> None:
        key = self._make_key(session_id, transaction_id)
        with self._lock:
            self._store[key] = (time.time(), text)

    def clear(self) -> None:
        """Clear all cached summaries. Used by tests."""
        with self._lock:
            self._store.clear()


# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------
# A single shared instance of each cache is used across the backend so that
# artifact_service.py and llm_service.py see the same in-memory state within
# one running process.

artifact_cache = ArtifactCache()
executive_summary_cache = ExecutiveSummaryCache()
