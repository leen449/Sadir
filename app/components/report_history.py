"""Streamlit UI for the shared GraphShield report history."""

from __future__ import annotations

from datetime import date, datetime
from html import escape

import streamlit as st

from services import firebase_services


_HISTORY_CSS = """
<style>
.report-history-card {
    background: #171b24;
    border: 1px solid #2b3140;
    border-radius: 12px;
    padding: 16px 18px;
    margin: 8px 0 4px 0;
}
.report-history-id {
    font-size: 16px;
    font-weight: 700;
    color: #f5f7fb;
    margin-bottom: 8px;
}
.report-history-meta {
    color: #aab2c0;
    font-size: 13px;
    line-height: 1.7;
}
.report-history-status {
    display: inline-block;
    padding: 3px 9px;
    border-radius: 999px;
    background: #262d3b;
    border: 1px solid #3a4356;
    color: #d6dbea;
    font-size: 12px;
}
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

    info_col, menu_col = st.columns([12, 1])

    with info_col:
        st.markdown(
            f"""
            <div class="report-history-card">
                <div class="report-history-id">{escape(report_id)}</div>
                <div class="report-history-meta">
                    Transaction ID: <b>{escape(txid)}</b><br/>
                    Generated: {generated_at}<br/>
                    <span class="report-history-status">{escape(status)}</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with menu_col:
        with st.popover("⋮", use_container_width=True):
            try:
                download_url = firebase_services.get_report_download_url(
                    storage_path,
                    filename=filename,
                    expires_minutes=15,
                )
            except Exception as exc:
                st.error(f"Could not prepare this report download: {exc}")
            else:
                st.link_button(
                    "Download PDF",
                    download_url,
                    use_container_width=True,
                )


def render_report_history(*, storage_error: str | None = None) -> None:
    """Render report history below the Investigation Workspace."""
    st.markdown(_HISTORY_CSS, unsafe_allow_html=True)
    st.markdown("## Report History")

    if storage_error:
        st.warning(storage_error)

    filter_col, spacer_col = st.columns([2, 5])
    with filter_col:
        date_range = st.date_input(
            "Date Filter",
            value=(),
            key="report_history_date_filter",
        )

    start_date: date | None = None
    end_date: date | None = None
    if isinstance(date_range, tuple):
        if len(date_range) >= 1:
            start_date = date_range[0]
        if len(date_range) >= 2:
            end_date = date_range[1]
        elif len(date_range) == 1:
            end_date = date_range[0]

    try:
        reports = firebase_services.get_reports(
            limit=100,
            start_date=start_date,
            end_date=end_date,
        )
    except Exception as exc:
        st.error(f"Could not load report history: {exc}")
        print(
            f"[FIREBASE][REPORT] history load failed | "
            f"{type(exc).__name__}: {exc}"
        )
        return

    if not reports:
        st.info("No reports are available for the selected date range.")
        return

    for index, report in enumerate(reports):
        _render_card(report, index)
