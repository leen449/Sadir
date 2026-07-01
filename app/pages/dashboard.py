import streamlit as st
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from app.components.data_loader   import load_all
from app.components.graph_builder import build_graph_data
from app.components.graph_viewer  import render_graph

st.set_page_config(page_title="Dashboard — GraphShields", layout="wide", page_icon="📊")
st.title("📊 Dashboard")

d = load_all()
m = d["metrics"]

# ── KPI row ──────────────────────────────────────────────────────────────────
hybrid = m.get("Hybrid", {})
c1,c2,c3,c4 = st.columns(4)
c1.metric("Test Transactions",   f"{len(d['pred_df']):,}")
c2.metric("Flagged Suspicious",  f"{int((d['pred_df']['pred']==1).sum()):,}")
c3.metric("Hybrid Macro F1",     f"{hybrid.get('macro_f1',0):.3f}")
c4.metric("Hybrid ROC-AUC",      f"{hybrid.get('roc_auc',0):.3f}")

st.markdown("---")

# ── Controls ─────────────────────────────────────────────────────────────────
with st.expander("⚙️ Graph settings", expanded=False):
    col1, col2, col3 = st.columns(3)
    top_n    = col1.slider("Target transactions (red)",  5, 30, 15)
    max_nb   = col2.slider("Max neighbors per target",  10, 40, 25)
    num_norm = col3.slider("Normal nodes (grey)",        5, 20, 10)

# ── Build + render ────────────────────────────────────────────────────────────
graph_data = build_graph_data(
    pred_df=d["pred_df"], edge_np=d["edge_np"],
    node_to_tx=d["node_to_tx"], tx_to_node=d["tx_to_node"],
    risk_by_txid=d["risk_by_txid"], shap_by_txid=d["shap_by_txid"],
    gnn_edge_imp=d["gnn_edge_imp"], gnn_node_imp=d["gnn_node_imp"],
    top_n_targets=top_n, max_neighbors=max_nb, num_normal=num_norm,
)
n_nodes = len(graph_data["nodes"])
n_edges = len(graph_data["links"])
st.caption(f"Showing {n_nodes} nodes · {n_edges} edges · click any node for its explanation")

render_graph(graph_data, height=720)