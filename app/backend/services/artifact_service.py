"""
artifact_service.py

Minimal, read-only artifact loader for the LLM backend module.

Scope (intentionally narrow):
    Loads exactly the saved offline artifacts required to build a
    TransactionContext, using the SAME files and column/key conventions as
    app/components/data_loader.py:
        - results/predictions/hybrid_predictions.csv   (txId, pred, prob, true_label)
        - results/explanations/shap/transaction_explanations.csv
              (txId, top_positive_factors, top_negative_factors as JSON strings)
        - results/explanations/gnn/explanation_graph.json
              ("nodes": [{node_idx, node_importance, txId, ...}],
               "edges": [{source_node_idx, target_node_idx, edge_importance}])
        - results/embeddings/transaction_ids.csv        (node_idx, txId)
        - results/shared/feature_categories.json

    NOTE on graph evidence (Q2): the GNNExplainer per-target outputs live in
    important_nodes.csv and important_edges.csv. Each row is tagged with the
    target it explains via `explained_target_txId`. Neighbor/edge lookups are
    therefore target-scoped by that column and return the explainer's important
    subgraph, which can include nodes/edges several hops from the target. An
    earlier revision instead scanned explanation_graph.json for edges directly
    incident to the target node; that discarded most of the explanation and is
    the bug this module fixes.

Out of scope:
    - Report history / report metadata artifacts.
    - Any writing back to disk.
    - The full offline pipeline (models, GATv2, XGBoost, SHAP, GNNExplainer).
      Those are pre-computed by the notebooks; this module only reads their
      saved outputs.

Design notes:
    - Artifacts are loaded lazily on first access and cached in memory for
      the lifetime of the process via utils.cache.artifact_cache, so this
      module can be used independently of Streamlit's own st.cache_resource
      loader in data_loader.py.
    - Nothing here calls Azure OpenAI or knows about LLM prompts. This file
      only exposes lookup-by-transaction_id access.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import pandas as pd

from app.backend.utils.cache import artifact_cache


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Root of the results/ directory. Resolved from THIS file's location (like
# app/components/data_loader.py does) instead of the current working directory,
# so `streamlit run app/pages/dashboard.py` finds the data. Overridable via env.
def _find_results_root() -> str:
    env = os.environ.get("GRAPHSHIELD_RESULTS_ROOT")
    if env and os.path.isdir(env):
        return env
    # Walk up from this file looking for results/predictions/hybrid_predictions.csv.
    probe = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        candidate = os.path.join(probe, "results")
        if os.path.exists(os.path.join(candidate, "predictions", "hybrid_predictions.csv")):
            return candidate
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    # Fallback: mirror data_loader.py (project root = 4 levels up) + /results.
    root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
    return os.path.join(root, "results")


RESULTS_ROOT = _find_results_root()

PREDICTIONS_PATH = os.path.join(RESULTS_ROOT, "predictions", "hybrid_predictions.csv")
SHAP_EXPLANATIONS_PATH = os.path.join(RESULTS_ROOT, "explanations", "shap", "transaction_explanations.csv")
EXPLANATION_GRAPH_PATH = os.path.join(RESULTS_ROOT, "explanations", "gnn", "explanation_graph.json")
TRANSACTION_IDS_PATH = os.path.join(RESULTS_ROOT, "embeddings", "transaction_ids.csv")
FEATURE_CATEGORIES_PATH = os.path.join(RESULTS_ROOT, "shared", "feature_categories.json")

# GNNExplainer per-target outputs. Each row is tagged with the target it
# explains via `explained_target_txId`, so the important subgraph for a given
# transaction is ALL its rows -- not just edges physically incident to the
# target node. Overridable via env vars; falls back to a few common locations.
IMPORTANT_NODES_PATH = os.environ.get(
    "GRAPHSHIELD_IMPORTANT_NODES",
    os.path.join(RESULTS_ROOT, "explanations", "gnn", "important_nodes.csv"),
)
IMPORTANT_EDGES_PATH = os.environ.get(
    "GRAPHSHIELD_IMPORTANT_EDGES",
    os.path.join(RESULTS_ROOT, "explanations", "gnn", "important_edges.csv"),
)

# Cap how many ranked neighbors/edges are handed to the LLM, to keep the Q2
# prompt bounded. Per-target counts in the artifacts are small (<= ~21).
MAX_IMPORTANT_ITEMS = int(os.environ.get("GRAPHSHIELD_MAX_IMPORTANT_ITEMS", "15"))


class ArtifactNotFoundError(FileNotFoundError):
    """Raised when a required artifact file is missing on disk."""


# ---------------------------------------------------------------------------
# Cached loaders (backed by utils.cache.artifact_cache -- process lifetime)
# ---------------------------------------------------------------------------

def _load_csv_cached(path: str, key: str) -> pd.DataFrame:
    def _loader() -> pd.DataFrame:
        if not os.path.exists(path):
            raise ArtifactNotFoundError(f"Required artifact not found: {path}")
        return pd.read_csv(path)

    return artifact_cache.get_or_load(key, _loader)


def _load_json_cached(path: str, key: str) -> Dict[str, Any]:
    def _loader() -> Dict[str, Any]:
        if not os.path.exists(path):
            raise ArtifactNotFoundError(f"Required artifact not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    return artifact_cache.get_or_load(key, _loader)


def clear_cache() -> None:
    """Clear all cached artifacts. Useful for tests and hot-reloading."""
    artifact_cache.clear()


def _resolve_existing(primary: str, *fallbacks: str) -> str:
    """Return the first candidate path that exists on disk.

    Keeps the module working whether the two GNNExplainer CSVs sit under
    results/explanations/gnn/ (default) or next to the other results files.
    If none exist, returns the primary path so the caller raises a clear,
    single ArtifactNotFoundError pointing at the expected location.
    """
    candidates = [primary, *fallbacks]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return primary


def _parse_shap_factors(raw_json: str) -> str:
    """Parse a JSON list of {category, feature, impact} into a single
    human-readable string, e.g. 'Transaction Profile (V6: +1.17); V54: +0.90'.
    Returns 'n/a' on missing/invalid data -- mirrors
    app/components/graph_builder.parse_factors()'s category logic so the
    LLM sees the same evidence the UI displays."""
    try:
        factors = json.loads(raw_json) if raw_json else []
    except (json.JSONDecodeError, TypeError):
        return "n/a"
    if not factors:
        return "n/a"
    parts = []
    seen_categories = set()
    for f in factors:
        cat = f.get("category", "Other")
        feat = f.get("feature", "")
        impact = f.get("impact", "")
        if cat not in seen_categories:
            seen_categories.add(cat)
            parts.append(f"{cat} ({feat}: {impact})")
        else:
            parts.append(f"{feat}: {impact}")
    return "; ".join(parts) if parts else "n/a"


def _node_to_tx_map() -> Dict[Any, str]:
    df = _load_csv_cached(TRANSACTION_IDS_PATH, "transaction_ids")
    return dict(zip(df["node_idx"], df["txId"].astype(str)))


def _tx_to_node_map() -> Dict[str, Any]:
    return {v: k for k, v in _node_to_tx_map().items()}


# ---------------------------------------------------------------------------
# Public lookup API
# ---------------------------------------------------------------------------

def get_prediction_row(transaction_id: str) -> Optional[Dict[str, Any]]:
    """Return the prediction row for a transaction, normalized to
    {prediction, true_label, risk_score}, or None if not found."""
    df = _load_csv_cached(PREDICTIONS_PATH, "predictions")
    match = df[df["txId"].astype(str) == str(transaction_id)]
    if match.empty:
        return None
    row = match.iloc[0].to_dict()
    return {
        "prediction": "suspicious" if row.get("pred") == 1 else "normal",
        "true_label": "illicit" if row.get("true_label") == 1 else "licit",
        "risk_score": row.get("prob"),
    }


def get_gnn_importance_row(transaction_id: str) -> Optional[Dict[str, Any]]:
    """Return {'gnn_importance': float} for the transaction's own node, or
    None if it does not appear in the explanation graph."""
    node_idx = _tx_to_node_map().get(str(transaction_id))
    if node_idx is None:
        return None
    graph = _load_json_cached(EXPLANATION_GRAPH_PATH, "explanation_graph")
    for n in graph.get("nodes", []):
        if n.get("node_idx") == node_idx:
            return {"gnn_importance": n.get("node_importance")}
    return None


def _txid_str(value: Any) -> str:
    """Format a transaction id as a clean integer string (no trailing '.0'
    that pandas introduces when a column is read as float)."""
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return str(value)


def _target_rows(df: pd.DataFrame, transaction_id: str) -> pd.DataFrame:
    """Rows of a per-target GNNExplainer artifact that explain this target.

    Filtering is by `explained_target_txId`, NOT by physical adjacency to the
    target node. This is the whole point of the fix: GNNExplainer's important
    subgraph can include nodes/edges several hops from the target, and those
    must be included as the model's network evidence.
    """
    if "explained_target_txId" not in df.columns:
        return df.iloc[0:0]
    return df[df["explained_target_txId"].astype(str) == str(transaction_id)]


def get_important_neighbors(transaction_id: str) -> List[Dict[str, Any]]:
    """Return the GNNExplainer-selected important neighbor nodes for this
    transaction, ranked by node importance.

    Source: important_nodes.csv, scoped by explained_target_txId. The target's
    own node is excluded. Zero-importance rows are dropped when at least one
    important node exists; otherwise the raw subgraph is returned so the answer
    is never silently empty for a target that does have an explanation.
    """
    path = _resolve_existing(
        IMPORTANT_NODES_PATH,
        os.path.join(RESULTS_ROOT, "important_nodes.csv"),
    )
    df = _load_csv_cached(path, "important_nodes")
    sub = _target_rows(df, transaction_id)
    if sub.empty:
        return []  # no GNN explanation for this target -> Q2 reports unavailable

    # Drop the target's own node from its neighbor list.
    if "node_idx" in sub.columns and "explained_target_node_idx" in sub.columns:
        sub = sub[sub["node_idx"] != sub["explained_target_node_idx"]]

    nonzero = sub[sub["node_importance"] > 0]
    use = nonzero if not nonzero.empty else sub
    use = use.sort_values("node_importance", ascending=False).head(MAX_IMPORTANT_ITEMS)

    return [
        {
            "txId": _txid_str(row.get("txId")),
            "node_importance": round(float(row.get("node_importance", 0.0)), 4),
        }
        for _, row in use.iterrows()
    ]


def get_important_edges(transaction_id: str) -> List[Dict[str, Any]]:
    """Return the GNNExplainer-selected important edges for this transaction,
    ranked by edge importance.

    Source: important_edges.csv, scoped by explained_target_txId. Crucially,
    this includes important edges that do NOT physically touch the target node
    (multi-hop subgraph edges) -- exactly the evidence the previous
    direct-adjacency scan discarded.
    """
    path = _resolve_existing(
        IMPORTANT_EDGES_PATH,
        os.path.join(RESULTS_ROOT, "important_edges.csv"),
    )
    df = _load_csv_cached(path, "important_edges")
    sub = _target_rows(df, transaction_id)
    if sub.empty:
        return []

    nonzero = sub[sub["edge_importance"] > 0]
    use = nonzero if not nonzero.empty else sub
    use = use.sort_values("edge_importance", ascending=False).head(MAX_IMPORTANT_ITEMS)

    return [
        {
            "source_txId": _txid_str(row.get("source_txId")),
            "target_txId": _txid_str(row.get("target_txId")),
            "edge_importance": round(float(row.get("edge_importance", 0.0)), 4),
        }
        for _, row in use.iterrows()
    ]


def get_shap_row(transaction_id: str) -> Optional[Dict[str, Any]]:
    """Return {'positive_shap', 'negative_shap'} as human-readable strings
    parsed from transaction_explanations.csv's JSON factor columns."""
    df = _load_csv_cached(SHAP_EXPLANATIONS_PATH, "shap_explanations")
    match = df[df["txId"].astype(str) == str(transaction_id)]
    if match.empty:
        return None
    row = match.iloc[0].to_dict()
    return {
        "positive_shap": _parse_shap_factors(row.get("top_positive_factors", "[]")),
        "negative_shap": _parse_shap_factors(row.get("top_negative_factors", "[]")),
    }


def get_feature_categories() -> Dict[str, Any]:
    """Return the shared feature-category mapping (ranges/prefix/label)."""
    return _load_json_cached(FEATURE_CATEGORIES_PATH, "feature_categories")


def transaction_exists(transaction_id: str) -> bool:
    return get_prediction_row(transaction_id) is not None


def node_exists(node_index: Any) -> bool:
    """Check whether a given node index appears in the transaction/node
    mapping (i.e. it is a known node in the analyzed graph)."""
    return node_index in _node_to_tx_map()