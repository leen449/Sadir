from typing import Optional

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response

from app.components.data_loader import load_all
from app.components.graph_builder import build_graph_data
from app.backend.services.transaction_service import (
    build_context,
    SelectedNode,
    TransactionNotFoundError,
)
from app.backend.services.llm_service import generate_explanation_stream
from app.backend.services import firebase_services, report_service
from app.backend.security.validation import ValidationError

app = FastAPI(title="GraphShield API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    load_all()
    return {"status": "ok"}


@app.get("/api/graph")
def get_graph(
    top_n_targets: int = Query(15, ge=1, le=100),
    max_neighbors: int = Query(25, ge=1, le=200),
    num_normal: int = Query(10, ge=0, le=100),
):
    data = load_all()
    return build_graph_data(
        pred_df=data["pred_df"],
        edge_np=data["edge_np"],
        node_to_tx=data["node_to_tx"],
        tx_to_node=data["tx_to_node"],
        risk_by_txid=data["risk_by_txid"],
        shap_by_txid=data["shap_by_txid"],
        gnn_edge_imp=data["gnn_edge_imp"],
        gnn_node_imp=data["gnn_node_imp"],
        top_n_targets=top_n_targets,
        max_neighbors=max_neighbors,
        num_normal=num_normal,
    )


@app.get("/api/analysis/stream")
def analysis_stream(
    txid: str = Query(..., description="Transaction ID the user clicked"),
    node_index: int = Query(..., description="Graph node index for that txId"),
    request_type: str = Query("initial_analysis"),
    question_id: Optional[str] = Query(None),
    session_id: str = Query(..., description="Client session id (enables summary caching)"),
):
    selected = SelectedNode(node_index=node_index, txId=str(txid))

    try:
        context = build_context(str(txid), selected)
    except TransactionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    def event_source():
        try:
            for chunk in generate_explanation_stream(
                context=context,
                request_type=request_type,
                question_id=question_id,
                session_id=session_id,
            ):
                safe = chunk.replace("\r", "").replace("\n", "\\n")
                yield f"data: {safe}\n\n"
            yield "event: done\ndata: end\n\n"
        except ValidationError as e:
            yield f"event: error\ndata: {e.reason_code}: {e.message}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")


# =====================================================================
# STEP 3c — add report saving + history endpoints to api.py
# =====================================================================
#
# 1) At the top of api.py, add firebase_services to your imports:
#
#       from services import report_service, firebase_services
#
#    (If report_service is imported on its own line, just add firebase_services
#     next to it, matching whatever import path your working files use.)
#
# ---------------------------------------------------------------------
# 2) REPLACE your existing create_report function with this version.
#    The only change is the try/except block that calls save_report AFTER
#    the PDF is built. A Firebase failure is swallowed (logged) so it never
#    blocks the user's download — same behavior as the old dashboard.py.
# ---------------------------------------------------------------------
@app.post("/api/reports")
def create_report(session_id: str, txid: str, node_index: Optional[int] = None):
    selected_node = {"txId": str(txid), "node_index": node_index}
    try:
        pdf_bytes, filename = report_service.generate_report(session_id, selected_node)
    except (ValidationError, TransactionNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Persist to Firebase for Report History. Failure here must NOT block the
    # download the user just asked for (mirrors dashboard.py lines 992-1010).
    try:
        firebase_services.save_report(
            pdf_bytes=pdf_bytes,
            filename=filename,
            transaction_id=str(txid),
            status="Under Investigation",
        )
    except Exception as e:
        print(f"[REPORT] Firebase save failed (download still served): "
              f"{type(e).__name__}: {e}")

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------
# 3) ADD these two new endpoints anywhere below create_report.
# ---------------------------------------------------------------------
@app.get("/api/reports/history")
def report_history(limit: int = 100):
    """Shared report history, newest first. Wraps firebase_services.get_reports()."""
    try:
        reports = firebase_services.get_reports(limit=limit)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"History unavailable: {e}")

    # Firestore returns datetime objects for generated_at; make them JSON-safe.
    out = []
    for r in reports:
        item = dict(r)
        ga = item.get("generated_at")
        if hasattr(ga, "isoformat"):
            item["generated_at"] = ga.isoformat()
        out.append(item)
    return out


@app.get("/api/reports/download")
def download_saved_report(storage_path: str):
    """Download a previously-saved report PDF by its Firebase storage_path."""
    try:
        pdf_bytes = firebase_services.download_report(storage_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Download failed: {e}")

    filename = storage_path.rsplit("/", 1)[-1]
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/auth/verify-token")
def verify_token(id_token: str = Body(..., embed=True)):
    """Verify a Firebase ID token sent from the client/frontend."""
    token = str(id_token or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="Authentication token is required.")

    try:
        user = firebase_services.verify_user_token(token)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Authentication failed: {e}")

    return {"verified": True, "user": user}
