"""ForceGraph3D V2 component for GraphShield.

The graph engine and visual interactions stay in JavaScript. The V2 component
bridge sends discrete node and Analyze actions back to Streamlit.
"""

import base64

import streamlit as st

_HTML = """
<div id="graph-shell">
<div id="graph"></div>
<div id="legend">
  <div><span style="background:#ff4d4d"></span>Suspicious target</div>
  <div><span style="background:#ffa64d"></span>Important neighbor</div>
  <div><span style="background:#4dbd74"></span>Normal / licit comparison</div>
  <div class="legend-help">Click node · Drag to rotate · Scroll to zoom</div>
</div>
<div id="panel"></div>
</div>
"""

_CSS = """
html,body{margin:0;padding:0;background:#0b0e14;overflow:hidden;font-family:-apple-system,Segoe UI,Roboto,sans-serif}
#graph-shell{position:relative;width:100%;height:100%;min-height:420px;overflow:hidden;background:#0b0e14}
#graph{width:100%;height:100%}
#panel{position:absolute;top:16px;right:16px;width:clamp(290px,28vw,370px);max-height:calc(100% - 32px);overflow-y:auto;
       background:rgba(20,24,34,.97);color:#e8eaf0;border:1px solid #2a3040;border-radius:12px;
       padding:16px 18px;box-sizing:border-box;box-shadow:0 8px 24px rgba(0,0,0,.45);
       font-size:12px;line-height:1.5;display:none;z-index:20}
#panel h3{margin:0 0 6px;font-size:14px;padding-right:20px}
.report-error{margin-top:10px;padding:9px 10px;border-radius:7px;background:#3a1f1f;border:1px solid #7a3a3a;color:#ffb0b0;font-size:11px}
.lbl{color:#8c93a6;font-size:10px;text-transform:uppercase;letter-spacing:.05em;margin-top:9px}
.val{color:#e8eaf0;word-break:break-word}
.raw{color:#9299aa;font-size:10px;font-family:monospace;margin-top:2px;word-break:break-word}
.rh{color:#ff6b6b;font-weight:600}.rl{color:#69db7c;font-weight:600}
#pc{position:absolute;top:10px;right:12px;cursor:pointer;color:#8c93a6;font-size:15px;background:none;border:none}
#pc:hover{color:#e8eaf0}
.actions{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:8px;margin-top:14px;padding-top:12px;border-top:1px solid #2a3040}
.action-btn{min-height:40px;padding:8px 10px;border-radius:7px;border:1px solid #3a4357;background:#232938;color:#f3f4f6;cursor:pointer;font-weight:600;font-size:11px;white-space:normal}
.action-btn:hover:not(:disabled){background:#30384a;border-color:#59647d}
.action-btn.primary{background:#6d4aff;border-color:#7e64ff;color:#fff}
.action-btn.primary:hover{background:#7a5cff}
.action-btn:disabled{opacity:.45;cursor:not-allowed}
#legend{position:absolute;top:16px;left:16px;max-width:min(300px,calc(100% - 32px));box-sizing:border-box;color:#c4c9d4;font-size:11px;background:rgba(20,24,34,.88);padding:9px 13px;border-radius:8px;z-index:10;pointer-events:none}
#legend span{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px}
.legend-help{margin-top:5px;color:#8c93a6;font-size:10px}
@media (max-width:900px){
  #legend{top:10px;left:10px;font-size:10px;padding:7px 9px}
  .legend-help{display:none}
  #panel{top:10px;right:10px;width:min(330px,calc(100% - 20px));max-height:calc(100% - 20px);padding:14px}
  .actions{grid-template-columns:1fr}
}
@media (max-width:560px){
  #panel{left:10px;right:10px;width:auto}
}
"""

_JS = r"""
function loadScript(src) {
  return new Promise((resolve, reject) => {
    if (window.ForceGraph3D && src.includes("3d-force-graph")) { resolve(); return; }
    if (window.THREE && src.includes("three")) { resolve(); return; }
    const existing = document.querySelector(`script[src="${src}"]`);
    if (existing) {
      existing.addEventListener("load", resolve, {once:true});
      existing.addEventListener("error", () => reject(new Error("Failed to load " + src)), {once:true});
      return;
    }
    const s = document.createElement("script");
    s.src = src;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("Failed to load " + src));
    document.head.appendChild(s);
  });
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, ch => ({
    '&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'
  })[ch]);
}

export default async function(component) {
  const { data, setTriggerValue, parentElement } = component;

  await loadScript("https://unpkg.com/three@0.149.0/build/three.min.js");
  await loadScript("https://unpkg.com/3d-force-graph@1.71.3/dist/3d-force-graph.min.js");

  const graphData = data.graph_data || {nodes:[], links:[]};
  const height = data.height || 650;
  const selectedTxId = data.selected_txid ? String(data.selected_txid) : null;
  const reportTxId = data.report_txid ? String(data.report_txid) : null;
  const reportPdfBase64 = data.report_pdf_base64 || null;
  const reportFilename = data.report_filename || "GraphShield_Report.pdf";
  const reportError = data.report_error || null;
  const reportDownloadToken = data.report_download_token || null;

  console.log("[REPORT][GRAPH] component state", {
    selectedTxId,
    reportTxId,
    hasPdf: Boolean(reportPdfBase64),
    pdfBase64Length: reportPdfBase64 ? reportPdfBase64.length : 0,
    reportFilename,
    reportDownloadToken,
    reportError
  });

  const graphEl = parentElement.querySelector("#graph");
  const panel = parentElement.querySelector("#panel");
  graphEl.style.height = height + "px";

  function fmtRisk(r){
    if(r===null||r===undefined)return"n/a";
    const pct=(Number(r)*100).toFixed(1)+"%";
    return Number(r)>=0.5?`<span class="rh">${pct}</span>`:`<span class="rl">${pct}</span>`;
  }

  function listOrNA(items){
    if(!Array.isArray(items) || items.length===0) return "n/a";
    return items.map(x=>`• ${escapeHtml(x)}`).join("<br>");
  }

  function hidePanel(){ panel.style.display="none"; }

  function nodePayload(n){
    return {txId:String(n.txId), group:n.group, node_index:n.id};
  }

  function showPanel(n){
    panel.style.display="block";
    const icon=n.group==="target"?"🎯":n.group==="neighbor"?"🔗":"✅";
    const label=n.group==="target"?"Target":(n.group==="neighbor"?"Neighbor":"Normal");
    panel.innerHTML=`
      <button id="pc" aria-label="Close transaction details">✕</button>
      <h3>${icon} ${label} Transaction</h3>
      <div class="lbl">Transaction ID</div><div class="val">${escapeHtml(n.txId)}</div>
      <div class="lbl">Prediction</div><div class="val">${escapeHtml(n.prediction || "n/a")}</div>
      <div class="lbl">True Label</div><div class="val">${escapeHtml(n.true_label || "n/a")}</div>
      <div class="lbl">Risk Score</div><div class="val">${fmtRisk(n.predicted_risk)}</div>
      <div class="lbl">GNN Importance</div><div class="val">${Number(n.gnn_importance || 0).toFixed(4)}</div>
      <div class="lbl">Positive SHAP Features</div><div class="val">${escapeHtml(n.shap_increasing_cat || "n/a")}</div>
      <div class="raw">${escapeHtml(n.shap_increasing_raw || "")}</div>
      <div class="lbl">Negative SHAP Features</div><div class="val">${escapeHtml(n.shap_decreasing_cat || "n/a")}</div>
      <div class="raw">${escapeHtml(n.shap_decreasing_raw || "")}</div>
      <div class="lbl">Transaction Profile Factors</div><div class="val">${listOrNA(n.transaction_profile_factors)}</div>
      <div class="lbl">Network Context Factors</div><div class="val">${listOrNA(n.network_context_factors)}</div>
      <div class="actions">
        <button id="analyze-btn" class="action-btn primary">Analyze Transaction</button>
        <button id="report-btn" class="action-btn">Generate Report</button>
      </div>
      ${reportError && selectedTxId === String(n.txId) ? `<div class="report-error">⚠️ ${escapeHtml(reportError)}</div>` : ""}`;

    panel.querySelector("#pc").onclick = e => { e.stopPropagation(); hidePanel(); };
    panel.querySelector("#analyze-btn").onclick = e => {
      e.stopPropagation();
      setTriggerValue("analyze_transaction", nodePayload(n));
    };
    panel.querySelector("#report-btn").onclick = e => {
      e.stopPropagation();
      const payload = nodePayload(n);
      console.log("[REPORT][GRAPH] Generate Report clicked", payload);
      setTriggerValue("generate_report", payload);
    };
  }

  function downloadReportOnce() {
    console.log("[REPORT][GRAPH] downloadReportOnce called");

    if (!reportPdfBase64) {
      console.log("[REPORT][GRAPH] download skipped: no PDF data");
      return;
    }
    if (!reportDownloadToken) {
      console.error("[REPORT][GRAPH] download skipped: missing report_download_token");
      return;
    }
    if (!reportTxId) {
      console.error("[REPORT][GRAPH] download skipped: missing report_txid");
      return;
    }

    const storageKey = "graphshield_report_download_token";
    const previousToken = sessionStorage.getItem(storageKey);
    if (previousToken === reportDownloadToken) {
      console.log("[REPORT][GRAPH] download skipped: token already downloaded", reportDownloadToken);
      return;
    }

    try {
      console.log("[REPORT][GRAPH] decoding PDF", {
        txid: reportTxId,
        filename: reportFilename,
        token: reportDownloadToken,
        base64Length: reportPdfBase64.length
      });

      const binary = atob(reportPdfBase64);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);

      const blob = new Blob([bytes], {type: "application/pdf"});
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = reportFilename || "GraphShield_Report.pdf";
      a.style.display = "none";
      document.body.appendChild(a);
      a.click();
      a.remove();

      sessionStorage.setItem(storageKey, reportDownloadToken);
      console.log("[REPORT][GRAPH] download triggered successfully", {
        filename: a.download,
        byteLength: bytes.length,
        token: reportDownloadToken
      });

      setTimeout(() => URL.revokeObjectURL(url), 3000);
    } catch (err) {
      console.error("[REPORT][GRAPH] download failed", err);
    }
  }

  downloadReportOnce();

  let G = parentElement.__graphShieldGraph;
  if (!G) {
    G = ForceGraph3D()(graphEl)
      .backgroundColor("#0b0e14")
      .nodeLabel(n=>`${String(n.group).toUpperCase()} · ${n.txId}`)
      .nodeColor(n=>n.group==="target"?"#ff4d4d":n.group==="neighbor"?"#ffa64d":"#4dbd74")
      .nodeVal(n=>n.group==="target"?14:3+9*Number(n.gnn_importance || 0))
      .linkWidth(l=>0.5+5*Number(l.importance || 0))
      .linkColor(()=>"rgba(255,255,255,0.25)")
      .linkDirectionalParticles(1)
      .linkDirectionalParticleWidth(l=>1+2*Number(l.importance || 0));
    parentElement.__graphShieldGraph = G;
  }

  G.graphData(graphData)
    .onNodeClick(n=>{
      showPanel(n);
      const norm=Math.hypot(n.x||0,n.y||0,n.z||0) || 1;
      const dist=80, r=1+dist/norm;
      G.cameraPosition({x:(n.x||0)*r,y:(n.y||0)*r,z:(n.z||0)*r},n,800);
    })
    .onNodeHover(n=>{ graphEl.style.cursor = n ? "pointer" : "default"; })
    .onBackgroundClick(()=>{ hidePanel(); graphEl.style.cursor="default"; });

  if (selectedTxId) {
    const selectedNode = graphData.nodes.find(n => String(n.txId) === selectedTxId);
    if (selectedNode) showPanel(selectedNode);
  }
}
"""

_component = st.components.v2.component(
    "graphshields_force_graph_v3",
    html=_HTML,
    css=_CSS,
    js=_JS,
)


def render_graph(
    graph_data_3d: dict,
    height: int = 720,
    key: str = "force_graph_3d",
    selected_txid: str | None = None,
):
    """Render the graph and return discrete component events.

    Returns a dict with optional ``node_clicked`` and ``analyze_transaction``
    payloads. Trigger callbacks are registered explicitly so the attributes are
    always present on the V2 ComponentResult.
    """
    # Read report state directly from Streamlit. This keeps the public
    # render_graph() call unchanged while allowing the graph card to switch
    # while keeping the card button labeled Generate Report; the PDF downloads
    # automatically once after report generation succeeds.
    report_pdf_bytes = st.session_state.get("report_pdf_bytes")
    report_filename = st.session_state.get("report_filename")
    report_txid = st.session_state.get("report_txid")
    report_error = st.session_state.get("report_error")
    report_download_token = st.session_state.get("report_download_token")

    print(
        "[REPORT][GRAPH] render state | "
        f"selected_txid={selected_txid} | report_txid={report_txid} | "
        f"has_pdf={bool(report_pdf_bytes)} | bytes={len(report_pdf_bytes) if report_pdf_bytes else 0} | "
        f"filename={report_filename} | token={report_download_token} | error={report_error}"
    )

    result = _component(
        data={
            "graph_data": graph_data_3d,
            "height": height,
            "selected_txid": selected_txid,
            "report_pdf_base64": (
                base64.b64encode(report_pdf_bytes).decode("ascii")
                if report_pdf_bytes
                else None
            ),
            "report_filename": report_filename,
            "report_txid": report_txid,
            "report_error": report_error,
            "report_download_token": report_download_token,
        },
        on_node_clicked_change=lambda: None,
        on_analyze_transaction_change=lambda: None,
        on_generate_report_change=lambda: None,
        key=key,
    )
    if result is None:
        return {"node_clicked": None, "analyze_transaction": None, "generate_report": None}
    return {
        "node_clicked": getattr(result, "node_clicked", None),
        "analyze_transaction": getattr(result, "analyze_transaction", None),
        "generate_report": getattr(result, "generate_report", None),
    }
