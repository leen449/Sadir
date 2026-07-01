import numpy as np
import json

def parse_factors(row, col):
    """Parse JSON SHAP factor list into readable category string + raw string."""
    try:
        factors = json.loads(row.get(col, "[]"))
        cats, raws = [], []
        seen = []
        for f in factors:
            cat    = f.get("category", "Other")
            feat   = f.get("feature", "")
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


def make_node(node_idx, group, imp, node_to_tx, risk_by_txid, shap_by_txid):
    txid = node_to_tx.get(node_idx, "unknown")
    row  = shap_by_txid.get(txid, {})
    pos_cat, pos_raw = parse_factors(row, "top_positive_factors")
    neg_cat, neg_raw = parse_factors(row, "top_negative_factors")
    return {
        "id":  node_idx,
        "txId": str(txid),
        "group": group,
        "gnn_importance":      round(float(imp), 4),
        "predicted_risk":      risk_by_txid.get(txid),   # None → JS null → "n/a"
        "shap_increasing_cat": pos_cat,
        "shap_increasing_raw": pos_raw,
        "shap_decreasing_cat": neg_cat,
        "shap_decreasing_raw": neg_raw,
    }


def build_graph_data(
    pred_df, edge_np, node_to_tx, tx_to_node,
    risk_by_txid, shap_by_txid, gnn_edge_imp, gnn_node_imp,
    top_n_targets=15, max_neighbors=25, num_normal=10,
    default_edge_imp=0.15, default_node_imp=0.2,
):
    src_arr, dst_arr = edge_np[0], edge_np[1]

    target_nodes = (
        pred_df.sort_values("prob", ascending=False)
        .head(top_n_targets)["txId"]
        .map(tx_to_node).dropna().astype(int).tolist()
    )

    nodes_by_id, edge_rows = {}, []

    for t_node in target_nodes:
        nodes_by_id[t_node] = make_node(
            t_node, "target", 1.0, node_to_tx, risk_by_txid, shap_by_txid
        )
        incident = np.where((src_arr == t_node) | (dst_arr == t_node))[0]
        if len(incident) > max_neighbors:
            scored   = [i for i in incident if (int(src_arr[i]), int(dst_arr[i])) in gnn_edge_imp]
            unscored = [i for i in incident if i not in scored]
            incident = (scored + unscored)[:max_neighbors]
        for e in incident:
            s, d = int(src_arr[e]), int(dst_arr[e])
            edge_rows.append({
                "source": s, "target": d,
                "importance": gnn_edge_imp.get((s, d), default_edge_imp),
            })
            other = d if s == t_node else s
            if other in nodes_by_id and nodes_by_id[other]["group"] == "target":
                continue
            imp = max(nodes_by_id[other]["gnn_importance"], gnn_node_imp.get(other, default_node_imp))                   if other in nodes_by_id else gnn_node_imp.get(other, default_node_imp)
            nodes_by_id[other] = make_node(
                other, "neighbor", imp, node_to_tx, risk_by_txid, shap_by_txid
            )

    added = 0
    for _, row in pred_df.sort_values("prob", ascending=True).iterrows():
        n_node = tx_to_node.get(row["txId"])
        if n_node is not None and n_node not in nodes_by_id and added < num_normal:
            nodes_by_id[n_node] = make_node(
                n_node, "normal", default_node_imp, node_to_tx, risk_by_txid, shap_by_txid
            )
            added += 1

    import pandas as pd
    edges_df = pd.DataFrame(edge_rows).drop_duplicates(subset=["source", "target"])
    return {
        "nodes": list(nodes_by_id.values()),
        "links": edges_df.to_dict(orient="records"),
    }