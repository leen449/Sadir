# GraphShield

GraphShield is an AI-powered Anti-Money Laundering (AML) system that combines Graph Neural Networks, traditional Machine Learning, and Explainable AI to detect suspicious transaction patterns and provide investigators with transparent reasoning behind every prediction.

---

## Problem

Traditional AML systems mainly rely on rule-based detection.

Although effective for known patterns, they struggle with:

- High false positive rates
- Complex fraud networks
- Hidden relationships between transactions
- Lack of explanation behind alerts

This creates unnecessary investigation workload and makes decision-making difficult.

---

# Solution

GraphShield models financial transactions as a graph.

Each transaction becomes a node, and relationships between transactions become edges.

The system learns both:

1. Transaction-level behavior
2. Network-level relationships

to identify suspicious activity.

---

# Features

## Hybrid Detection

Combines:

- Graph Attention Networks (GATv2)
- Gradient Boosted Decision Trees (XGBoost)

to improve fraud detection reliability.

---

## Graph-Based Analysis

Represents transactions as connected networks to identify:

- Suspicious transaction clusters
- Hidden relationships
- High-risk neighbors

---

## Explainable AI

Provides:

- Feature contribution analysis using SHAP
- Important graph connections using GNNExplainer
- Risk reasoning for flagged transactions

---

## Interactive Visualization

Uses 3D graph visualization to allow investigators to:

- Explore transaction networks
- Identify suspicious nodes
- Inspect relationships

---

# Technologies

- Python
- PyTorch
- PyTorch Geometric
- Scikit-learn
- XGBoost
- SHAP
- NetworkX
- ForceGraph3D

---

# Dataset

This project uses:

Elliptic Bitcoin Transaction Dataset

A public benchmark dataset containing:

- 200K+ transactions
- Transaction relationships
- Engineered transaction features
- Labels: licit, illicit, unknown

---

# Evaluation

The system is evaluated using:

- ROC-AUC
- Precision
- Recall
- F1-score
- Confusion Matrix

Special focus is placed on:

- Illicit transaction detection
- Avoiding data leakage
- Preventing overfitting


---

# Team

GraphShield team 
# Architecture
## Architecture
 
```
GraphShield/
│
├── README.md
├── requirements.txt
├── .gitignore
├── .gitattributes
│
├── app/                              # Frontend / Streamlit application
│   │
│   ├── main.py                       # Streamlit entry point
│   │
│   ├── pages/
│   │    ├── dashboard.py             # Overall AML dashboard + 3D graph
│   │    ├── transaction_analysis.py  # Risk + explanation view
│   │    └── network_view.py          # Predictions table + metrics
│   │
│   ├── components/
│   │    ├── __init__.py
│   │    ├── data_loader.py           # Cached artifact loader (all paths)
│   │    ├── graph_builder.py         # Builds node/edge data for 3D viewer
│   │    ├── graph_viewer.py          # ForceGraph3D HTML component
│   │    ├── risk_card.py             # Risk score display widget
│   │    ├── explanation_panel.py     # SHAP + GNN explanation display
│   │    └── charts.py               # Metrics / plots
│   │
│   └── assets/
│
│
├── backend/                          # AI backend logic
│   │
│   ├── models/                       # Model definitions only
│   │    ├── gatv2.py
│   │    ├── xgboost_model.py
│   │    └── hybrid_model.py
│   │
│   ├── inference/                    # Loading weights + prediction
│   │    ├── predictor.py
│   │    └── risk_scoring.py
│   │
│   ├── explainability/               # Reading / generating explanations
│   │    ├── shap_explainer.py
│   │    └── gnn_explainer.py
│   │
│   └── visualization/
│        └── force_graph.py
│
│
├── data/
│   └── README.md
│
│
├── results/
│   │
│   ├── predictions/
│   │    ├── hybrid_predictions.csv
│   │    ├── xgb_predictions.csv
│   │    └── gatv2_predictions.csv
│   │
│   ├── explanations/
│   │    ├── shap/
│   │    │    └── transaction_explanations.csv
│   │    └── gnn/
│   │         ├── important_nodes.csv
│   │         ├── important_edges.csv
│   │         └── explanation_graph.json
│   │
│   ├── graphs/
│   │    ├── pyg_graph.pt
│   │    └── fraud_network.json
│   │
│   ├── embeddings/
│   │    └── transaction_ids.csv
│   │
│   ├── shared/
│   │    └── feature_categories.json
│   │
│   └── metrics/
│        ├── final_metrics.json
│        ├── confusion_matrices.png
│        └── roc_curve.png
│
│
├── notebooks/
│   ├── 01_training.ipynb
│   ├── 02_explainability.ipynb
│   └── 03_visualization.ipynb
│
│
└── deployment/
    ├── Dockerfile
    └── azure_deployment.md
```
 
---
 
## Running the App
 
```bash
pip install -r requirements.txt
streamlit run app/main.py
```
