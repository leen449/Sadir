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
├── app/
│   │
│   ├── main.py
│   │
│   ├── pages/
│   │    ├── dashboard.py             # Investigation workspace, graph, LLM interactions, report generation and history
│   │    ├── transaction_analysis.py  # Transaction analysis page
│   │    └── network_view.py          # Network/prediction view
│   │
│   ├── components/
│   │    ├── data_loader.py           # Cached artifact loader
│   │    ├── graph_builder.py         # Builds graph node/edge data
│   │    ├── graph_viewer.py          # ForceGraph3D interactive component
│   │    └── report_history.py        # Displays Report History and report download actions
│   │
│   └── backend/
│        │
│        ├── .gitignore
│        ├── config.py                # Backend configuration and environment variables
│        │
│        ├── services/
│        │    ├── artifact_service.py     # Reads and caches model artifacts
│        │    ├── transaction_service.py  # Builds transaction context
│        │    ├── llm_service.py          # LLM prompts, evidence injection, and response generation
│        │    ├── prewarm.py              # Preloads backend artifacts/services
│        │    ├── report_service.py       # Builds report data and generates PDF reports
│        │    └── firebase_services.py    # Firebase initialization, report storage, metadata, listing, and retrieval
│        │
│        ├── security/
│        │    └── validation.py            # Validates LLM requests
│        │
│        ├── prompts/
│        │    ├── system_prompt.txt
│        │    ├── initial_analysis_prompt.txt
│        │    ├── question_1_positive_shap.txt
│        │    ├── question_2_gnn_neighbors.txt
│        │    └── question_3_negative_shap.txt
│        │
│        ├── utils/
│        │    └── cache.py                 # Artifact and executive-summary caches
│        │
│        └── test_llm_backend.py
│
├── data/
│   └── README.md
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
│   ├── metrics/
│   │    ├── final_metrics.json
│   │    ├── confusion_matrices.png
│   │    ├── pr_curve.png
│   │    └── roc_curve.png
│   │
│   └── notebooks/
│        ├── 01_training.ipynb.ipynb
│        ├── 02_explainability.ipynb.ipynb
│        └── 03_visualization.ipynb
│
└── node_modules/
```
 
---
 
## Running the App
 
```bash
pip install -r requirements.txt
streamlit run app/main.py
```


