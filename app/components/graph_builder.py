import json
import numpy as np


def parse_factors(row, col):
    """Parse a JSON SHAP factor list into readable category and raw strings."""
    try:
        factors = json.loads(row.get(col, "[]"))
        cats, raws = [], []
        seen = []
        for f in factors:
            cat = f.get("category", "Other")
            feat = f.get("feature", "")
            impact = f.get("impact", "")
            if cat not in seen:
                seen.append(cat)
                cats.append(f"{cat} ({feat}: {impact})")
            else:
                cats.append(f"{feat}: {impact}")
            raws.append(f"{feat}:{impact}")
        return "; ".join(cats) or "n/a", "; ".join(raws) or "n/a"
    except Exception:
        return "n/a", "n/a"


def _factor_lines(row, col, category):
    """Return compact factor strings for one semantic category."""
    try:
        factors = json.loads(row.get(col, "[]"))
    except Exception:
        return []
    out = []
    for factor in factors:
        if factor.get("category") == category:
            feature = factor.get("feature", "?")
            impact = factor.get("impact", "?")
            out.append(f"{feature} ({impact})")
    return out


def make_node(
    node_idx,
    group,
    imp,
    node_to_tx,
    risk_by_txid,
    shap_by_txid,
    prediction_by_txid,
    true_label_by_txid,
):
    txid = node_to_tx.get(node_idx, "unknown")
    row = shap_by_txid.get(txid, {})
    pos_cat, pos_raw = parse_factors(row, "top_positive_factors")
    neg_cat, neg_raw = parse_factors(row, "top_negative_factors")

    profile_factors = (
        _factor_lines(row, "top_positive_factors", "Transaction Profile")
        + _factor_lines(row, "top_negative_factors", "Transaction Profile")
    )
    network_factors = (
        _factor_lines(row, "top_positive_factors", "Network Context")
        + _factor_lines(row, "top_negative_factors", "Network Context")
    )

    pred = prediction_by_txid.get(txid)
    true_label = true_label_by_txid.get(txid)

    return {
        "id": node_idx,
        "txId": str(txid),
        "group": group,
        "prediction": "Suspicious" if pred == 1 else "Normal" if pred == 0 else "n/a",
        "true_label": "Illicit" if true_label == 1 else "Licit" if true_label == 0 else "n/a",
        "gnn_importance": round(float(imp), 4),
        "predicted_risk": risk_by_txid.get(txid),
        "shap_increasing_cat": pos_cat,
        "shap_increasing_raw": pos_raw,
        "shap_decreasing_cat": neg_cat,
        "shap_decreasing_raw": neg_raw,
        "transaction_profile_factors": profile_factors,
        "network_context_factors": network_factors,
    }


def build_graph_data(
    pred_df,
    edge_np,
    node_to_tx,
    tx_to_node,
    risk_by_txid,
    shap_by_txid,
    gnn_edge_imp,
    gnn_node_imp,
    top_n_targets=15,
    max_neighbors=25,
    num_normal=10,
    default_edge_imp=0.15,
    default_node_imp=0.2,
):
    src_arr, dst_arr = edge_np[0], edge_np[1]

    prediction_by_txid = dict(zip(pred_df["txId"], pred_df["pred"]))
    true_label_by_txid = dict(zip(pred_df["txId"], pred_df["true_label"]))

    target_nodes = (
        pred_df.sort_values("prob", ascending=False)
        .head(top_n_targets)["txId"]
        .map(tx_to_node)
        .dropna()
        .astype(int)
        .tolist()
    )

    # Build adjacency once for this graph build instead of scanning the full
    # edge array once per target node.
    adjacency = {}
    for edge_idx, (source, target) in enumerate(zip(src_arr, dst_arr)):
        s, t = int(source), int(target)
        adjacency.setdefault(s, []).append(edge_idx)
        if t != s:
            adjacency.setdefault(t, []).append(edge_idx)

    nodes_by_id, edge_rows = {}, []

    def node_payload(node_idx, group, importance):
        return make_node(
            node_idx,
            group,
            importance,
            node_to_tx,
            risk_by_txid,
            shap_by_txid,
            prediction_by_txid,
            true_label_by_txid,
        )

    for t_node in target_nodes:
        nodes_by_id[t_node] = node_payload(t_node, "target", 1.0)
        incident = list(adjacency.get(t_node, []))

        if len(incident) > max_neighbors:
            scored = [
                i
                for i in incident
                if (int(src_arr[i]), int(dst_arr[i])) in gnn_edge_imp
            ]
            scored_set = set(scored)
            unscored = [i for i in incident if i not in scored_set]
            incident = (scored + unscored)[:max_neighbors]

        for edge_idx in incident:
            s, d = int(src_arr[edge_idx]), int(dst_arr[edge_idx])
            edge_rows.append(
                {
                    "source": s,
                    "target": d,
                    "importance": gnn_edge_imp.get((s, d), default_edge_imp),
                }
            )
            other = d if s == t_node else s
            if other in nodes_by_id and nodes_by_id[other]["group"] == "target":
                continue
            importance = (
                max(nodes_by_id[other]["gnn_importance"], gnn_node_imp.get(other, default_node_imp))
                if other in nodes_by_id
                else gnn_node_imp.get(other, default_node_imp)
            )
            nodes_by_id[other] = node_payload(other, "neighbor", importance)

    added = 0
    for _, row in pred_df.sort_values("prob", ascending=True).iterrows():
        n_node = tx_to_node.get(row["txId"])
        if n_node is not None and n_node not in nodes_by_id and added < num_normal:
            nodes_by_id[n_node] = node_payload(n_node, "normal", default_node_imp)
            added += 1

    import pandas as pd

    edges_df = pd.DataFrame(edge_rows)
    if not edges_df.empty:
        edges_df = edges_df.drop_duplicates(subset=["source", "target"])
    else:
        edges_df = pd.DataFrame(columns=["source", "target", "importance"])

    return {
        "nodes": list(nodes_by_id.values()),
        "links": edges_df.to_dict(orient="records"),
    }
