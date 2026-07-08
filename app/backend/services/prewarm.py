"""
prewarm.py

One-time, background startup warm-up for the GraphShield investigation page.

Purpose
-------
The FIRST LLM investigation of a session is disproportionately slow (observed
~26s vs ~12-17s for later calls). Measurement showed this is NOT backend data
loading (~0.6s); it is the cold Azure OpenAI path: building the HTTPS client and
the deployment warming up on the first real request.

This module removes that first-click penalty by doing the cold work up front,
in a background daemon thread, as soon as the page loads -- so by the time the
analyst clicks "Analyze", the connection is open, the deployment is warm, and
the backend artifact cache is populated.

Safety / isolation
-------------------
- Runs in a plain daemon thread. It NEVER calls any Streamlit API and NEVER
  touches st.session_state or the investigation state machine, so it cannot
  affect UI responsiveness or reintroduce the earlier fragment/async issues.
- Runs exactly once per process (guarded by a module-level flag + lock). Calling
  start_prewarm() on every Streamlit rerun is cheap: the guard returns instantly.
- Every step is wrapped in try/except and only logs on failure. A warm-up
  problem can never crash the page or block rendering.
- Can be disabled entirely with the env var GRAPHSHIELD_PREWARM=0.

Usage (add ONE line to pages/dashboard.py, e.g. right after load_all()):

    from services.prewarm import start_prewarm
    start_prewarm()
"""

from __future__ import annotations

import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

_started = False
_lock = threading.Lock()


def start_prewarm() -> None:
    """Kick off the one-time background warm-up (idempotent, non-blocking)."""
    global _started

    if os.environ.get("GRAPHSHIELD_PREWARM", "1") == "0":
        return

    with _lock:
        if _started:
            return
        _started = True

    thread = threading.Thread(
        target=_prewarm_worker,
        name="graphshield-prewarm",
        daemon=True,
    )
    thread.start()


def _warm_artifact_cache() -> None:
    """Populate the backend artifact cache so the first build_context is fast.

    Uses only public artifact_service functions, with a dummy id that will not
    match any transaction. The lookups still load and cache each underlying
    file (the load happens before the id filter), which is the point.
    """
    started = time.perf_counter()
    from services import artifact_service as a

    # Each call loads+caches its file even though "0" matches nothing.
    a.get_feature_categories()          # feature_categories.json
    a.transaction_exists("0")           # hybrid_predictions.csv
    a.get_shap_row("0")                 # transaction_explanations.csv
    a.get_important_neighbors("0")      # important_nodes.csv
    a.get_important_edges("0")          # important_edges.csv
    a.node_exists(0)                    # transaction_ids.csv (the large map)

    print(f"[PREWARM] artifact cache warmed: {time.perf_counter() - started:.3f}s")


def _warm_azure() -> None:
    """Open the Azure client and warm the deployment with one tiny request.

    This is the part that removes the ~10s cold-start seen on the first
    investigation. Output is irrelevant -- we only care that the connection is
    established and the deployment is warm.
    """
    started = time.perf_counter()
    from config import settings
    from services.llm_service import _get_azure_client

    deployment = getattr(settings, "AZURE_OPENAI_DEPLOYMENT", None)
    if not deployment:
        print("[PREWARM] Azure not configured; skipping deployment warm-up")
        return

    client = _get_azure_client()  # builds + caches the HTTPS client (TLS handshake)
    client.chat.completions.create(
        model=deployment,
        messages=[{"role": "user", "content": "ping"}],
        max_completion_tokens=16,
    )
    print(f"[PREWARM] Azure deployment warmed: {time.perf_counter() - started:.3f}s")


def _prewarm_worker() -> None:
    try:
        _warm_artifact_cache()
    except Exception:
        logger.exception("prewarm: artifact cache warm-up failed (non-fatal)")

    try:
        _warm_azure()
    except Exception:
        logger.exception("prewarm: Azure warm-up failed (non-fatal)")
