"""GraphShield investigation workspace.

The ForceGraph3D component remains the main visualization. Node details and
Analyze action live in the in-graph card; LLM investigation content lives in a
fixed left workspace panel.
"""

import json
import os
import sys
import time
import uuid

import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
_BACKEND_ROOT = os.path.join(os.path.dirname(__file__), "..", "backend")
sys.path.insert(0, os.path.abspath(_BACKEND_ROOT))



from app.components.data_loader import load_all
from app.components.graph_builder import build_graph_data
from app.components.graph_viewer import render_graph
from app.components.report_history import render_report_history
from security.validation import ValidationError
from services.llm_service import generate_explanation
from services.transaction_service import SelectedNode, build_context
from services import firebase_services, report_service

st.set_page_config(
    page_title="Investigation Workspace — GraphShield",
    layout="wide",
    page_icon="🕵️",
)

st.markdown(
    """
<style>
.st-key-investigation_sidebar {
    position: fixed;
    top: 0;
    left: 0;
    width: min(430px, 92vw);
    height: 100vh;
    box-sizing: border-box;
    background: #12151c;
    border-right: 1px solid #2a2f3a;
    z-index: 999999;
    overflow-y: auto;
    padding: 18px 18px 28px 18px;
    box-shadow: 4px 0 24px rgba(0,0,0,.45);
}
.st-key-investigation_response_area {
    background: #1a1e28;
    border: 1px solid #2a3040;
    border-radius: 10px;
    padding: 14px 16px;
    margin: 8px 0 16px 0;
    min-height: 130px;
    font-size: 14px;
    line-height: 1.6;
}
.error-box {
    background: #3a1f1f;
    border: 1px solid #7a3a3a;
    border-radius: 8px;
    padding: 12px 14px;
    color: #ffb0b0;
}
</style>
""",
    unsafe_allow_html=True,
)

st.title("🕵️ Investigation Workspace")
d = load_all()

if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

st.session_state.setdefault("selected_node", None)
st.session_state.setdefault("sidebar_open", False)
st.session_state.setdefault("initial_analysis_text", None)
st.session_state.setdefault("initial_analysis_error", None)
st.session_state.setdefault("initial_analysis_pending", False)
st.session_state.setdefault("question_answer_text", None)
st.session_state.setdefault("question_error", None)
st.session_state.setdefault("question_pending_id", None)
st.session_state.setdefault("graph_cache_key", None)
st.session_state.setdefault("graph_cache_value", None)
st.session_state.setdefault("report_pdf_bytes", None)
st.session_state.setdefault("report_filename", None)
st.session_state.setdefault("report_txid", None)
st.session_state.setdefault("report_error", None)
st.session_state.setdefault("report_download_token", None)
st.session_state.setdefault("report_storage_error", None)


def _reset_investigation_state():
    st.session_state.initial_analysis_text = None
    st.session_state.initial_analysis_error = None
    st.session_state.initial_analysis_pending = False
    st.session_state.question_answer_text = None
    st.session_state.question_error = None
    st.session_state.question_pending_id = None


def _select_node(payload: dict | None):
    if not payload:
        return
    previous_txid = (st.session_state.selected_node or {}).get("txId")
    st.session_state.selected_node = payload
    if payload.get("txId") != previous_txid:
        _reset_investigation_state()


def _build_selected_node_obj(selected: dict) -> SelectedNode:
    return SelectedNode(
        node_index=selected.get("node_index"),
        txId=str(selected["txId"]),
    )


def _run_initial_analysis(selected: dict):
    started = time.perf_counter()
    try:
        context = build_context(selected["txId"], _build_selected_node_obj(selected))
        st.session_state.initial_analysis_text = generate_explanation(
            context,
            request_type="initial_analysis",
            session_id=st.session_state.session_id,
        )
        st.session_state.initial_analysis_error = None
    except ValidationError:
        st.session_state.initial_analysis_error = (
            "This transaction could not be analyzed because the request did not pass validation. "
            "Please select a valid transaction and try again."
        )
    except Exception:
        st.session_state.initial_analysis_error = (
            "The analysis request failed unexpectedly. Please try again."
        )
    finally:
        st.session_state.initial_analysis_pending = False
        print(f"[PERF] initial_analysis total: {time.perf_counter() - started:.3f}s")


def _run_question(selected: dict, question_id: str):
    started = time.perf_counter()
    try:
        context = build_context(selected["txId"], _build_selected_node_obj(selected))
        st.session_state.question_answer_text = generate_explanation(
            context,
            request_type="question",
            question_id=question_id,
            session_id=st.session_state.session_id,
        )
        st.session_state.question_error = None
    except ValidationError:
        st.session_state.question_error = (
            "This question could not be answered because the request did not pass validation."
        )
    except Exception:
        st.session_state.question_error = (
            "The question request failed unexpectedly. Please try again."
        )
    finally:
        st.session_state.question_pending_id = None
        print(f"[PERF] {question_id} total: {time.perf_counter() - started:.3f}s")


SUGGESTED_QUESTIONS = [
    ("question_1", "Which transaction characteristics contributed most to this prediction?"),
    ("question_2", "How did neighboring transactions influence this prediction?"),
    ("question_3", "Which evidence reduced the estimated risk?"),
]

# 1. Graph controls
with st.expander("⚙️ Graph Settings", expanded=False):
    col1, col2, col3 = st.columns(3)
    top_n = col1.slider("Target Transactions", 5, 30, 15)
    max_nb = col2.slider("Maximum Neighbors per Target", 10, 40, 25)
    num_norm = col3.slider("Normal Nodes", 5, 20, 10)

# 2. Filters
fcol1, fcol2 = st.columns(2)
show_pred = fcol1.multiselect(
    "Prediction",
    ["Suspicious", "Normal"],
    default=["Suspicious", "Normal"],
)
show_true = fcol2.multiselect(
    "True Label",
    ["Illicit", "Licit"],
    default=["Illicit", "Licit"],
)

pred_df_filtered = d["pred_df"].copy()
pred_labels = pred_df_filtered["pred"].map({1: "Suspicious", 0: "Normal"})
true_labels = pred_df_filtered["true_label"].map({1: "Illicit", 0: "Licit"})
pred_df_filtered = pred_df_filtered[
    pred_labels.isin(show_pred) & true_labels.isin(show_true)
]

# 3. Graph data memoization: rebuild only when controls or filters change.
graph_cache_key = (
    top_n,
    max_nb,
    num_norm,
    tuple(sorted(show_pred)),
    tuple(sorted(show_true)),
)

if st.session_state.graph_cache_key != graph_cache_key:
    started = time.perf_counter()
    st.session_state.graph_cache_value = build_graph_data(
        pred_df=pred_df_filtered,
        edge_np=d["edge_np"],
        node_to_tx=d["node_to_tx"],
        tx_to_node=d["tx_to_node"],
        risk_by_txid=d["risk_by_txid"],
        shap_by_txid=d["shap_by_txid"],
        gnn_edge_imp=d["gnn_edge_imp"],
        gnn_node_imp=d["gnn_node_imp"],
        top_n_targets=top_n,
        max_neighbors=max_nb,
        num_normal=num_norm,
    )
    st.session_state.graph_cache_key = graph_cache_key
    print(f"[PERF] build_graph_data: {time.perf_counter() - started:.3f}s")

graph_data = st.session_state.graph_cache_value
st.caption(
    f"Showing {len(graph_data['nodes'])} nodes · {len(graph_data['links'])} edges · click any node to investigate"
)

events = render_graph(
    graph_data,
    height=650,
    selected_txid=(st.session_state.selected_node or {}).get("txId"),
)

# Node selection remains independent from analysis. A node switch clears stale
# investigation content but never calls Azure automatically.
_select_node(events.get("node_clicked"))

analyze_request = events.get("analyze_transaction")
if analyze_request:
    _select_node(analyze_request)
    st.session_state.sidebar_open = True
    # Reuse an existing cached/visible initial analysis when the same
    # transaction is analyzed again; otherwise request it once.
    if st.session_state.initial_analysis_text is None:
        st.session_state.initial_analysis_pending = True
        st.session_state.initial_analysis_error = None
    st.rerun()

report_request = events.get("generate_report")
if report_request:
    print(f"[REPORT] generate_report event received: {report_request}")
    _select_node(report_request)
    txid = str(st.session_state.selected_node["txId"])
    print(f"[REPORT] generation starting | txid={txid} | session_id={st.session_state.session_id}")
    try:
        with st.spinner("Preparing report…"):
            pdf_bytes, filename = report_service.generate_report(
                st.session_state.session_id, st.session_state.selected_node
            )

        if not pdf_bytes:
            raise ValueError("report_service.generate_report returned empty PDF bytes")

        st.session_state.report_pdf_bytes = pdf_bytes
        st.session_state.report_filename = filename
        st.session_state.report_txid = txid
        st.session_state.report_error = None

        # Persist the generated PDF and its metadata. Firebase failure does not
        # block the user's immediate download; it is surfaced separately below.
        try:
            firebase_record = firebase_services.save_report(
                pdf_bytes=pdf_bytes,
                filename=filename,
                transaction_id=txid,
                status="Under Investigation",
            )
            st.session_state.report_storage_error = None
            print(
                f"[REPORT] Firebase save success | txid={txid} "
                f"| doc_id={firebase_record['document_id']} "
                f"| storage_path={firebase_record['storage_path']}"
            )
        except Exception as firebase_exc:
            st.session_state.report_storage_error = (
                "The report was generated and downloaded, but it could not be saved "
                "to Report History. Check the Firebase configuration and try again."
            )
            print(
                f"[REPORT] Firebase save failed | txid={txid} "
                f"| {type(firebase_exc).__name__}: {firebase_exc}"
            )
            import traceback
            traceback.print_exc()

        # New token on every successful generation. The graph component uses it
        # to auto-download exactly once after Streamlit reruns with the PDF data.
        st.session_state.report_download_token = uuid.uuid4().hex

        print(
            f"[REPORT] generation success | txid={txid} | filename={filename} "
            f"| bytes={len(pdf_bytes)} | token={st.session_state.report_download_token}"
        )
        st.rerun()
    except Exception as exc:
        import traceback

        st.session_state.report_pdf_bytes = None
        st.session_state.report_filename = None
        st.session_state.report_txid = None
        st.session_state.report_download_token = None
        st.session_state.report_error = "Could not generate the report. Please try again."
        print(f"[REPORT] generation failed | txid={txid} | {type(exc).__name__}: {exc}")
        traceback.print_exc()
        st.rerun()

if st.session_state.selected_node is None:
    st.info("Click a node in the graph to open its transaction details card.")

# 4. Investigation sidebar. This is a real Streamlit container with a stable
# key, so all widgets are structurally contained and CSS positions the whole
# workspace as one fixed left panel.
if st.session_state.sidebar_open and st.session_state.selected_node is not None:
    selected = st.session_state.selected_node

    with st.container(key="investigation_sidebar"):
        hcol1, hcol2 = st.columns([4, 1])
        hcol1.markdown(f"### 🔎 Transaction {selected['txId']}")
        if hcol2.button("✕", key="close_sidebar", help="Close investigation panel"):
            st.session_state.sidebar_open = False
            st.rerun()

        st.markdown("**Investigation Response**")
        with st.container(key="investigation_response_area"):
            if st.session_state.question_pending_id is not None:
                st.markdown("⏳ Answering the selected question...")
            elif st.session_state.question_error:
                st.markdown(
                    f'<div class="error-box">⚠️ {st.session_state.question_error}</div>',
                    unsafe_allow_html=True,
                )
            elif st.session_state.question_answer_text:
                st.markdown(st.session_state.question_answer_text)
            elif st.session_state.initial_analysis_pending:
                st.markdown("⏳ Running initial analysis...")
            elif st.session_state.initial_analysis_error:
                st.markdown(
                    f'<div class="error-box">⚠️ {st.session_state.initial_analysis_error}</div>',
                    unsafe_allow_html=True,
                )
            elif st.session_state.initial_analysis_text:
                st.markdown(st.session_state.initial_analysis_text)
            else:
                st.caption("No analysis is available yet.")

        st.markdown("**Suggested Questions**")
        questions_locked = (
            st.session_state.initial_analysis_text is None
            or st.session_state.initial_analysis_pending
            or st.session_state.question_pending_id is not None
        )

        for q_id, q_text in SUGGESTED_QUESTIONS:
            if st.button(
                q_text,
                key=f"btn_{q_id}",
                disabled=questions_locked,
                use_container_width=True,
            ):
                st.session_state.question_pending_id = q_id
                st.session_state.question_answer_text = None
                st.session_state.question_error = None
                st.rerun()


# 5. Execute pending LLM work only after the sidebar has been rendered with its
# loading state and all question buttons disabled. Then rerun once to display
# the returned text in the upper response area.
if st.session_state.sidebar_open and st.session_state.selected_node is not None:
    selected = st.session_state.selected_node

    if (
        st.session_state.initial_analysis_pending
        and st.session_state.initial_analysis_text is None
        and st.session_state.initial_analysis_error is None
    ):
        _run_initial_analysis(selected)
        st.rerun()

    if st.session_state.question_pending_id is not None:
        pending_question = st.session_state.question_pending_id
        _run_question(selected, pending_question)
        st.rerun()


# 6. Shared Report History. With no login system, all saved reports are shown.
render_report_history(storage_error=st.session_state.report_storage_error)
