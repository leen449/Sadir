import streamlit as st

st.set_page_config(
    page_title="GraphShields — AML Explorer",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.sidebar.markdown("""
# 🛡️ GraphShields
**AMAD Hackathon**  
GATv2 + XGBoost Ensemble  
Elliptic Bitcoin Dataset

---
""")
st.sidebar.page_link("pages/dashboard.py",           label="📊 Dashboard & 3D Graph")
st.sidebar.page_link("pages/transaction_analysis.py", label="🔎 Transaction Analysis")
st.sidebar.page_link("pages/network_view.py",         label="📋 Predictions Table")

st.title("🛡️ GraphShields")
st.markdown("""
Welcome to the GraphShields AML Explorer built for the **AMAD Hackathon**.

**What this app shows:**
- A 3D interactive graph of the Bitcoin transaction network, coloured by fraud risk
- Per-transaction SHAP + GNNExplainer explanations
- Full model evaluation results (temporal split, no data leakage)

Use the sidebar to navigate.
""")