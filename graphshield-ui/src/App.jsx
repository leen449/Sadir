// App.jsx — GraphShield, faithful port of dashboard.py.
// Node card (top-right float) = info + Analyze/Report only.
// Analyze opens a left-sliding Investigation sidebar holding the streaming
// response + Suggested Questions (locked until initial analysis completes).
// Graph has directional particles + theme-aware link colors.

import { useEffect, useRef, useState, useCallback } from "react";
import ForceGraph3D from "react-force-graph-3d";
import "./index.css";
import logoLight from "../../app/assets/Gemini_Generated_Image_bi207cbi207cbi20.png";
import logoDark from "../../app/assets/photo_5949691588562849333_y-removebg-preview.png";
import VerifyGate from "./VerifyGate";


const SESSION_ID = crypto.randomUUID?.() ?? String(Math.random()).slice(2);
const GRAPH_BG_LIGHT = "#c7d7e1";
const GRAPH_BG_DARK = "#526c76";
// Links: white on dark, dark-teal on light (fixes invisible light-mode edges).
const LINK_DARK = "rgba(255,255,255,0.25)";
const LINK_LIGHT = "rgba(6,49,66,0.35)";

const nodeColor = (n) =>
  n.group === "target" ? "#ff4d4d" : n.group === "neighbor" ? "#f6cfc7" : "#b9d7e3";
const nodeVal = (n) => (n.group === "target" ? 14 : 3 + 9 * Number(n.gnn_importance || 0));

const QUESTIONS = [
  { id: "question_1", label: "What drove this prediction?" },
  { id: "question_2", label: "How did neighbors influence it?" },
  { id: "question_3", label: "What reduced the risk?" },
];

const listOrNA = (v) =>
  Array.isArray(v) ? (v.length ? v.join(", ") : "n/a") : v || "n/a";

// slider fill percentage (for the red/pink filled track)
const pct = (v, min, max) => Math.round(((v - min) / (max - min)) * 100);

// "11 Jul 2026" style date key for the filter dropdown
function dateKey(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d)) return null;
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  const s = d.toLocaleString("en-US", {
    month: "short", day: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
  return s.replace(/(\d{4}),/, "$1 ·");
}

export default function App() {
  const [graph, setGraph] = useState({ nodes: [], links: [] });
  const [selected, setSelected] = useState(null);
  const [verified, setVerified] = useState(false);

  // investigation sidebar state
  const [invOpen, setInvOpen] = useState(false);
  const [analysisText, setAnalysisText] = useState("");
  const [analysisPending, setAnalysisPending] = useState(false); // initial analysis in-flight
  const [qPending, setQPending] = useState(null);                // question id currently streaming
  const [responseText, setResponseText] = useState("");          // what shows in the response box

  const [reporting, setReporting] = useState(false);
  const [reportError, setReportError] = useState("");
  const [history, setHistory] = useState([]);
  const [dateFilter, setDateFilter] = useState("All Reports");
  const [settingsOpen, setSettingsOpen] = useState(false);

  const [topN, setTopN] = useState(15);
  const [maxNb, setMaxNb] = useState(25);
  const [numNorm, setNumNorm] = useState(10);

  const [dark, setDark] = useState(
    () => window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? true
  );

  const esRef = useRef(null);
  const fgRef = useRef(null);
  const debounceRef = useRef(null);

  useEffect(() => {
    document.body.classList.toggle("gs-dark", dark);
    document.body.classList.toggle("gs-light", !dark);
  }, [dark]);

  const loadGraph = useCallback(() => {
    fetch(`/api/graph?top_n_targets=${topN}&max_neighbors=${maxNb}&num_normal=${numNorm}`)
      .then((r) => r.json()).then(setGraph)
      .catch((e) => console.error("graph load failed", e));
  }, [topN, maxNb, numNorm]);

  useEffect(() => {
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(loadGraph, 250);
    return () => clearTimeout(debounceRef.current);
  }, [loadGraph]);

  useEffect(() => { loadHistory(); }, []);
  useEffect(() => () => esRef.current?.close(), []);

  function handleNodeClick(node) {
    esRef.current?.close();
    setSelected(node);
    // clicking a different node closes the investigation view
    setInvOpen(false);
    setAnalysisText(""); setResponseText(""); setQPending(null); setAnalysisPending(false);
    const distance = 120;
    const hyp = Math.hypot(node.x || 0, node.y || 0, node.z || 0) || 1;
    const r = 1 + distance / hyp;
    fgRef.current?.cameraPosition(
      { x: (node.x || 0) * r, y: (node.y || 0) * r, z: (node.z || 0) * r }, node, 800
    );
  }

  // Generic SSE runner. onDone lets us flip pending flags per call type.
  function stream({ questionId, onToken, onDone }) {
    if (!selected) return;
    esRef.current?.close();
    const params = new URLSearchParams({
      txid: selected.txId, node_index: String(selected.id),
      request_type: questionId ? "question" : "initial_analysis", session_id: SESSION_ID,
    });
    if (questionId) params.set("question_id", questionId);
    const es = new EventSource(`/api/analysis/stream?${params}`);
    esRef.current = es;
    es.onmessage = (ev) => onToken(ev.data.replaceAll("\\n", "\n"));
    es.addEventListener("done", () => { es.close(); onDone?.(null); });
    es.addEventListener("error", (ev) => { es.close(); onDone?.(ev.data || "stream failed"); });
  }

  // Analyze button on the card -> open sidebar + auto-run initial analysis.
  function openInvestigation() {
    if (!selected) return;
    setInvOpen(true);
    setAnalysisText(""); setResponseText(""); setQPending(null);
    setAnalysisPending(true);
    stream({
      questionId: null,
      onToken: (t) => { setAnalysisText((p) => p + t); setResponseText((p) => p + t); },
      onDone: (err) => {
        setAnalysisPending(false);
        if (err) setResponseText((p) => p + `\n[error] ${err}`);
      },
    });
  }

  function askQuestion(qid) {
    setQPending(qid);
    setResponseText("");
    stream({
      questionId: qid,
      onToken: (t) => setResponseText((p) => p + t),
      onDone: (err) => {
        setQPending(null);
        if (err) setResponseText((p) => p + `\n[error] ${err}`);
      },
    });
  }

  function closeInvestigation() {
    esRef.current?.close();
    setInvOpen(false);
    setQPending(null);
  }

  async function downloadReport() {
    if (!selected) return;
    setReporting(true); setReportError("");
    const params = new URLSearchParams({
      session_id: SESSION_ID, txid: selected.txId, node_index: String(selected.id),
    });
    try {
      const res = await fetch(`/api/reports?${params}`, { method: "POST" });
      if (!res.ok) {
        const msg = await res.json().catch(() => ({}));
        throw new Error(msg.detail || `Report failed (${res.status})`);
      }
      const blob = await res.blob();
      const disp = res.headers.get("Content-Disposition") || "";
      const m = disp.match(/filename="(.+?)"/);
      const filename = m ? m[1] : `report_${selected.txId}.pdf`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = filename;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
      loadHistory();
    } catch (e) {
      setReportError(e.message);
    } finally {
      setReporting(false);
    }
  }

  async function loadHistory() {
    try {
      const res = await fetch("/api/reports/history?limit=50");
      setHistory(await res.json());
    } catch (e) { console.error("history load failed", e); }
  }

  function downloadFromHistory(sp) {
    window.open(`/api/reports/download?storage_path=${encodeURIComponent(sp)}`, "_blank");
  }

  const riskText = selected?.predicted_risk != null
    ? `High Risk · ${(Number(selected.predicted_risk) * 100).toFixed(1)}%` : "Risk n/a";

  // Questions locked until the initial analysis has finished (matches dashboard.py).
  const questionsLocked = analysisPending || !analysisText || qPending !== null;
  const linkColor = dark ? LINK_DARK : LINK_LIGHT;

  return (
    <>
      {!verified && <VerifyGate onVerified={() => setVerified(true)} />}
      <div className={verified ? "" : "app-locked"}>
        <header className="gs-main-header">
          <div className="gs-brand">
            <div className="gs-logo"><img src={dark ? logoDark : logoLight} alt="GraphShield Logo" /></div>
            <div>
              <h1>GraphShield</h1>
              <p>Smarter Insights. Safer Finance.</p>
            </div>
          </div>
          <button className="gs-icon-btn" onClick={() => setDark((d) => !d)} title="Toggle theme">
            {dark ? "\u2600" : "\u263E"}
          </button>
        </header>

      {/* ===== Investigation sidebar (slides in from left) ===== */}
      <div className={`investigation ${invOpen ? "open" : ""}`}>
        {selected && (
          <>
            <div className="inv-head">
              <h3>Transaction {selected.txId}</h3>
              <button className="inv-close" onClick={closeInvestigation}>{"\u2715"}</button>
            </div>

            <div className="inv-label">Investigation Response</div>
            <div className="inv-response">
              {responseText
                ? (<>{responseText}{(analysisPending || qPending) && <span style={{ opacity: .5 }}>▌</span>}</>)
                : analysisPending ? "⏳ Running initial analysis..."
                : qPending ? "⏳ Answering the selected question..."
                : "No analysis is available yet."}
            </div>

            <div className="inv-label">Suggested Questions</div>
            {QUESTIONS.map((q) => (
              <button key={q.id} className="qbtn" disabled={questionsLocked} onClick={() => askQuestion(q.id)}>
                {q.label}
              </button>
            ))}
          </>
        )}
      </div>

      <div className="page">
        {/* ===== Graph Settings ===== */}
        <div className="settings">
          <div className={`settings-head ${settingsOpen ? "open" : ""}`} onClick={() => setSettingsOpen((o) => !o)}>
            <span>{"\u25B8"}</span> {"\u2699"} Graph Settings
          </div>
          <div className={`sliders-outer ${settingsOpen ? "open" : ""}`}>
            <div className="sliders-inner">
              <div className="sliders">
                <div className="slider-cell">
                  <label>Target Transactions</label><div className="sval">{topN}</div>
                  <input type="range" min="5" max="30" value={topN} style={{ "--pct": `${pct(topN, 5, 30)}%` }}
                    onChange={(e) => setTopN(+e.target.value)} />
                </div>
                <div className="slider-cell">
                  <label>Maximum Neighbors per Target</label><div className="sval">{maxNb}</div>
                  <input type="range" min="10" max="40" value={maxNb} style={{ "--pct": `${pct(maxNb, 10, 40)}%` }}
                    onChange={(e) => setMaxNb(+e.target.value)} />
                </div>
                <div className="slider-cell">
                  <label>Normal Nodes</label><div className="sval">{numNorm}</div>
                  <input type="range" min="5" max="20" value={numNorm} style={{ "--pct": `${pct(numNorm, 5, 20)}%` }}
                    onChange={(e) => setNumNorm(+e.target.value)} />
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="count-caption">
          Showing {graph.nodes.length} nodes · {graph.links.length} edges · click any node to investigate
        </div>

        {/* ===== Graph + card + legend ===== */}
        <div className="graph-wrap">
          <div className="legend">
            <div className="legend-title">Legend</div>
            <div className="legend-row"><span style={{ background: "#ff4d4d" }} />Suspicious target</div>
            <div className="legend-row"><span style={{ background: "#f6cfc7" }} />Important neighbor</div>
            <div className="legend-row"><span style={{ background: "#b9d7e3" }} />Normal / licit comparison</div>
            <div className="legend-help">Click node · Drag to rotate · Scroll to zoom</div>
          </div>

          {selected && (
            <div className="panel">
              <button className="pc" onClick={() => setSelected(null)}>{"\u2715"}</button>
              <div className="panel-top">
                <h3>{selected.txId}</h3>
                <div className="risk-pill">{riskText}</div>
              </div>
              <div className="info-grid">
                <div className="info-box"><div className="lbl">Prediction</div><div className="val">{selected.prediction || "n/a"}</div></div>
                <div className="info-box"><div className="lbl">True Label</div><div className="val">{selected.true_label || "n/a"}</div></div>
                <div className="info-box">
                  <div className="lbl">Positive SHAP</div>
                  <div className="val">{selected.shap_increasing_cat || "n/a"}</div>
                  <div className="raw">{selected.shap_increasing_raw || ""}</div>
                </div>
                <div className="info-box">
                  <div className="lbl">Negative SHAP</div>
                  <div className="val">{selected.shap_decreasing_cat || "n/a"}</div>
                  <div className="raw">{selected.shap_decreasing_raw || ""}</div>
                </div>
                <div className="info-box wide"><div className="lbl">GNN Importance</div><div className="val">{Number(selected.gnn_importance || 0).toFixed(4)}</div></div>
                <div className="info-box"><div className="lbl">Transaction Profile Factors</div><div className="val">{listOrNA(selected.transaction_profile_factors)}</div></div>
                <div className="info-box"><div className="lbl">Network Context Factors</div><div className="val">{listOrNA(selected.network_context_factors)}</div></div>
              </div>
              <div className="actions">
                <button className="action-btn" onClick={openInvestigation}>Analyze Transaction</button>
                <button className="action-btn" onClick={downloadReport} disabled={reporting}>
                  {reporting ? "Generating…" : "Generate Report"}
                </button>
              </div>
              {reportError && <div className="report-error">⚠️ {reportError}</div>}
            </div>
          )}

          <ForceGraph3D
            ref={fgRef}
            graphData={graph}
            nodeId="id"
            nodeLabel={(n) => `${n.txId} (${n.prediction})`}
            nodeColor={nodeColor}
            nodeVal={nodeVal}
            linkColor={() => linkColor}
            linkWidth={(l) => 0.5 + 5 * Number(l.importance || 0)}
            linkDirectionalParticles={1}
            linkDirectionalParticleWidth={(l) => 1 + 2 * Number(l.importance || 0)}
            linkDirectionalParticleColor={() => linkColor}
            onNodeClick={handleNodeClick}
            backgroundColor={dark ? GRAPH_BG_DARK : GRAPH_BG_LIGHT}
          />
        </div>

        {/* ===== Report History ===== */}
        <div className="history">
          <div className="history-head">
            <h2>Report History</h2>
            {history.length > 0 && (
              <select className="history-filter" value={dateFilter} onChange={(e) => setDateFilter(e.target.value)}>
                <option>All Reports</option>
                {[...new Set(history.map((r) => dateKey(r.generated_at)).filter(Boolean))].map((d) => (
                  <option key={d}>{d}</option>
                ))}
              </select>
            )}
          </div>

          {history.length === 0 && <p className="count-caption" style={{ margin: 0 }}>No reports yet.</p>}

          {history
            .filter((r) => dateFilter === "All Reports" || dateKey(r.generated_at) === dateFilter)
            .map((r) => (
              <div className="hist-card" key={r.document_id}>
                <h3>{r.report_id || r.document_id}</h3>
                <div className="hist-meta">Transaction ID: <strong>{r.transaction_id}</strong></div>
                <div className="hist-meta">Generated: {fmtDate(r.generated_at)}</div>
                <span className="report-history-status">{r.status || "Generated"}</span>

                {/* 3-dot menu (native <details>, mirrors report_history.py) */}
                <details className="report-menu">
                  <summary>{"\u22EE"}</summary>
                  <div className="report-menu-panel">
                    <span className="report-download-link" onClick={() => downloadFromHistory(r.storage_path)}>
                      Download PDF
                    </span>
                  </div>
                </details>
              </div>
            ))}
        </div>
      </div>
    </div>
    </>
  );
}