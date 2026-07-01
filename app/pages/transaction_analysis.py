import streamlit as st
import json, sys, os
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from app.components.data_loader import load_all

st.set_page_config(page_title="Transaction Analysis — GraphShields", layout="wide", page_icon="🔎")
st.title("🔎 Transaction Analysis")

d = load_all()

# ── Transaction selector ──────────────────────────────────────────────────────
pred_df  = d["pred_df"].sort_values("prob", ascending=False)
txid_options = pred_df["txId"].astype(str).tolist()
selected_str = st.selectbox(
    "Select transaction (sorted by risk, highest first)",
    txid_options,
    format_func=lambda x: f"txId {x}  —  risk {pred_df.loc[pred_df['txId'].astype(str)==x,'prob'].values[0]*100:.1f}%"
)
selected_txid = int(selected_str)

# ── Row data ──────────────────────────────────────────────────────────────────
row      = pred_df[pred_df["txId"] == selected_txid].iloc[0]
shap_row = d["shap_by_txid"].get(selected_txid, {})

risk_pct = row["prob"] * 100
label    = "🚨 Suspicious" if row["pred"] == 1 else "✅ Normal"

col1, col2, col3 = st.columns(3)
col1.metric("Prediction",      label)
col2.metric("Hybrid Risk Score", f"{risk_pct:.2f}%")
col3.metric("True Label",      "Illicit" if row["true_label"]==1 else "Licit")

st.markdown("---")

# ── SHAP explanation ──────────────────────────────────────────────────────────
def parse_factors(col):
    try:
        return json.loads(shap_row.get(col, "[]"))
    except Exception:
        return []

pos_factors = parse_factors("top_positive_factors")
neg_factors = parse_factors("top_negative_factors")

col_pos, col_neg = st.columns(2)

with col_pos:
    st.markdown("#### 📈 Features Increasing Risk")
    if pos_factors:
        for f in pos_factors:
            st.markdown(f"""
**{f.get('category','?')}** — `{f.get('feature','?')}`  
Impact: `{f.get('impact','?')}`
""")
    else:
        st.info("No SHAP data for this transaction.")

with col_neg:
    st.markdown("#### 📉 Features Decreasing Risk")
    if neg_factors:
        for f in neg_factors:
            st.markdown(f"""
**{f.get('category','?')}** — `{f.get('feature','?')}`  
Impact: `{f.get('impact','?')}`
""")
    else:
        st.info("No SHAP data for this transaction.")

st.markdown("---")

# ── GNN neighbors ─────────────────────────────────────────────────────────────
st.markdown("#### 🕸️ Important GNN Neighbors")
node_idx = d["tx_to_node"].get(selected_txid)
if node_idx is not None:
    neighbors = [
        n for n in d["expl_graph"]["nodes"]
        if n.get("explained_target_node_idx") == node_idx
           or n.get("for_target_node_idx") == node_idx
    ]
    if neighbors:
        nb_df = pd.DataFrame(neighbors)[["txId","node_importance"]].rename(
            columns={"txId":"Neighbor txId","node_importance":"GNN Importance"}
        ).sort_values("GNN Importance", ascending=False)
        st.dataframe(nb_df, use_container_width=True)
    else:
        st.info("No GNNExplainer data for this transaction (only top-20 suspicious transactions were explained).")
else:
    st.warning("Transaction not found in node mapping.")