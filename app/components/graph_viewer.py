import json
import streamlit.components.v1 as components

_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
  html,body{margin:0;padding:0;background:#0b0e14;overflow:hidden;font-family:-apple-system,Segoe UI,Roboto,sans-serif}
  #graph{width:100vw;height:100vh}
  #panel{position:fixed;top:16px;right:16px;width:300px;background:rgba(20,24,34,.93);color:#e8eaf0;
         border-radius:10px;padding:16px 18px;box-shadow:0 8px 24px rgba(0,0,0,.4);
         font-size:13px;line-height:1.55;display:none}
  #panel h3{margin:0 0 6px;font-size:14px;padding-right:20px}
  .lbl{color:#8c93a6;font-size:10px;text-transform:uppercase;letter-spacing:.05em;margin-top:9px}
  .val{color:#e8eaf0;word-break:break-word}
  .raw{color:#6b7280;font-size:10px;font-family:monospace;margin-top:2px}
  .rh{color:#ff6b6b;font-weight:600}.rl{color:#69db7c;font-weight:600}
  #pc{position:absolute;top:10px;right:12px;cursor:pointer;color:#8c93a6;
      font-size:15px;background:none;border:none}
  #pc:hover{color:#e8eaf0}
  #legend{position:fixed;top:16px;left:16px;color:#c4c9d4;font-size:11px;
          background:rgba(20,24,34,.8);padding:9px 13px;border-radius:8px}
  #legend span{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px}
</style>
</head>
<body>
<div id="graph"></div>
<div id="legend">
  <div><span style="background:#ff4d4d"></span>Suspicious target</div>
  <div><span style="background:#4d94ff"></span>Important neighbor</div>
  <div><span style="background:#6b7280"></span>Licit (comparison)</div>
  <div style="margin-top:5px;color:#8c93a6;font-size:10px">Click node · Drag to rotate · Scroll to zoom</div>
</div>
<div id="panel"></div>
<script src="https://unpkg.com/three@0.149.0/build/three.min.js"></script>
<script src="https://unpkg.com/3d-force-graph@1.71.3/dist/3d-force-graph.min.js"></script>
<script>
const data=__GRAPH_DATA__;
const panel=document.getElementById("panel");

function fmtRisk(r){
  if(r===null||r===undefined)return"n/a";
  const pct=(r*100).toFixed(1)+"%";
  return r>=0.5?`<span class="rh">${pct}</span>`:`<span class="rl">${pct}</span>`;
}

function hidePanel(){panel.style.display="none"}

function showPanel(n){
  panel.style.display="block";
  const icon=n.group==="target"?"🎯":n.group==="neighbor"?"🔗":"✅";
  panel.innerHTML=`
    <button id="pc">✕</button>
    <h3>${icon} ${n.group==="target"?"Target":"n.group==='neighbor'?'Neighbor':'Normal'"} Transaction</h3>
    <div class="val" style="font-size:11px;color:#8c93a6">txId: ${n.txId}</div>
    <div class="lbl">Predicted Risk</div>
    <div class="val">${fmtRisk(n.predicted_risk)}</div>
    <div class="lbl">GNN Importance</div>
    <div class="val">${n.gnn_importance.toFixed(4)}</div>
    <div class="lbl">SHAP — Increasing Risk</div>
    <div class="val">${n.shap_increasing_cat||"n/a"}</div>
    <div class="raw">${n.shap_increasing_raw||""}</div>
    <div class="lbl">SHAP — Decreasing Risk</div>
    <div class="val">${n.shap_decreasing_cat||"n/a"}</div>
    <div class="raw">${n.shap_decreasing_raw||""}</div>`;
  document.getElementById("pc").onclick=e=>{e.stopPropagation();hidePanel()};
}

const G=ForceGraph3D()(document.getElementById("graph"))
  .graphData(data)
  .backgroundColor("#0b0e14")
  .nodeLabel(n=>`${n.group.toUpperCase()} · ${n.txId}`)
  .nodeColor(n=>n.group==="target"?"#ff4d4d":n.group==="neighbor"?"#4d94ff":"#6b7280")
  .nodeVal(n=>n.group==="target"?14:3+9*n.gnn_importance)
  .linkWidth(l=>0.5+5*l.importance)
  .linkColor(()=>"rgba(255,255,255,0.25)")
  .linkDirectionalParticles(1)
  .linkDirectionalParticleWidth(l=>1+2*l.importance)
  .onNodeClick(n=>{
    showPanel(n);
    const dist=80,r=1+dist/Math.hypot(n.x,n.y,n.z);
    G.cameraPosition({x:n.x*r,y:n.y*r,z:n.z*r},n,800);
  })
  .onBackgroundClick(hidePanel);
</script>
</body>
</html>"""

def render_graph(graph_data_3d: dict, height: int = 720):
    html = _HTML.replace("__GRAPH_DATA__", __import__("json").dumps(graph_data_3d))
    components.html(html, height=height, scrolling=False)