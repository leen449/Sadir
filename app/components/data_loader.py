import os, json
from functools import lru_cache          # ← CHANGED: standard-library cache, replaces st.cache_resource
import pandas as pd
import numpy as np
import torch
# ← REMOVED: import streamlit as st

# ── Paths (relative to repo root, adjust if needed) ──────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PATHS = {
    "pyg_graph":               os.path.join(ROOT, "results/graphs/pyg_graph.pt"),
    "transaction_ids":         os.path.join(ROOT, "results/embeddings/transaction_ids.csv"),
    "predictions":             os.path.join(ROOT, "results/predictions/hybrid_predictions.csv"),
    "explanation_graph":       os.path.join(ROOT, "results/explanations/gnn/explanation_graph.json"),
    "transaction_explanations":os.path.join(ROOT, "results/explanations/shap/transaction_explanations.csv"),
    "feature_categories": os.path.join(ROOT, "results/shared/feature_categories.json"),
    "final_metrics":           os.path.join(ROOT, "results/metrics/final_metrics.json"),
}


@lru_cache(maxsize=1)                     # ← CHANGED: runs once, caches result (same idea as st.cache_resource)
def load_all():
    missing = [k for k, p in PATHS.items() if not os.path.exists(p)]
    if missing:
        # ← CHANGED: raise a normal exception instead of st.error(...) + st.stop()
        raise FileNotFoundError(
            f"Missing files: {missing}. Check your results/ and data/ folders."
        )

    graph  = torch.load(PATHS["pyg_graph"], map_location="cpu", weights_only=False)
    tx_df  = pd.read_csv(PATHS["transaction_ids"])
    pred_df= pd.read_csv(PATHS["predictions"])
    shap_df= pd.read_csv(PATHS["transaction_explanations"])

    with open(PATHS["explanation_graph"]) as f:
        expl_graph = json.load(f)
    with open(PATHS["feature_categories"]) as f:
        feat_cats  = json.load(f)
    with open(PATHS["final_metrics"]) as f:
        metrics    = json.load(f)

    # Core lookups
    node_to_tx  = dict(zip(tx_df["node_idx"], tx_df["txId"]))
    tx_to_node  = {v: k for k, v in node_to_tx.items()}
    risk_by_txid= dict(zip(pred_df["txId"], pred_df["prob"]))
    shap_by_txid= shap_df.set_index("txId").to_dict(orient="index")

    edge_np = graph.edge_index.cpu().numpy()

    gnn_edge_imp = {
        (e["source_node_idx"], e["target_node_idx"]): e["edge_importance"]
        for e in expl_graph["edges"]
    }
    gnn_node_imp = {
        n["node_idx"]: n["node_importance"]
        for n in expl_graph["nodes"]
    }

    return {
        "graph": graph, "tx_df": tx_df, "pred_df": pred_df, "shap_df": shap_df,
        "expl_graph": expl_graph, "feat_cats": feat_cats, "metrics": metrics,
        "node_to_tx": node_to_tx, "tx_to_node": tx_to_node,
        "risk_by_txid": risk_by_txid, "shap_by_txid": shap_by_txid,
        "edge_np": edge_np, "gnn_edge_imp": gnn_edge_imp, "gnn_node_imp": gnn_node_imp,
    }