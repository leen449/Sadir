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
import threading
from concurrent.futures import ThreadPoolExecutor

import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
_BACKEND_ROOT = os.path.join(os.path.dirname(__file__), "..", "backend")
sys.path.insert(0, os.path.abspath(_BACKEND_ROOT))



from app.components.data_loader import load_all
from app.components.graph_builder import build_graph_data
from app.components.graph_viewer import render_graph
from app.components.report_history import render_report_history
from app.backend.security.validation import ValidationError
from app.backend.services.llm_service import generate_explanation, generate_explanation_stream
from app.backend.services.transaction_service import SelectedNode, build_context
from app.backend.utils.cache import executive_summary_cache
from app.backend.services import firebase_services, report_service

st.set_page_config(
    page_title="Investigation Workspace — GraphShield",
    layout="wide",
    page_icon="🕵️",
)

st.markdown(
    """
<style>
/* Unified Slider Fix */
div[data-testid="stSlider"] div[role="slider"] {
    background: #f6c2bc !important;
    background-color: #f6c2bc !important;
    border-color: #f6c2bc !important;
}

div[data-testid="stSlider"] div[data-track="true"] > div,
div[data-testid="stSlider"] *[style*="rgb(255, 75, 75)"],
div[data-testid="stSlider"] *[style*="#ff4b4b"] {
    background: #f6c2bc !important;
    background-color: #f6c2bc !important;
}
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

def render_topbar():
    """Sticky, frosted-glass "GraphShield" header + full-page light/dark theme.

    Design notes:
      * Default (no body class) = DARK, matching the existing app, so there is
        no light-flash on first paint. Light mode adds a `gs-light` class to the
        page <body>; the theme rules below key off that class, so the toggle
        controls the whole page, not just the header.
      * Streamlit's own top chrome (Deploy / Stop / running status / the "..."
        menu) is hidden, and its header strip is made transparent so the glass
        header shows through.
      * The AML-GNN / Analyst pills and login button are intentionally omitted.
    """
    import base64
    from pathlib import Path
    _logo_path = Path(__file__).parent.parent / "assets" / "Gemini_Generated_Image_bi207cbi207cbi20.png"
    try:
        _logo_src = "data:image/jpeg;base64," + base64.b64encode(_logo_path.read_bytes()).decode("ascii")
    except FileNotFoundError:
        _logo_src = "app/assets/photo_5949691588562849331_y-removebg-preview.png"

    # Dark-mode logo. Drop your dark-theme art at assets/logo_dark.png; if it's
    # missing we fall back to the light logo so nothing breaks.
    _logo_path_dark = Path(__file__).parent.parent / "assets" / "logo_dark.png"
    try:
        _logo_src_dark = "data:image/png;base64," + base64.b64encode(_logo_path_dark.read_bytes()).decode("ascii")
    except FileNotFoundError:
        _logo_src_dark = _logo_src

    st.markdown(
        """
<style>
/* ---- hide Streamlit's default top chrome; let the glass header show ---- */
[data-testid="stHeader"] { background: transparent !important; pointer-events: none !important; }
[data-testid="stToolbar"], [data-testid="stToolbarActions"], [data-testid="stStatusWidget"],
[data-testid="stDeployButton"], [data-testid="stMainMenu"], #MainMenu,
[data-testid="stDecoration"] { display: none !important; }

/* ---- header (DARK is the default; gs-light overrides to the glass look) ---- */
[data-testid="stAppViewContainer"] .block-container { padding-top: 120px; }
.gs-main-header {
  position: fixed; top: 0; left: 0; right: 0; height: 96px;
  display: flex; align-items: center; justify-content: space-between;
  gap: 20px; padding: 16px 28px; z-index: 1000;
  font-family: "Segoe UI", Tahoma, Arial, sans-serif;
  background: rgba(3,31,45,.72);
  border-bottom: 1px solid rgba(255,255,255,.12);
  box-shadow: 0 10px 35px rgba(0,0,0,.20);
  backdrop-filter: blur(18px); -webkit-backdrop-filter: blur(18px);
}
body.gs-light .gs-main-header {
  background: rgba(255,255,255,.72);
  border-bottom: 1px solid rgba(216,227,234,.72);
  box-shadow: 0 10px 35px rgba(6,49,66,.055);
}
.gs-brand { display: flex; align-items: center; gap: 14px; }
.gs-logo {
  width: 69px;
  height: 60px;
  background: #F8F8F7;
  border-radius: 18px;
  display: grid;
  place-items: center;
  overflow: hidden;
  border: 1px solid rgba(6,49,66,.08);
  box-shadow: 0 12px 30px rgba(6,49,66,.12);
}
.gs-logo img {
  width: 95%;
  height: 98%;
  object-fit: contain;
  transform: translateY(-2px);
}
/* Theme-swapped logo: dark mode shows the dark art, light mode the light art. */
.gs-logo .gs-logo-dark { display: block; }
.gs-logo .gs-logo-light { display: none; }
body.gs-light .gs-logo .gs-logo-dark { display: none; }
body.gs-light .gs-logo .gs-logo-light { display: block; }
.gs-brand h1 { margin: 0; font-size: 20px; color: #fff; }
body.gs-light .gs-brand h1 { color: #063142; }
.gs-brand p {
  margin: 5px 0 0; font-size: 9px; letter-spacing: 1.7px;
  color: #b9d7e3; text-transform: uppercase; white-space: nowrap;
}
body.gs-light .gs-brand p { color: #6b7c88; }
.gs-header-actions { display: flex; align-items: center; gap: 12px; }
.gs-icon-btn {
  width: 48px; height: 48px; border: 1px solid rgba(255,255,255,.14);
  background: rgba(255,255,255,.07); color: #fff; border-radius: 50%;
  cursor: pointer; box-shadow: 0 12px 35px rgba(0,0,0,.18);
  font-size: 19px; font-weight: 900; display: grid; place-items: center;
  backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
}
body.gs-light .gs-icon-btn {
  background: rgba(255,255,255,.62); border-color: rgba(216,227,234,.85); color: #063142;
  box-shadow: 0 12px 35px rgba(6,49,66,.06);
}

/* ---- WHOLE-PAGE light theme (dark is the app's existing look) ---- */
body.gs-light [data-testid="stAppViewContainer"],
body.gs-light .stApp,
body.gs-light [data-testid="stMarkdownContainer"],
body.gs-light [data-testid="stMarkdownContainer"] p,
body.gs-light label, body.gs-light .stCaption,
body.gs-light h1, body.gs-light h2, body.gs-light h3,
body.gs-light h4, body.gs-light h5, body.gs-light h6 { color: #063142 !important; }
body.gs-light .st-key-investigation_sidebar {
  background: #ffffff !important; border-right: 1px solid #d8e3ea !important;
  box-shadow: 4px 0 24px rgba(6,49,66,.10) !important;
}
body.gs-light .st-key-investigation_response_area {
  background: #f8fbfc !important; border: 1px solid #d8e3ea !important; color: #063142 !important;
}
/* ---- Graph Settings card: rounded stat-card shape + corner arc ---- */
[data-testid="stExpander"] details {
  position: relative !important;
  overflow: hidden !important;
  border-radius: 24px !important;
  background: rgba(58,79,89,1.000) !important;
  border: 1px solid rgba(255,255,255,.16) !important;
  box-shadow: 0 20px 70px rgba(0,0,0,.35) !important;
}
[data-testid="stExpander"] details::before {
  content: "";
  position: absolute;
  width: 120px;
  height: 120px;
  border-radius: 50%;
  right: -45px;
  top: -55px;
  background: rgba(255,255,255,.08);
  pointer-events: none;
  z-index: 0;
}
[data-testid="stExpander"] details > * {
  position: relative;
  z-index: 1;
}
[data-testid="stExpander"] summary {
  background: rgba(46,73,82,1.000) !important;
  color: #ffffff !important;
  border: 0 !important;
}

body.gs-light [data-testid="stExpander"] details {
  background: #ffffff !important;
  border: 1px solid #d8e3ea !important;
  border-radius: 24px !important;
  box-shadow: 0 20px 55px rgba(6,49,66,.13) !important;
}
body.gs-light [data-testid="stExpander"] details::before {
  background: rgba(6,49,66,.06);
}
body.gs-light [data-testid="stExpander"] summary,
body.gs-light [data-testid="stExpander"] summary:hover {
  background: rgba(248,251,252,.86) !important;
  color: #063142 !important;
  border: 0 !important;
}
body.gs-light .stButton > button {
  background: #ffffff !important; color: #063142 !important; border: 1px solid #d8e3ea !important;
}
body.gs-light [data-baseweb="input"] input,
body.gs-light [data-baseweb="select"] > div {
  background: #ffffff !important; color: #063142 !important;
}

/* ---- Investigation side panel: card look for background + response area, restyled chips + close (both themes) ---- */
/* DARK (default) --- the whole sidebar reads as one dark teal card */
/* Streaming-without-rerun: the questions block is emitted BEFORE the response
   block in source order so a click can be handled and the response area can
   stream in the same render pass. Restore visual order: answer on top,
   questions at the bottom. Because Streamlit wraps every keyed container in
   several ancestor divs, .st-key-* elements are NOT direct children of the
   sidebar, so `order` on them has no effect. Instead: make every plausible
   flex-capable ancestor inside the sidebar a flex column, and use :has() at
   several nesting depths to reach the positional wrapper Streamlit put around
   our keyed containers. Redundant selectors ensure at least one matches. */
.st-key-investigation_sidebar,
.st-key-investigation_sidebar > div,
.st-key-investigation_sidebar > div > div,
.st-key-investigation_sidebar [data-testid="stVerticalBlockBorderWrapper"],
.st-key-investigation_sidebar [data-testid="stVerticalBlockBorderWrapper"] > div,
.st-key-investigation_sidebar [data-testid="stVerticalBlock"] {
  display: flex !important;
  flex-direction: column !important;
}
.st-key-investigation_sidebar *:has(> .st-key-investigation_response_wrap),
.st-key-investigation_sidebar *:has(> * > .st-key-investigation_response_wrap),
.st-key-investigation_sidebar *:has(> * > * > .st-key-investigation_response_wrap) {
  order: 1 !important;
}
.st-key-investigation_sidebar *:has(> .st-key-investigation_questions_area),
.st-key-investigation_sidebar *:has(> * > .st-key-investigation_questions_area),
.st-key-investigation_sidebar *:has(> * > * > .st-key-investigation_questions_area) {
  order: 2 !important;
}
.st-key-investigation_sidebar {
  background: rgba(58,79,89,1.000) !important;
  border-right: 1px solid rgba(255,255,255,.10) !important;
  box-shadow: 4px 0 32px rgba(0,0,0,.45), inset 0 1px 0 rgba(255,255,255,.06) !important;
  padding: 20px 20px 28px 20px !important;
}
.st-key-investigation_sidebar h3,
.st-key-investigation_sidebar [data-testid="stMarkdownContainer"] strong,
.st-key-investigation_sidebar [data-testid="stMarkdownContainer"] p,
.st-key-investigation_sidebar [data-testid="stMarkdownContainer"] {
  color: #ffffff !important;
}
/* The response area becomes the big rounded inner card in the mockup */
.st-key-investigation_sidebar .st-key-investigation_response_area {
  background: rgba(8,50,64,.46) !important;
  border: 1px solid rgba(255,255,255,.12) !important;
  border-radius: 22px !important;
  padding: 18px 20px !important;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.05) !important;
  color: #ffffff !important;
}
.st-key-investigation_sidebar .st-key-investigation_response_area [data-testid="stMarkdownContainer"],
.st-key-investigation_sidebar .st-key-investigation_response_area [data-testid="stMarkdownContainer"] p,
.st-key-investigation_sidebar .st-key-investigation_response_area .stCaption {
  color: #e6eef3 !important;
}
/* Suggested-question chips: pill, translucent -- kept stacked (no columns changes) */
.st-key-investigation_sidebar .stButton > button {
  background: rgba(8,50,64,.46) !important;
  color: #ffffff !important;
  border: 1px solid rgba(255,255,255,.14) !important;
  border-radius: 999px !important;
  padding: 10px 18px !important;
  font-weight: 600 !important;
  box-shadow: none !important;
  transition: background .18s ease, transform .18s ease !important;
}
.st-key-investigation_sidebar .stButton > button:hover:not(:disabled) {
  background: rgba(255,255,255,.12) !important;
  transform: translateY(-1px);
}
.st-key-investigation_sidebar .stButton > button:disabled {
  opacity: .55 !important;
  color: rgba(255,255,255,.65) !important;
}
/* Close (✕) button: circular chip matched to the graph card's #pc exactly */
.st-key-investigation_sidebar .st-key-close_sidebar button,
.st-key-investigation_sidebar .stButton > button[kind="secondary"][aria-label*="Close"] {
  width: 40px !important; height: 40px !important;
  min-width: 40px !important; max-width: 40px !important;
  padding: 0 !important;
  border-radius: 50% !important;
  background: rgba(31,63,75,1) !important;
  border: 1px solid rgba(255,255,255,.22) !important;
  color: rgba(255,255,255,.92) !important;
  font-size: 15px !important;
  font-weight: 400 !important;
  line-height: 1 !important;
  display: flex !important; align-items: center !important; justify-content: center !important;
  box-shadow: 0 6px 16px rgba(0,0,0,.28) !important;
}
.st-key-investigation_sidebar .st-key-close_sidebar button:hover:not(:disabled),
.st-key-investigation_sidebar .stButton > button[kind="secondary"][aria-label*="Close"]:hover:not(:disabled) {
  color: #fff !important;
  background: rgba(82,100,109,1) !important;
  transform: none !important;
}

/* LIGHT mode --- off-white card matching the light mockup */
body.gs-light .st-key-investigation_sidebar {
  background: #ffffff !important;
  border-right: 1px solid #d8e3ea !important;
  box-shadow: 4px 0 24px rgba(6,49,66,.10) !important;
}
body.gs-light .st-key-investigation_sidebar h3,
body.gs-light .st-key-investigation_sidebar [data-testid="stMarkdownContainer"] strong,
body.gs-light .st-key-investigation_sidebar [data-testid="stMarkdownContainer"] p,
body.gs-light .st-key-investigation_sidebar [data-testid="stMarkdownContainer"] {
  color: #063142 !important;
}
body.gs-light .st-key-investigation_sidebar .st-key-investigation_response_area {
  background: #f4f8fb !important;
  border: 1px solid #d8e3ea !important;
  color: #063142 !important;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.9) !important;
}
body.gs-light .st-key-investigation_sidebar .st-key-investigation_response_area [data-testid="stMarkdownContainer"],
body.gs-light .st-key-investigation_sidebar .st-key-investigation_response_area [data-testid="stMarkdownContainer"] p {
  color: #063142 !important;
}
body.gs-light .st-key-investigation_sidebar .stButton > button {
  background: #eef4f7 !important;
  color: #063142 !important;
  border: 1px solid #d8e3ea !important;
}
body.gs-light .st-key-investigation_sidebar .stButton > button:hover:not(:disabled) {
  background: #e4edf2 !important;
}
body.gs-light .st-key-investigation_sidebar .st-key-close_sidebar button {
  background: #f0f5f8 !important;
  border: 1px solid #d8e3ea !important;
  color: #063142 !important;
}

/* ---- Close (✕) chip + tooltip: theme-aware in light mode ---- */
/* Baseweb renders tooltips into a portal at the root of <body>, so they inherit
   the app's dark theme by default. In light mode, retheme the tooltip to a light
   pill so it doesn't look like a stray dark blob on a white background. */
body.gs-light div[data-baseweb="tooltip"],
body.gs-light div[data-baseweb="tooltip"] *,
body.gs-light [role="tooltip"] {
  background: #ffffff !important;
  color: #063142 !important;
  border: 1px solid #d8e3ea !important;
  box-shadow: 0 8px 22px rgba(6,49,66,.12) !important;
  border-radius: 8px !important;
}
/* Baseweb sometimes paints the tooltip arrow via ::before/::after; retheme too */
body.gs-light div[data-baseweb="tooltip"]::before,
body.gs-light div[data-baseweb="tooltip"]::after {
  background: #ffffff !important; border-color: #d8e3ea !important;
}

/* Restyle the ✕ chip in light mode so it's a soft, clearly-interactive pill */
body.gs-light .st-key-investigation_sidebar .st-key-close_sidebar button {
  background: #eef4f7 !important;
  color: #063142 !important;
  border: 1px solid #cfdde5 !important;
  box-shadow: 0 2px 6px rgba(6,49,66,.06) !important;
  font-size: 16px !important;
  line-height: 1 !important;
}
body.gs-light .st-key-investigation_sidebar .st-key-close_sidebar button:hover {
  background: #e0ebf1 !important;
  border-color: #b8ccd7 !important;
  color: #063142 !important;
  transform: translateY(-1px);
}

/* =========================
   GraphShield Page Background
   Dark + Light Mode
   ========================= */

/* DARK MODE - default */
.stApp,
[data-testid="stAppViewContainer"] {
  background:
    radial-gradient(circle at 15% 10%, rgba(18, 121, 145, 0.18), transparent 30%),
    radial-gradient(circle at 85% 0%, rgba(13, 64, 84, 0.28), transparent 32%),
    radial-gradient(circle at 50% 100%, rgba(8, 50, 64, 0.38), transparent 42%),
    linear-gradient(135deg, #061f2b 0%, #0a3142 52%, #0c3a4d 100%) !important;
  color: #ffffff !important;
}

/* LIGHT MODE */
body.gs-light .stApp,
body.gs-light [data-testid="stAppViewContainer"] {
  background:
    radial-gradient(circle at 15% 10%, rgba(7, 80, 106, 0.08), transparent 30%),
    radial-gradient(circle at 85% 0%, rgba(246, 214, 207, 0.45), transparent 32%),
    radial-gradient(circle at 50% 100%, rgba(185, 215, 227, 0.35), transparent 42%),
    linear-gradient(135deg, #f8fbfc 0%, #f3f7f9 52%, #edf4f6 100%) !important;
  color: #063142 !important;
}

/* Text colors in light mode */
body.gs-light [data-testid="stMarkdownContainer"],
body.gs-light [data-testid="stMarkdownContainer"] p,
body.gs-light label,
body.gs-light .stCaption,
body.gs-light h1, body.gs-light h2, body.gs-light h3,
body.gs-light h4, body.gs-light h5, body.gs-light h6 {
  color: #063142 !important;
}

/* Text colors in dark mode */
body:not(.gs-light) [data-testid="stMarkdownContainer"],
body:not(.gs-light) [data-testid="stMarkdownContainer"] p,
body:not(.gs-light) label,
body:not(.gs-light) .stCaption,
body:not(.gs-light) h1, body:not(.gs-light) h2, body:not(.gs-light) h3,
body:not(.gs-light) h4, body:not(.gs-light) h5, body:not(.gs-light) h6 {
  color: #ffffff !important;
}

/* ---- collapse the empty leftover wrappers (fixed header + hidden iframe) ---- */
div[data-testid="stElementContainer"]:has(.gs-main-header),
div[data-testid="stElementContainer"]:has(iframe[height="0"]) {
  position: absolute !important; height: 0 !important; width: 0 !important;
  min-height: 0 !important; margin: 0 !important; padding: 0 !important; overflow: hidden !important;
}
</style>
<header class="gs-main-header">
  <div class="gs-brand">
  <div class="gs-logo"><img class="gs-logo-light" src="__LOGO_SRC__" alt="GraphShield Logo"><img class="gs-logo-dark" src="__LOGO_SRC_DARK__" alt="GraphShield Logo"></div>
    <div><h1>GraphShield</h1><p>Smarter Insights. Safer Finance.</p></div>  
  </div>
  <div class="gs-header-actions">
    <button class="gs-icon-btn" id="gs-theme-toggle" title="Toggle dark / light">☀</button>
  </div>
</header>
""".replace("__LOGO_SRC__", _logo_src).replace("__LOGO_SRC_DARK__", _logo_src_dark),
        unsafe_allow_html=True,
    )

    # Toggle wiring via a 0-height component iframe (Streamlit strips inline JS).
    # Default = dark (no `gs-light` class) so there is no first-paint flash.
    # The icon flips: sun while dark (click -> light), moon while light.
    components.html(
        """
<script>
(function () {
  function apply(body, light, btn) {
    if (light) { body.classList.add('gs-light'); } else { body.classList.remove('gs-light'); }
    if (btn) { btn.textContent = light ? '☾' : '☀'; }
  }
  function wire(attempt) {
    try {
      var doc = window.parent.document;
      var body = doc.body;
      var saved = window.parent.localStorage.getItem('gs-theme');
      var light = (saved === 'light');            // default (null) -> dark
      var btn = doc.getElementById('gs-theme-toggle');
      apply(body, light, btn);
      if (!btn) { if (attempt < 20) setTimeout(function () { wire(attempt + 1); }, 100); return; }
      btn.onclick = function () {
        var nowLight = !body.classList.contains('gs-light');
        apply(body, nowLight, btn);
        try { window.parent.localStorage.setItem('gs-theme', nowLight ? 'light' : 'dark'); } catch (e) {}
      };
    } catch (e) {
      if (attempt < 20) setTimeout(function () { wire(attempt + 1); }, 100);
    }
  }
  wire(0);
})();
</script>
""",
        height=0,
    )


render_topbar()
print(f"[SCRIPT] full rerun at {time.strftime('%H:%M:%S')}.{int(time.time()*1000)%1000:03d}")
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
st.session_state.setdefault("active_run_token", None)


@st.cache_resource
def _analysis_runtime():
    """
    Process-lifetime background runtime shared across Streamlit reruns.

    The worker never touches st.session_state. It writes only to this
    thread-safe registry, while the UI fragment polls the registry.
    """
    return {
        "executor": ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="graphshield-analysis",
        ),
        "jobs": {},
        "lock": threading.RLock(),
    }


def _analysis_job_key(session_id: str, txid: str) -> tuple[str, str]:
    return (str(session_id), str(txid))


def _get_analysis_job(session_id: str, txid: str) -> dict | None:
    runtime = _analysis_runtime()
    key = _analysis_job_key(session_id, txid)

    with runtime["lock"]:
        job = runtime["jobs"].get(key)
        return dict(job) if job is not None else None


def _update_analysis_job(
    session_id: str,
    txid: str,
    **changes,
) -> None:
    runtime = _analysis_runtime()
    key = _analysis_job_key(session_id, txid)

    with runtime["lock"]:
        job = runtime["jobs"].setdefault(
            key,
            {
                "status": "running",
                "partial_text": "",
                "final_text": None,
                "error": None,
                "started_at": time.time(),
                "finished_at": None,
            },
        )
        job.update(changes)


def _analysis_worker(
    session_id: str,
    selected: dict,
) -> None:
    """
    Run the initial-analysis LLM stream outside Streamlit's UI execution.

    Closing the panel does not cancel this worker. The stream is fully consumed,
    so llm_service stores the final Executive Summary in
    executive_summary_cache exactly as before.
    """
    txid = str(selected["txId"])
    started = time.perf_counter()
    accumulated = ""

    try:
        context = build_context(
            txid,
            _build_selected_node_obj(selected),
        )

        for chunk in generate_explanation_stream(
            context,
            request_type="initial_analysis",
            session_id=session_id,
        ):
            accumulated += chunk
            _update_analysis_job(
                session_id,
                txid,
                status="running",
                partial_text=accumulated,
            )

        _update_analysis_job(
            session_id,
            txid,
            status="done",
            partial_text=accumulated,
            final_text=accumulated,
            error=None,
            finished_at=time.time(),
        )

        print(
            f"[ANALYSIS][BG] completed | "
            f"txid={txid} | chars={len(accumulated)} | "
            f"elapsed={time.perf_counter() - started:.3f}s"
        )

    except ValidationError:
        message = (
            "This transaction could not be analyzed because the request did "
            "not pass validation. Please select a valid transaction and try again."
        )
        _update_analysis_job(
            session_id,
            txid,
            status="error",
            error=message,
            finished_at=time.time(),
        )
        print(
            f"[ANALYSIS][BG] validation failed | txid={txid}"
        )

    except Exception as exc:
        message = "The analysis request failed unexpectedly. Please try again."
        _update_analysis_job(
            session_id,
            txid,
            status="error",
            error=message,
            finished_at=time.time(),
        )
        print(
            f"[ANALYSIS][BG] failed | txid={txid} | "
            f"{type(exc).__name__}: {exc}"
        )


def _ensure_initial_analysis_job(
    session_id: str,
    selected: dict,
) -> str:
    """
    Ensure exactly one initial-analysis job exists for this session+transaction.

    Returns one of: "cached", "running", "done", "error", "started".
    """
    txid = str(selected["txId"])

    cached = executive_summary_cache.get(session_id, txid)
    if cached is not None:
        _update_analysis_job(
            session_id,
            txid,
            status="done",
            partial_text=cached,
            final_text=cached,
            error=None,
            finished_at=time.time(),
        )
        return "cached"

    existing = _get_analysis_job(session_id, txid)
    if existing is not None:
        status = str(existing.get("status") or "")
        if status in {"running", "done", "error"}:
            return status

    _update_analysis_job(
        session_id,
        txid,
        status="running",
        partial_text="",
        final_text=None,
        error=None,
        started_at=time.time(),
        finished_at=None,
    )

    runtime = _analysis_runtime()
    runtime["executor"].submit(
        _analysis_worker,
        str(session_id),
        dict(selected),
    )

    print(
        f"[ANALYSIS][BG] started | "
        f"txid={txid} | session_id={session_id}"
    )
    return "started"


def _reset_investigation_state():
    st.session_state.initial_analysis_text = None
    st.session_state.initial_analysis_error = None
    st.session_state.initial_analysis_pending = False
    st.session_state.question_answer_text = None
    st.session_state.question_error = None
    st.session_state.question_pending_id = None
    # Invalidate any stream still running for the transaction being left --
    # it will see the mismatch on its next chunk and abandon cleanly instead
    # of writing its result into the newly-selected transaction's panel.
    st.session_state.active_run_token = None


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


def _run_initial_analysis_streaming(selected: dict, placeholder, run_token: str) -> None:
    """Streams the initial analysis into `placeholder`, writing text as it
    arrives instead of blocking silently. This is the standard fix for
    reasoning-model latency: total wait time is unchanged, but the user sees
    live progress instead of a frozen button.

    Cancellation: `run_token` is a unique id stamped by the caller when this
    request started. On every chunk we check it against
    st.session_state.active_run_token -- if they no longer match (the user
    closed the panel or switched transactions while this was still running
    on the server), we stop writing to session_state and to the placeholder
    and return immediately. Without this, an abandoned stream keeps running
    to completion, writes its result late, and reopens/repopulates a panel
    the user already closed or moved away from.
    """
    started = time.perf_counter()
    accumulated = ""
    try:
        context = build_context(selected["txId"], _build_selected_node_obj(selected))
        for chunk in generate_explanation_stream(
            context,
            request_type="initial_analysis",
            session_id=st.session_state.session_id,
        ):
            if st.session_state.get("active_run_token") != run_token:
                print(f"[STREAM] initial_analysis abandoned (stale token) tx={selected.get('txId')}")
                return  # abandoned: do not write partial/final result anywhere
            accumulated += chunk
            placeholder.markdown(accumulated + " ▌")  # cursor while still streaming

        if st.session_state.get("active_run_token") != run_token:
            print(f"[STREAM] initial_analysis finished but abandoned tx={selected.get('txId')}")
            return

        placeholder.markdown(accumulated)
        st.session_state.initial_analysis_text = accumulated
        st.session_state.initial_analysis_error = None
    except ValidationError:
        if st.session_state.get("active_run_token") == run_token:
            st.session_state.initial_analysis_error = (
                "This transaction could not be analyzed because the request did not pass validation. "
                "Please select a valid transaction and try again."
            )
    except Exception:
        if st.session_state.get("active_run_token") == run_token:
            st.session_state.initial_analysis_error = (
                "The analysis request failed unexpectedly. Please try again."
            )
    finally:
        if st.session_state.get("active_run_token") == run_token:
            st.session_state.initial_analysis_pending = False
        print(f"[PERF] initial_analysis total: {time.perf_counter() - started:.3f}s")


def _run_question_streaming(selected: dict, question_id: str, placeholder, run_token: str) -> None:
    """Streaming counterpart to _run_initial_analysis_streaming. See its
    docstring for the cancellation mechanism (run_token)."""
    started = time.perf_counter()
    accumulated = ""
    try:
        context = build_context(selected["txId"], _build_selected_node_obj(selected))
        for chunk in generate_explanation_stream(
            context,
            request_type="question",
            question_id=question_id,
            session_id=st.session_state.session_id,
        ):
            if st.session_state.get("active_run_token") != run_token:
                print(f"[STREAM] {question_id} abandoned (stale token) tx={selected.get('txId')}")
                return
            accumulated += chunk
            placeholder.markdown(accumulated + " ▌")

        if st.session_state.get("active_run_token") != run_token:
            print(f"[STREAM] {question_id} finished but abandoned tx={selected.get('txId')}")
            return

        placeholder.markdown(accumulated)
        st.session_state.question_answer_text = accumulated
        st.session_state.question_error = None
    except ValidationError:
        if st.session_state.get("active_run_token") == run_token:
            st.session_state.question_error = (
                "This question could not be answered because the request did not pass validation."
            )
    except Exception:
        if st.session_state.get("active_run_token") == run_token:
            st.session_state.question_error = (
                "The question request failed unexpectedly. Please try again."
            )
    finally:
        if st.session_state.get("active_run_token") == run_token:
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

pred_df_filtered = d["pred_df"].copy()


# 3. Graph data memoization: rebuild only when controls or filters change.
graph_cache_key = (
    top_n,
    max_nb,
    num_norm,
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

st.markdown("<div style='height:40px'></div>", unsafe_allow_html=True)

st.caption(
    f"Showing {len(graph_data['nodes'])} nodes · {len(graph_data['links'])} edges · click any node to investigate"
)

events = render_graph(
    graph_data,
    height=650,
    selected_txid=(st.session_state.selected_node or {}).get("txId"),
)

st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)

# Node selection remains independent from analysis. A node switch clears stale
# investigation content but never calls Azure automatically.
_select_node(events.get("node_clicked"))

analyze_request = events.get("analyze_transaction")
if analyze_request:
    _select_node(analyze_request)
    st.session_state.sidebar_open = True

    txid = str(st.session_state.selected_node["txId"])
    job_state = _ensure_initial_analysis_job(
        st.session_state.session_id,
        st.session_state.selected_node,
    )

    job = _get_analysis_job(
        st.session_state.session_id,
        txid,
    )

    if job_state in {"cached", "done"} and job:
        st.session_state.initial_analysis_text = job.get("final_text")
        st.session_state.initial_analysis_error = None
        st.session_state.initial_analysis_pending = False

    elif job_state == "error" and job:
        st.session_state.initial_analysis_text = None
        st.session_state.initial_analysis_error = job.get("error")
        st.session_state.initial_analysis_pending = False

    else:
        st.session_state.initial_analysis_text = None
        st.session_state.initial_analysis_error = None
        st.session_state.initial_analysis_pending = True

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

# 4/5. Investigation sidebar as a PLAIN fragment (no run_every, no threads).
# Clicking Close or a question button now reruns only this fragment --
# render_graph above is never re-executed by these clicks, which removes the
# 3D graph re-render cost from them. st.rerun() called from inside a fragment
# is automatically scoped to the fragment, not the full app.
# Poll the fragment ONLY while the initial-analysis stream is in-flight AND
# nothing else is displayed in the response area. Once the user is reading a
# settled answer -- either the initial analysis text or a question answer --
# or a question is currently streaming inline (writes directly into the
# placeholder), polling would just repaint the response area every 500ms and
# cause a visible blink while the user reads. The gate below disables the
# poll in those cases.
_panel_poll_interval = (
    0.5
    if (
        st.session_state.sidebar_open
        and st.session_state.initial_analysis_pending
        and st.session_state.question_pending_id is None
        and not st.session_state.question_answer_text
        and not st.session_state.initial_analysis_text
    )
    else None
)


@st.fragment(run_every=_panel_poll_interval)
def investigation_panel():
    print(
        f"[PANEL] enter | sidebar_open={st.session_state.sidebar_open} "
        f"| selected_txid={(st.session_state.selected_node or {}).get('txId')} "
        f"| pending={st.session_state.initial_analysis_pending} "
        f"| has_text={st.session_state.initial_analysis_text is not None} "
        f"| token={st.session_state.active_run_token}"
    )
    if not (st.session_state.sidebar_open and st.session_state.selected_node is not None):
        return

    selected = st.session_state.selected_node
    selected_txid = str(selected["txId"])

    # Synchronize UI state from the background job registry. This is read-only
    # from the worker's perspective; the worker never touches st.session_state.
    analysis_job = _get_analysis_job(
        st.session_state.session_id,
        selected_txid,
    )

    if analysis_job is not None:
        analysis_status = analysis_job.get("status")

        if analysis_status == "done":
            st.session_state.initial_analysis_text = analysis_job.get("final_text")
            st.session_state.initial_analysis_error = None
            st.session_state.initial_analysis_pending = False

        elif analysis_status == "error":
            st.session_state.initial_analysis_text = None
            st.session_state.initial_analysis_error = analysis_job.get("error")
            st.session_state.initial_analysis_pending = False

        elif analysis_status == "running":
            st.session_state.initial_analysis_pending = True

    # If the fragment is being auto-polled (run_every=0.5) but the poll gate
    # condition no longer holds -- typically because the initial-analysis
    # finished, or the user just clicked a question -- the poll interval
    # captured by @st.fragment at module top-level is stale. Fragment reruns
    # don't re-evaluate decorator arguments, so the panel would keep polling
    # every 500ms forever inside this fragment. Trigger ONE full-script rerun
    # to recompute _panel_poll_interval to None; from then on the fragment
    # sits still until the user actually interacts.
    _should_poll_now = (
        st.session_state.sidebar_open
        and st.session_state.initial_analysis_pending
        and st.session_state.question_pending_id is None
        and not st.session_state.question_answer_text
        and not st.session_state.initial_analysis_text
    )
    if _panel_poll_interval is not None and not _should_poll_now:
        st.rerun()

    with st.container(key="investigation_sidebar"):
        hcol1, hcol2 = st.columns([4, 1])
        hcol1.markdown(f"### Transaction {selected['txId']}")
        if hcol2.button("✕", key="close_sidebar"):
            # Close the UI only. The initial-analysis worker keeps running in
            # the background and will save its completed result in the shared
            # Executive Summary cache. Reopening the same transaction reuses
            # that running job or its cached final result instead of starting
            # another LLM request.
            st.session_state.sidebar_open = False
            st.session_state.question_pending_id = None
            st.session_state.active_run_token = None
            st.rerun()

        # Render Suggested Questions FIRST (source order), so a click sets
        # `question_pending_id` before the response area below is drawn. The
        # response area then streams inline in the SAME render pass -- no
        # st.rerun(), no placeholder-then-overwrite blink.
        # We render the button row inside a scoped container so its DOM
        # position in the sidebar visually stays after the response area via
        # CSS ordering (see .st-key-investigation_sidebar rules).
        questions_locked = (
            st.session_state.initial_analysis_text is None
            or st.session_state.initial_analysis_pending
            or st.session_state.question_pending_id is not None
        )

        with st.container(key="investigation_questions_area"):
            st.markdown("**Suggested Questions**")
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
                    # Fresh token: invalidates any stream still finishing from a
                    # previous question/analysis so it abandons instead of landing
                    # its result in the wrong place later.
                    st.session_state.active_run_token = uuid.uuid4().hex
                    # NOTE: no st.rerun() here -- see comment above. The response
                    # area below will see the freshly-set pending id and stream.

        with st.container(key="investigation_response_wrap"):
            st.markdown("**Investigation Response**")
            with st.container(key="investigation_response_area"):
                response_placeholder = st.empty()

                if st.session_state.question_pending_id is not None:
                    # Stream directly into the placeholder now, in this same pass,
                    # so text appears live instead of a silent block-then-rerun.
                    response_placeholder.markdown("⏳ Answering the selected question...")
                    _run_question_streaming(
                        selected,
                        st.session_state.question_pending_id,
                        response_placeholder,
                        st.session_state.active_run_token,
                    )
                elif st.session_state.question_error:
                    response_placeholder.markdown(
                        f'<div class="error-box">⚠️ {st.session_state.question_error}</div>',
                        unsafe_allow_html=True,
                    )
                elif st.session_state.question_answer_text:
                    response_placeholder.markdown(st.session_state.question_answer_text)
                elif st.session_state.initial_analysis_pending:
                    if analysis_job and analysis_job.get("partial_text"):
                        response_placeholder.markdown(
                            analysis_job["partial_text"] + " ▌"
                        )
                    else:
                        response_placeholder.markdown(
                            "⏳ Running initial analysis..."
                        )
                elif st.session_state.initial_analysis_error:
                    response_placeholder.markdown(
                        f'<div class="error-box">⚠️ {st.session_state.initial_analysis_error}</div>',
                        unsafe_allow_html=True,
                    )
                elif st.session_state.initial_analysis_text:
                    response_placeholder.markdown(st.session_state.initial_analysis_text)
                else:
                    response_placeholder.caption("No analysis is available yet.")

investigation_panel()


st.markdown("<div style='height: 24px;'></div>", unsafe_allow_html=True)


# 6. Shared Report History. With no login system, all saved reports are shown.
render_report_history(storage_error=st.session_state.report_storage_error)