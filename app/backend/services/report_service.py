"""
report_service.py

Builds the GraphShield "AI Transaction Investigation Report".

Design (per handoff section 42 and the agreed spec):
  * Only the EXECUTIVE SUMMARY comes from the LLM. It is reused from the
    executive_summary_cache when the analyst already clicked Analyze; on a cache
    miss (report requested without Analyze) it is generated on demand and cached.
  * Every other section is DETERMINISTIC, assembled from the existing artifacts
    via artifact_service. No LLM involvement.

Definitions (agreed):
  * Model Confidence = decision-margin from the 0.8 threshold (Option A). It is
    NOT calibrated statistical confidence and is labelled accordingly.
  * Evidence Summary = conditional bullets whose wording reflects what SHAP and
    GNNExplainer actually show.
  * Network Investigation = direct, interpretable GNNExplainer measurements.
    Graph Influence Score is intentionally omitted (no separation in the data).

Public entry point:
    generate_report(session_id, selected_node) -> (pdf_bytes, filename)
"""

from __future__ import annotations

import io
import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from services import artifact_service as A

DECISION_THRESHOLD = 0.8

# Evidence-rule thresholds, kept in one place so they are easy to tune.
TX_FEATURE_SHAP_MIN = 0.5          # |SHAP| for a Transaction Profile factor
SUSPICIOUS_RISK_MIN = 0.90         # risk score for "strong suspicious-risk signal"
MIN_INFLUENTIAL_NODES = 2          # for "multiple influential network transactions"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class ReportData:
    report_id: str
    transaction_id: str
    generated_at: datetime
    status: str

    # Transaction Overview
    prediction_label: str            # "High Risk" / "Low Risk"
    risk_score: float                # 0..1
    confidence_label: str            # High / Medium / Low
    confidence_margin: float         # 0..1

    # Evidence Summary
    evidence_bullets: List[str] = field(default_factory=list)

    # Explainability (each item: {"feature","category","impact"})
    increasing_factors: List[Dict[str, Any]] = field(default_factory=list)
    reducing_factors: List[Dict[str, Any]] = field(default_factory=list)
    explainability_available: bool = True

    # Network Investigation
    network_available: bool = True
    network_transactions_analysed: int = 0
    influential_network_transactions: int = 0
    influential_edges: int = 0
    highest_edge_importance: Optional[float] = None


# ---------------------------------------------------------------------------
# Base-model predictions (for the agreement bullet)
# ---------------------------------------------------------------------------
def _predictions_path(name: str) -> str:
    return A._resolve_existing(
        os.path.join(A.RESULTS_ROOT, "predictions", f"{name}_predictions.csv"),
        os.path.join(A.RESULTS_ROOT, f"{name}_predictions.csv"),
    )


def _base_model_pred(name: str, transaction_id: str) -> Optional[int]:
    """Return the integer `pred` (0/1) for a base model, or None if absent."""
    try:
        df = A._load_csv_cached(_predictions_path(name), f"{name}_predictions")
    except Exception:
        return None
    match = df[df["txId"].astype(str) == str(transaction_id)]
    if match.empty:
        return None
    return int(match.iloc[0]["pred"])


# ---------------------------------------------------------------------------
# Structured SHAP factors (feature / category / signed impact)
# ---------------------------------------------------------------------------
def _structured_shap(transaction_id: str) -> Optional[Dict[str, List[Dict[str, Any]]]]:
    """Parse transaction_explanations.csv into structured positive/negative
    factor lists. Returns None if the transaction has no SHAP explanation."""
    try:
        df = A._load_csv_cached(A.SHAP_EXPLANATIONS_PATH, "shap_explanations")
    except Exception:
        return None
    match = df[df["txId"].astype(str) == str(transaction_id)]
    if match.empty:
        return None
    row = match.iloc[0].to_dict()

    def _parse(raw: Any) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        try:
            for f in json.loads(raw or "[]"):
                impact_raw = str(f.get("impact", "0")).replace("+", "")
                try:
                    impact = float(impact_raw)
                except ValueError:
                    impact = 0.0
                out.append({
                    "feature": f.get("feature"),
                    "category": f.get("category", ""),
                    "impact": impact,
                })
        except (json.JSONDecodeError, TypeError):
            pass
        return out

    return {
        "positive": _parse(row.get("top_positive_factors", "[]")),
        "negative": _parse(row.get("top_negative_factors", "[]")),
    }


# ---------------------------------------------------------------------------
# GNNExplainer subgraph measurements
# ---------------------------------------------------------------------------
def _gnn_measurements(transaction_id: str) -> Dict[str, Any]:
    """Direct interpretable GNNExplainer numbers for the target, computed from
    the raw important_nodes/edges artifacts (so we can count non-zero exactly)."""
    result = {
        "available": False,
        "analysed": 0,
        "influential_nodes": 0,
        "influential_edges": 0,
        "highest_edge_importance": None,
    }

    nodes_path = A._resolve_existing(
        A.IMPORTANT_NODES_PATH, os.path.join(A.RESULTS_ROOT, "important_nodes.csv")
    )
    edges_path = A._resolve_existing(
        A.IMPORTANT_EDGES_PATH, os.path.join(A.RESULTS_ROOT, "important_edges.csv")
    )
    try:
        ndf = A._load_csv_cached(nodes_path, "important_nodes")
        edf = A._load_csv_cached(edges_path, "important_edges")
    except Exception:
        return result

    n_sub = ndf[ndf["explained_target_txId"].astype(str) == str(transaction_id)]
    e_sub = edf[edf["explained_target_txId"].astype(str) == str(transaction_id)]
    if n_sub.empty and e_sub.empty:
        return result

    # Non-target nodes only.
    if "node_idx" in n_sub.columns and "explained_target_node_idx" in n_sub.columns:
        non_target = n_sub[n_sub["node_idx"] != n_sub["explained_target_node_idx"]]
    else:
        non_target = n_sub

    result["available"] = True
    result["analysed"] = int(len(non_target))
    result["influential_nodes"] = int((non_target["node_importance"] > 0).sum())
    result["influential_edges"] = int((e_sub["edge_importance"] > 0).sum())
    if not e_sub.empty:
        result["highest_edge_importance"] = round(float(e_sub["edge_importance"].max()), 4)
    return result


# ---------------------------------------------------------------------------
# Model confidence (Option A: decision-margin from the 0.8 threshold)
# ---------------------------------------------------------------------------
def compute_model_confidence(risk_score: float) -> Dict[str, Any]:
    if risk_score >= DECISION_THRESHOLD:
        margin = (risk_score - DECISION_THRESHOLD) / (1.0 - DECISION_THRESHOLD)
    else:
        margin = (DECISION_THRESHOLD - risk_score) / DECISION_THRESHOLD
    margin = max(0.0, min(1.0, margin))
    if margin >= 0.6:
        label = "High"
    elif margin >= 0.3:
        label = "Medium"
    else:
        label = "Low"
    return {"label": label, "margin": round(margin, 4)}


# ---------------------------------------------------------------------------
# Evidence Summary (conditional bullets)
# ---------------------------------------------------------------------------
def _build_evidence_bullets(
    transaction_id: str,
    prediction_label_raw: str,   # "suspicious" / "normal"
    risk_score: float,
    shap: Optional[Dict[str, List[Dict[str, Any]]]],
    gnn: Dict[str, Any],
    hybrid_pred: int,
) -> List[str]:
    bullets: List[str] = []

    if gnn.get("available") and gnn.get("influential_edges", 0) > 0:
        bullets.append("Strong network influence")

    if gnn.get("available") and gnn.get("influential_nodes", 0) >= MIN_INFLUENTIAL_NODES:
        bullets.append("Multiple influential network transactions")

    if shap:
        strong_tx = any(
            f.get("category") == "Transaction Profile" and abs(f.get("impact", 0.0)) >= TX_FEATURE_SHAP_MIN
            for f in shap.get("positive", []) + shap.get("negative", [])
        )
        if strong_tx:
            bullets.append("Strong transaction-level feature influence")

    xgb_pred = _base_model_pred("xgb", transaction_id)
    gatv2_pred = _base_model_pred("gatv2", transaction_id)
    if xgb_pred is not None and gatv2_pred is not None and xgb_pred == gatv2_pred:
        bullets.append("Hybrid model agreement")

    if prediction_label_raw == "suspicious" and risk_score >= SUSPICIOUS_RISK_MIN:
        bullets.append("Strong suspicious-risk signal")

    return bullets


# ---------------------------------------------------------------------------
# Report ID + history (handoff: running counter, persisted)
# ---------------------------------------------------------------------------
_id_lock = threading.Lock()


def _reports_dir() -> str:
    d = os.path.join(A.RESULTS_ROOT, "reports")
    os.makedirs(d, exist_ok=True)
    return d


def _history_path() -> str:
    return os.path.join(_reports_dir(), "report_history.json")


def _next_report_id(transaction_id: str, generated_at: datetime) -> str:
    with _id_lock:
        path = _history_path()
        history: List[Dict[str, Any]] = []
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    history = json.load(fh)
            except (json.JSONDecodeError, OSError):
                history = []
        counter = len(history) + 1
        report_id = f"GS-{generated_at.year}-{counter:05d}"
        history.append({
            "report_id": report_id,
            "transaction_id": str(transaction_id),
            "generated_at": generated_at.isoformat(timespec="seconds"),
        })
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(history, fh, indent=2)
        except OSError:
            pass
        return report_id


# ---------------------------------------------------------------------------
# Deterministic assembly
# ---------------------------------------------------------------------------
def build_report_data(transaction_id: str) -> ReportData:
    transaction_id = str(transaction_id)
    pred = A.get_prediction_row(transaction_id)
    if pred is None:
        raise ValueError(f"No prediction found for transaction {transaction_id}")

    risk_score = float(pred["risk_score"])
    prediction_raw = pred["prediction"]  # "suspicious"/"normal"
    prediction_label = "High Risk" if prediction_raw == "suspicious" else "Low Risk"
    confidence = compute_model_confidence(risk_score)

    shap = _structured_shap(transaction_id)
    gnn = _gnn_measurements(transaction_id)

    hybrid_pred = 1 if prediction_raw == "suspicious" else 0
    evidence = _build_evidence_bullets(
        transaction_id, prediction_raw, risk_score, shap, gnn, hybrid_pred
    )

    increasing = shap["positive"] if shap else []
    reducing = shap["negative"] if shap else []

    generated_at = datetime.now()
    report_id = _next_report_id(transaction_id, generated_at)

    return ReportData(
        report_id=report_id,
        transaction_id=transaction_id,
        generated_at=generated_at,
        status="Under Investigation",
        prediction_label=prediction_label,
        risk_score=risk_score,
        confidence_label=confidence["label"],
        confidence_margin=confidence["margin"],
        evidence_bullets=evidence,
        increasing_factors=increasing,
        reducing_factors=reducing,
        explainability_available=shap is not None,
        network_available=gnn["available"],
        network_transactions_analysed=gnn["analysed"],
        influential_network_transactions=gnn["influential_nodes"],
        influential_edges=gnn["influential_edges"],
        highest_edge_importance=gnn["highest_edge_importance"],
    )


# ---------------------------------------------------------------------------
# Executive summary (cache-first, generate-on-demand)
# ---------------------------------------------------------------------------
def get_executive_summary(session_id: str, transaction_id: str, node_index: Any = None) -> str:
    """Reuse the cached initial analysis; generate + cache on a miss so a report
    is obtainable even if Analyze was never clicked."""
    from utils.cache import executive_summary_cache

    cached = executive_summary_cache.get(session_id, str(transaction_id))
    if cached:
        return cached

    # On-demand generation (adds LLM latency). generate_explanation writes the
    # result back into executive_summary_cache itself.
    from services.llm_service import generate_explanation
    from services.transaction_service import SelectedNode, build_context

    context = build_context(
        str(transaction_id),
        SelectedNode(node_index=node_index, txId=str(transaction_id)),
    )
    return generate_explanation(
        context,
        request_type="initial_analysis",
        session_id=session_id,
    )


# ---------------------------------------------------------------------------
# PDF rendering (ReportLab)
# ---------------------------------------------------------------------------
def render_pdf(data: ReportData, executive_summary: str) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    NAVY = colors.HexColor("#1a2b4a")
    GREY = colors.HexColor("#5b6472")
    RED = colors.HexColor("#b3261e")
    GREEN = colors.HexColor("#1b7f4b")
    LIGHT = colors.HexColor("#f4f6fa")
    BORDER = colors.HexColor("#d7dde8")

    ss = getSampleStyleSheet()
    title = ParagraphStyle("t", parent=ss["Title"], textColor=NAVY, fontSize=18, spaceAfter=2, alignment=TA_CENTER)
    subtitle = ParagraphStyle("s", parent=ss["Normal"], textColor=GREY, fontSize=10.5, alignment=TA_CENTER, spaceAfter=8)
    section = ParagraphStyle("sec", parent=ss["Heading2"], textColor=NAVY, fontSize=11.5, spaceBefore=10, spaceAfter=4)
    sub = ParagraphStyle("sub", parent=ss["Normal"], textColor=NAVY, fontSize=9.5, spaceBefore=4, spaceAfter=2, leading=12)
    body = ParagraphStyle("b", parent=ss["Normal"], fontSize=9.5, leading=14, textColor=colors.HexColor("#20242c"))
    small = ParagraphStyle("sm", parent=ss["Normal"], fontSize=8, textColor=GREY, alignment=TA_CENTER)
    cell = ParagraphStyle("c", parent=ss["Normal"], fontSize=9, leading=12)
    cell_b = ParagraphStyle("cb", parent=cell, textColor=NAVY, fontName="Helvetica-Bold")

    def rule():
        return HRFlowable(width="100%", thickness=1.4, color=NAVY, spaceBefore=3, spaceAfter=6)

    story: List[Any] = []
    story.append(Paragraph("GRAPHSHIELD", title))
    story.append(Paragraph("AI Transaction Investigation Report", subtitle))
    story.append(rule())

    # Metadata strip
    meta = [[
        Paragraph("<b>Report ID</b><br/>" + data.report_id, cell),
        Paragraph("<b>Transaction ID</b><br/>" + data.transaction_id, cell),
        Paragraph("<b>Generated</b><br/>" + data.generated_at.strftime("%d %b %Y"), cell),
        Paragraph("<b>Generated by</b><br/>GraphShield", cell),
        Paragraph("<b>Status</b><br/>" + data.status, cell),
    ]]
    mt = Table(meta, colWidths=[36 * mm] * 5)
    mt.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.6, BORDER),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(mt)

    # Executive summary
    story.append(Paragraph("EXECUTIVE SUMMARY", section))
    story.append(rule())
    box = Table([[Paragraph(executive_summary or "Executive summary unavailable.", body)]], colWidths=[170 * mm])
    box.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(box)

    # Overview + evidence (two columns)
    story.append(Paragraph("TRANSACTION OVERVIEW", section))
    story.append(rule())
    overview_rows = [
        [Paragraph("Transaction ID", cell), Paragraph(data.transaction_id, cell_b)],
        [Paragraph("Prediction", cell), Paragraph(data.prediction_label, cell_b)],
        [Paragraph("Risk Score", cell), Paragraph(f"{data.risk_score * 100:.1f}%", cell_b)],
        [Paragraph("Model Confidence", cell), Paragraph(f"{data.confidence_label}", cell_b)],
        [Paragraph("Generated At", cell), Paragraph(data.generated_at.strftime("%d %b %Y %I:%M %p"), cell_b)],
    ]
    ov = Table(overview_rows, colWidths=[38 * mm, 45 * mm])
    ov.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.6, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))

    if data.evidence_bullets:
        ev_html = "<br/>".join("&bull;&nbsp; " + b for b in data.evidence_bullets)
    else:
        ev_html = "&bull;&nbsp; No distinguishing evidence signals met their thresholds."
    ev = Table([[Paragraph(ev_html, body)]], colWidths=[80 * mm])
    ev.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("VALIGN", (0, 0), (0, 0), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    two = Table(
        [[Paragraph("Transaction Overview", sub), Paragraph("Evidence Summary", sub)], [ov, ev]],
        colWidths=[88 * mm, 88 * mm],
    )
    two.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(two)

    # Explainability
    story.append(Paragraph("EXPLAINABILITY", section))
    story.append(rule())
    if data.explainability_available:
        def factor_block(factors: List[Dict[str, Any]], colour) -> List[Any]:
            blocks: List[Any] = []
            for cat in ("Transaction Profile", "Network Context"):
                items = [f for f in factors if f.get("category") == cat]
                if not items:
                    continue
                blocks.append(Paragraph(cat, sub))
                lines = "<br/>".join(
                    f'&bull;&nbsp; {f["feature"]} '
                    f'(<font color="{colour}">{"+" if f["impact"] >= 0 else ""}{f["impact"]:.2f}</font>)'
                    for f in items
                )
                blocks.append(Paragraph(lines, body))
            if not blocks:
                blocks.append(Paragraph("None", body))
            return blocks

        left = [Paragraph("Factors Increasing Risk", sub)] + factor_block(data.increasing_factors, "#b3261e")
        right = [Paragraph("Factors Reducing Risk", sub)] + factor_block(data.reducing_factors, "#1b7f4b")
        exp = Table([[left, right]], colWidths=[88 * mm, 88 * mm])
        exp.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
            ("LINEAFTER", (0, 0), (0, 0), 0.6, BORDER),
            ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(exp)
    else:
        story.append(Paragraph(
            "Feature-level (SHAP) explanation is not available for this transaction.", body))

    # Network investigation
    story.append(Paragraph("NETWORK INVESTIGATION", section))
    story.append(rule())
    if data.network_available:
        hei = data.highest_edge_importance
        net_rows = [
            [Paragraph("Target Transaction", cell), Paragraph(data.transaction_id, cell_b)],
            [Paragraph("Network Transactions Analysed", cell), Paragraph(str(data.network_transactions_analysed), cell_b)],
            [Paragraph("Influential Network Transactions", cell), Paragraph(str(data.influential_network_transactions), cell_b)],
            [Paragraph("Number of Influential Edges", cell), Paragraph(str(data.influential_edges), cell_b)],
            [Paragraph("Highest Edge Importance", cell), Paragraph("N/A" if hei is None else f"{hei:.2f}", cell_b)],
        ]
        nt = Table(net_rows, colWidths=[62 * mm, 40 * mm])
        nt.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.6, BORDER),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(nt)
    else:
        story.append(Paragraph(
            "Graph explanation evidence is not available for this transaction.", body))

    story.append(Spacer(1, 10))
    story.append(rule())
    story.append(Paragraph("Generated by GraphShield &nbsp;|&nbsp; Version 1.0 &nbsp;|&nbsp; Confidential", small))
    story.append(Paragraph(
        "Model Confidence is a decision-margin indicator derived from the Hybrid Risk Score's "
        "distance from the classification threshold; it is not a calibrated statistical probability.",
        small,
    ))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=14 * mm,
        title=f"GraphShield Report {data.report_id}",
    )
    doc.build(story)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
def generate_report(session_id: str, selected_node: Dict[str, Any]) -> tuple[bytes, str]:
    """Full pipeline: deterministic data + executive summary -> PDF bytes."""
    transaction_id = str(selected_node["txId"])
    node_index = selected_node.get("node_index")

    data = build_report_data(transaction_id)
    summary = get_executive_summary(session_id, transaction_id, node_index)
    pdf_bytes = render_pdf(data, summary)
    filename = f"{data.report_id}_{transaction_id}.pdf"
    return pdf_bytes, filename
