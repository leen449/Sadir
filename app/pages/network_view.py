import streamlit as st
import pandas as pd
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from app.components.data_loader import load_all

st.set_page_config(page_title="Predictions — GraphShields", layout="wide", page_icon="📋")
st.title("📋 All Predictions")

d = load_all()
m = d["metrics"]

# ── Summary metrics table ─────────────────────────────────────────────────────
st.markdown("### Model Comparison (Temporal Split · Steps 40–49)")
rows = []
for model in ["XGBoost","GATv2","Hybrid"]:
    mm = m.get(model, {})
    rows.append({
        "Model":            model,
        "Licit F1":         f"{mm.get('licit_f1',0):.3f}",
        "Illicit F1":       f"{mm.get('illicit_f1',0):.3f}",
        "Macro F1":         f"{mm.get('macro_f1',0):.3f}",
        "ROC-AUC":          f"{mm.get('roc_auc',0):.3f}",
    })
st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

st.markdown("---")

# ── Filterable predictions table ──────────────────────────────────────────────
pred_df = d["pred_df"].copy()
pred_df["risk_%"]    = (pred_df["prob"]*100).round(2)
pred_df["predicted"] = pred_df["pred"].map({1:"Suspicious",0:"Normal"})
pred_df["true"]      = pred_df["true_label"].map({1:"Illicit",0:"Licit"})
pred_df["correct"]   = pred_df["pred"] == pred_df["true_label"]

col1, col2, col3 = st.columns(3)
show_pred  = col1.multiselect("Prediction",  ["Suspicious","Normal"],    default=["Suspicious","Normal"])
show_true  = col2.multiselect("True Label",  ["Illicit","Licit"],        default=["Illicit","Licit"])
min_risk   = col3.slider("Min risk %", 0, 100, 0)

filtered = pred_df[
    pred_df["predicted"].isin(show_pred) &
    pred_df["true"].isin(show_true) &
    (pred_df["risk_%"] >= min_risk)
].sort_values("risk_%", ascending=False)

st.caption(f"{len(filtered):,} transactions shown")
st.dataframe(
    filtered[["txId","risk_%","predicted","true","correct"]].rename(columns={
        "txId":"txId","risk_%":"Risk %","predicted":"Predicted",
        "true":"True Label","correct":"Correct"
    }),
    use_container_width=True, hide_index=True,
)

# ── Confusion matrices ────────────────────────────────────────────────────────
cm_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "results/metrics/confusion_matrix.png"
)
roc_path = cm_path.replace("confusion_matrix.png","roc_curve.png")

st.markdown("---")
c1, c2 = st.columns(2)
if os.path.exists(cm_path):
    c1.image(cm_path,  caption="Confusion Matrices", use_container_width=True)
if os.path.exists(roc_path):
    c2.image(roc_path, caption="ROC Curves",         use_container_width=True)