"""Streamlit UI for the shared GraphShield report history."""

from __future__ import annotations

from datetime import date, datetime
from html import escape

import streamlit as st

from services import firebase_services


_HISTORY_CSS = """
<style>
.report-history-toolbar { display:flex; justify-content:flex-end; align-items:center; margin:0 0 12px 0; }
[class*="st-key-report_history_date_wrap"] { max-width:310px; margin-left:auto; }

/* DARK default: #124f65 shade */
.report-history-card {
    position: relative;
    width: 100%;
    box-sizing: border-box;
    background: #124f65;
    border: 1px solid rgba(255,255,255,.10);
    border-radius: 16px;
    padding: 18px 64px 16px 20px;
    margin: 14px 0;
    overflow: visible;
    box-shadow: 0 8px 22px rgba(0,0,0,.22), inset 0 1px 0 rgba(255,255,255,.05);
    transition: background .18s ease, transform .18s ease, box-shadow .18s ease;
}
.report-history-card:hover {
    background: #155972;
    transform: translateY(-1px);
    box-shadow: 0 12px 28px rgba(0,0,0,.28), inset 0 1px 0 rgba(255,255,255,.06);
}
.report-history-id { font-size:16px; font-weight:800; color:#fff; margin:0 0 8px 0; letter-spacing:.1px; }
.report-history-meta { color:rgba(255,255,255,.78); font-size:13px; line-height:1.7; margin:0; }
.report-history-meta b { color:#fff; font-weight:700; }
.report-history-status {
    display:inline-block; padding:3px 10px; border-radius:999px;
    background: rgba(255,255,255,.10); border:1px solid rgba(255,255,255,.16);
    color:#eaf3f7; font-size:12px; font-weight:600; margin-top:6px;
}

.report-menu { position:absolute; top:14px; right:14px; z-index:5; }
.report-menu summary {
    list-style:none; cursor:pointer; color:rgba(255,255,255,.75);
    font-size:22px; line-height:1; padding:2px 6px; border-radius:6px; user-select:none;
}
.report-menu summary::-webkit-details-marker { display:none; }
.report-menu summary:hover { color:#fff; background: rgba(255,255,255,.12); }
.report-menu-panel {
    position:absolute; top:30px; right:0; min-width:155px; padding:6px;
    border-radius:10px; border:1px solid rgba(255,255,255,.14);
    background:#0e4257; box-shadow:0 10px 26px rgba(0,0,0,.35); z-index:20;
}
.report-download-link {
    display:block; white-space:nowrap; padding:8px 12px; border-radius:6px;
    color:#eaf3f7 !important; text-decoration:none !important;
    font-size:13px; text-align:left;
}
.report-download-link:hover { background: rgba(255,255,255,.08); color:#fff !important; }

/* LIGHT mode (matches the mockup) */
body.gs-light .report-history-card {
    background:#f5f9fb; border:1px solid #dae5ec; box-shadow:0 2px 8px rgba(6,49,66,.05);
}
body.gs-light .report-history-card:hover { background:#eef4f7; box-shadow:0 6px 16px rgba(6,49,66,.08); }
body.gs-light .report-history-id { color:#0b3a4c; }
body.gs-light .report-history-meta { color:#4a6373; }
body.gs-light .report-history-meta b { color:#0b3a4c; }
body.gs-light .report-history-status { background:#e5eef3; border:1px solid #d0dde4; color:#0b3a4c; }
body.gs-light .report-menu summary { color:#4a6373; }
body.gs-light .report-menu summary:hover { color:#0b3a4c; background:#e5eef3; }
body.gs-light .report-menu-panel { background:#fff; border:1px solid #dae5ec; box-shadow:0 10px 26px rgba(6,49,66,.10); }
body.gs-light .report-download-link { color:#0b3a4c !important; }
body.gs-light .report-download-link:hover { background:#eef4f7; color:#0b3a4c !important; }
</style>
"""


def _format_timestamp(value) -> str:
    if isinstance(value, datetime):
        return value.astimezone().strftime("%b %d, %Y · %I:%M %p")
    return "—"


def _render_card(report: dict, index: int) -> None:
    report_id = str(report.get("report_id") or "Report")
    txid = str(report.get("transaction_id") or "—")
    status = str(report.get("status") or "Generated")
    generated_at = _format_timestamp(report.get("generated_at"))
    filename = str(report.get("filename") or f"{report_id}_{txid}.pdf")
    storage_path = str(report.get("storage_path") or "")

    try:
        download_url = firebase_services.get_report_download_url(
            storage_path,
            filename=filename,
            expires_minutes=15,
        )
        menu_html = f"""
        <details class="report-menu">
            <summary aria-label="Report actions">⋮</summary>
            <div class="report-menu-panel">
                <a
                    class="report-download-link"
                    href="{escape(download_url, quote=True)}"
                    target="_blank"
                    rel="noopener noreferrer"
                >
                    Download PDF
                </a>
            </div>
        </details>
        """
    except Exception as exc:
        print(
            f"[FIREBASE][REPORT] download URL failed | "
            f"report_id={report_id} | "
            f"{type(exc).__name__}: {exc}"
        )
        menu_html = """
        <details class="report-menu">
            <summary aria-label="Report actions">⋮</summary>
            <div class="report-menu-panel">
                <span class="report-download-link">Download unavailable</span>
            </div>
        </details>
        """

    st.markdown(
        f"""
        <div class="report-history-card" id="report-card-{index}">
            <div class="report-history-id">{escape(report_id)}</div>
            <div class="report-history-meta">
                Transaction ID: <b>{escape(txid)}</b><br/>
                Generated: {escape(generated_at)}<br/>
                <span class="report-history-status">{escape(status)}</span>
            </div>
            {menu_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _report_date(report: dict) -> date | None:
    """Extract the calendar date from a report's generated_at timestamp."""
    ts = report.get("generated_at")
    if isinstance(ts, datetime):
        return ts.astimezone().date()
    return None


def render_report_history(*, storage_error: str | None = None) -> None:
    """Render report history below the Investigation Workspace."""
    st.markdown(_HISTORY_CSS, unsafe_allow_html=True)
    st.markdown("## Report History")

    if storage_error:
        st.warning(storage_error)

    # Load all reports first so we know which dates actually have data. The
    # filter below is a dropdown restricted to those dates -- users cannot pick
    # a day that has no reports.
    try:
        all_reports = firebase_services.get_reports(limit=100)
    except Exception as exc:
        st.error(f"Could not load report history: {exc}")
        print(
            f"[FIREBASE][REPORT] history load failed | "
            f"{type(exc).__name__}: {exc}"
        )
        return

    if not all_reports:
        st.info("No reports are available yet.")
        return

    available_dates = sorted(
        {d for d in (_report_date(r) for r in all_reports) if d is not None},
        reverse=True,
    )

    ALL_LABEL = "All Reports"
    options = [ALL_LABEL] + [d.strftime("%d %b %Y") for d in available_dates]

    with st.container(key="report_history_date_wrap"):
        selected_label = st.selectbox(
            "Date Filter",
            options=options,
            index=0,
            key="report_history_date_filter",
            label_visibility="collapsed",
        )

    if selected_label == ALL_LABEL:
        reports = all_reports
    else:
        chosen = next(
            (d for d in available_dates if d.strftime("%d %b %Y") == selected_label),
            None,
        )
        reports = [r for r in all_reports if _report_date(r) == chosen] if chosen else []

    if not reports:
        st.info("No reports are available for the selected date.")
        return

    for index, report in enumerate(reports):
        _render_card(report, index)  