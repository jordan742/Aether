"""
dashboard.py — Aether: Mediterranean Energy Intelligence
=========================================================
Streamlit Command Center for Gibraltar crude-oil tanker flow analytics.

Data pipeline
-------------
Orion (orion_feed.py)
  └─ data/energy_flow.csv
       └─ shared/intelligence.py → TrendReport
            └─ this dashboard (dashboard.py)

Refresh strategy
----------------
st.empty() + while True + time.sleep(5).
Every 5 seconds the live container is rebuilt with the latest data read
directly from disk — no WebSocket required, safe for Streamlit Cloud.

Secrets
-------
Uses st.secrets (Streamlit Cloud) with os.getenv fallback (local dev).
For local development, set variables in .env and ensure python-dotenv
loads them before Streamlit starts, or set them in the shell environment.

Panels
------
Sidebar:
  • Valuation Brief        $XOM and $USO last close + projected delta
  • Confidence Meter       Orion cloud-cover gate score (st.metric)
  • Supply Analysis        Key data-point bullet list
  • Configuration          AOI, supply window, pressure gate settings

Main area:
  • Status metrics row     Inward transit vol, Supply Index, pressure, confidence
  • Tanker Flow chart      Neon-blue st.line_chart (24-h rolling window)
  • Supply Intelligence    Pressure alert block + investment insight card

Run locally:
    streamlit run dashboard.py

Deploy:
    1. Push to GitHub.
    2. Connect repo at share.streamlit.io.
    3. Set secrets: TELEMETRY_FERNET_KEY (optional, for encrypted mode).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st

# ── Path bootstrap ─────────────────────────────────────────────────────────────

_ROOT = Path(__file__).resolve().parent   # Aether/ project root
sys.path.insert(0, str(_ROOT))

from shared.intelligence import analyse, TrendReport, EquitySnapshot  # noqa: E402

# ── Secrets helper ─────────────────────────────────────────────────────────────

def _secret(key: str, default: str = "") -> str:
    """
    Resolve a secret value.  Priority:
      1. st.secrets  (Streamlit Cloud deployment)
      2. os.getenv   (local dev — loaded from .env by run_system.py / shell)
    """
    try:
        return st.secrets[key]
    except (KeyError, FileNotFoundError):
        return os.getenv(key, default)


# ── Page config ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Aether: Mediterranean Energy Intelligence",
    page_icon="🛢️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS ─────────────────────────────────────────────────────────────────
# Palette:
#   #0E1117  deep-space background
#   #080B10  sidebar background (darker)
#   #00D4FF  neon blue  — primary accent / metric values / chart colour
#   #FFB800  amber      — supply-pressure warnings
#   #00FF88  green      — positive projections
#   #FF3344  red        — negative projections / bearish signals
#   #C9D1D9  off-white  — body text
#   #556677  muted      — labels, captions

st.markdown("""
<style>
/* ── Base ── */
html, body,
[data-testid="stAppViewContainer"],
[data-testid="stMain"]            { background:#0E1117 !important; color:#C9D1D9; }
[data-testid="stHeader"]          { background:transparent !important; }
[data-testid="stToolbar"]         { display:none !important; }
[data-testid="stSidebar"]         { background:#080B10 !important; }

h1, h2, h3 { color:#00D4FF !important; letter-spacing:.04em; }
hr          { border-color:#00D4FF22 !important; }

/* ── Metric tiles ── */
[data-testid="metric-container"] {
    background:#131920 !important;
    border:1px solid #00D4FF22 !important;
    border-radius:8px !important;
    padding:12px 16px !important;
}
[data-testid="stMetricValue"] { color:#00D4FF !important; font-weight:700; }
[data-testid="stMetricLabel"] { color:#556677 !important; font-size:.75rem; }

/* ── Supply Pressure alert (amber when active) ── */
.pressure-active {
    background:#0E0900;
    border:2px solid #FFB800;
    border-radius:8px;
    padding:18px 24px;
    box-shadow:0 0 28px #FFB80033;
}
.pressure-inactive {
    background:#0D1117;
    border:1px solid #334455;
    border-radius:8px;
    padding:18px 24px;
}
.pressure-tag   { font-size:.65rem; letter-spacing:.18em; text-transform:uppercase;
                  color:#556677; margin-bottom:6px; }
.pressure-label { font-size:1.8rem; font-weight:800; letter-spacing:.04em; }
.pressure-body  { font-size:.88rem; color:#8899AA; margin-top:8px; line-height:1.55; }

/* ── Investment insight card ── */
.insight-card {
    background:#0A1020;
    border-left:3px solid #00D4FF;
    border-radius:0 8px 8px 0;
    padding:16px 20px;
    font-size:.9rem;
    line-height:1.65;
    color:#A8B8C8;
    height:100%;
}

/* ── Valuation Brief cards (sidebar) ── */
.val-card {
    background:#070D18;
    border:1px solid #00D4FF33;
    border-radius:8px;
    padding:14px 18px;
    margin-bottom:12px;
}
.val-card.triggered {
    border-color:#FFB800;
    box-shadow:0 0 14px #FFB80022;
}
.val-ticker { font-size:.65rem; letter-spacing:.18em; text-transform:uppercase;
              color:#00D4FF; margin-bottom:6px; }
.val-price  { font-size:1.5rem; font-weight:700; color:#C9D1D9; }
.val-delta-pos { color:#00FF88; font-weight:700; font-size:1.05rem; }
.val-delta-neg { color:#FF3344; font-weight:700; font-size:1.05rem; }
.val-meta   { font-size:.74rem; color:#556677; margin-top:4px; }

/* ── DataFrame ── */
[data-testid="stDataFrame"] thead th {
    background:#0D1520 !important; color:#00D4FF !important;
    font-size:.75rem !important; letter-spacing:.08em !important;
}
</style>
""", unsafe_allow_html=True)


# ── HTML helpers ───────────────────────────────────────────────────────────────

def _pressure_html(report: TrendReport) -> str:
    """
    Render the Supply Pressure alert block.
    Amber glow + warning label when gate is active;
    muted border + confirmation label when inactive.
    """
    if report.pressure_flag:
        css         = "pressure-active"
        label       = "⚠  SUPPLY PRESSURE — GATE ACTIVE"
        label_color = "#FFB800"
    else:
        css         = "pressure-inactive"
        label       = "✓  FLOW WITHIN NORMAL VARIANCE"
        label_color = "#556677"

    dev_str = (
        f"{report.deviation_pct:+.1%} vs. {30}-obs Supply Index"
        if report.deviation_pct is not None
        else "Accumulating Supply Index baseline…"
    )
    return f"""
    <div class="{css}">
        <div class="pressure-tag">
            AETHER MEDITERRANEAN ENERGY INTELLIGENCE — SUPPLY MONITOR
        </div>
        <div class="pressure-label" style="color:{label_color}">{label}</div>
        <div class="pressure-body">{dev_str} &nbsp;·&nbsp; {report.inward_transit_vol}</div>
    </div>"""


def _equity_card_html(snap: EquitySnapshot) -> str:
    """
    Render one Valuation Brief card for the sidebar.

    Card turns amber (border + shadow) when the Supply Pressure gate is active,
    signalling that the Projected Value Delta is live.
    """
    triggered_cls = "triggered" if snap.pressure_triggered else ""

    # Format fundamentals
    price_str = f"${snap.last_close:.2f}" if snap.last_close else "—"
    mcap_str  = (
        f"${snap.market_cap / 1e9:.1f}B"
        if snap.market_cap and snap.market_cap >= 1e9
        else f"${snap.market_cap / 1e6:.0f}M"
        if snap.market_cap
        else "—"
    )
    pe_str = f"{snap.pe_ratio:.1f}×" if snap.pe_ratio else "—"

    # Projected delta section
    if snap.pressure_triggered and snap.projected_delta_pct is not None:
        sign      = "+" if snap.projected_delta_pct >= 0 else ""
        delta_cls = "val-delta-pos" if snap.projected_delta_pct >= 0 else "val-delta-neg"
        usd_part  = (
            f" &nbsp;({sign}${snap.projected_delta_usd:.2f})"
            if snap.projected_delta_usd is not None else ""
        )
        delta_html = (
            f'<div class="{delta_cls}">'
            f'{sign}{snap.projected_delta_pct:.1%} projected impact{usd_part}'
            f'</div>'
            f'<div class="val-meta">'
            f'Corr. r = {snap.correlation_coeff:.2f} &nbsp;·&nbsp; '
            f'Supply Pressure gate active'
            f'</div>'
        )
    elif snap.pressure_triggered:
        # Gate fired but live price unavailable (network issue)
        delta_html = (
            '<div class="val-meta" style="color:#FFB800">'
            'Gate active — live price unavailable for USD calculation</div>'
        )
    else:
        delta_html = (
            '<div class="val-meta">'
            'Supply Pressure gate inactive '
            f'(inward transit volume within {PRESSURE_GATE_PCT}% of Supply Index)'
            '</div>'
        )

    return f"""
    <div class="val-card {triggered_cls}">
        <div class="val-ticker">VALUATION BRIEF — ${snap.ticker}</div>
        <div class="val-price">{price_str}</div>
        {delta_html}
        <hr style="border-color:#00D4FF11;margin:10px 0"/>
        <table style="width:100%;font-size:.78rem;color:#C9D1D9">
          <tr><td>Market Cap</td><td style="text-align:right">{mcap_str}</td></tr>
          <tr><td>P/E Ratio</td><td  style="text-align:right">{pe_str}</td></tr>
        </table>
    </div>"""


# ── Display constants ──────────────────────────────────────────────────────────

SUPPLY_WINDOW     = 30       # must match shared/intelligence.py
PRESSURE_GATE_PCT = 15       # must match shared/intelligence.py (PRESSURE_GATE * 100)
AOI_LABEL         = "Strait of Gibraltar [35.9°N, 5.3°W]"


# ── Static header (rendered once outside the refresh loop) ────────────────────

st.markdown("# 🛢️  Aether: Mediterranean Energy Intelligence")
st.caption(
    f"{AOI_LABEL} &nbsp;·&nbsp; Crude Oil Tanker Flow Analytics &nbsp;·&nbsp; "
    "$XOM · $USO &nbsp;·&nbsp; Powered by Sentinel-2 Orbital Imagery"
)
st.divider()

# Live container — entire main panel is rebuilt every 5 s via st.empty()
live = st.empty()


# ══════════════════════════════════════════════════════════════════════════════
# Live refresh loop
# ══════════════════════════════════════════════════════════════════════════════

while True:

    # Pull latest intelligence report (reads CSV; calls yfinance)
    report: TrendReport = analyse()

    # Convenience aliases for the current observation
    current_count = (
        int(report.flow_series["tanker_count"].iloc[-1])
        if not report.flow_series.empty else None
    )
    supply_idx    = report.supply_index
    deviation_pct = report.deviation_pct
    confidence    = report.confidence_latest

    # ── Sidebar: Valuation Brief + Confidence Meter ──────────────────────────
    with st.sidebar:

        st.markdown("## 🛢️  Valuation Brief")
        st.divider()

        # $XOM card
        if report.xom:
            st.markdown(_equity_card_html(report.xom), unsafe_allow_html=True)
        else:
            st.caption("$XOM — awaiting Orion data.")

        # $USO card
        if report.uso:
            st.markdown(_equity_card_html(report.uso), unsafe_allow_html=True)
        else:
            st.caption("$USO — awaiting Orion data.")

        # ── Confidence Meter ─────────────────────────────────────────────────
        # Derived from Orion's Weather Gate: 1.0 = clear sky; 0.0 = opaque cloud
        st.divider()
        st.markdown("**📡 Confidence Meter**")
        conf_delta_label = (
            "⚠  Cloud cover > 30% — attenuated signal"
            if confidence < 0.50
            else "✓  Clear acquisition — full confidence"
        )
        st.metric(
            label="Orion Signal Quality",
            value=f"{confidence:.0%}",
            delta=conf_delta_label,
            delta_color="inverse" if confidence < 0.50 else "normal",
        )

        # ── Supply Analysis bullets ──────────────────────────────────────────
        st.divider()
        st.markdown("**📊 Supply Analysis**")
        for bullet in report.sidebar_bullets:
            st.markdown(f"- {bullet}")

        # ── Configuration panel ──────────────────────────────────────────────
        st.divider()
        st.markdown("**⚙️  Configuration**")
        st.caption(f"AOI: `{AOI_LABEL}`")
        st.caption(f"Supply Index window: `{SUPPLY_WINDOW} observations`")
        st.caption(f"Pressure gate: `>{PRESSURE_GATE_PCT}% above Supply Index`")
        st.caption(
            f"Encryption: `{'ON' if _secret('TELEMETRY_FERNET_KEY') else 'OFF'}`"
        )
        st.caption("Secrets via `st.secrets` (Streamlit Cloud)")

    # ── Main panel ─────────────────────────────────────────────────────────────
    with live.container():

        # ── Row A: Status metrics ─────────────────────────────────────────────
        c1, c2, c3, c4 = st.columns(4)

        with c1:
            st.metric(
                label="Inward Transit Volume",
                value=(
                    f"{current_count} VLCC"
                    if current_count is not None else "—"
                ),
                delta=(
                    f"{deviation_pct:+.1%} vs. Supply Index"
                    if deviation_pct is not None else None
                ),
                # Positive deviation = more tankers = bullish for energy prices
                delta_color="normal" if (deviation_pct or 0) >= 0 else "inverse",
            )

        with c2:
            st.metric(
                label=f"{SUPPLY_WINDOW}-Obs Supply Index",
                value=(
                    f"{supply_idx:.1f} transits"
                    if supply_idx is not None else "Accumulating…"
                ),
            )

        with c3:
            st.metric(
                label="Supply Pressure Gate",
                value="ACTIVE 🔴" if report.pressure_flag else "INACTIVE 🟢",
            )

        with c4:
            st.metric(
                label="Confidence",
                value=f"{confidence:.0%}",
                delta="LOW — cloud attenuated" if confidence < 0.50 else "CLEAR",
                delta_color="inverse" if confidence < 0.50 else "normal",
            )

        st.divider()

        # ── Row B: Tanker Flow line chart ─────────────────────────────────────
        st.markdown("### 📡 Tanker Flow — Strait of Gibraltar")

        if not report.flow_series.empty:
            # Rename for a clean chart legend
            chart_df = report.flow_series.rename(
                columns={"tanker_count": "VLCC / Suezmax Inward Transits"}
            )
            st.line_chart(
                chart_df,
                use_container_width=True,
                height=260,
                color="#00D4FF",   # neon blue — primary brand colour
            )

            # Supply Index reference caption below chart
            if supply_idx is not None and deviation_pct is not None:
                st.caption(
                    f"🔵 Current: **{current_count}** transits &nbsp;·&nbsp; "
                    f"📊 {SUPPLY_WINDOW}-obs Supply Index: **{supply_idx:.1f}** &nbsp;·&nbsp; "
                    f"Deviation: **{deviation_pct:+.1%}**"
                )
            elif current_count is not None:
                st.caption(
                    f"🔵 Current: **{current_count}** transits &nbsp;·&nbsp; "
                    f"Accumulating Supply Index baseline ({SUPPLY_WINDOW} obs required)…"
                )
        else:
            st.info(
                "No flow data yet. "
                "Seed the dataset with a single command:\n\n"
                "```bash\npython orion_feed.py\n```",
                icon="🛰️",
            )

        st.divider()

        # ── Row C: Supply Intelligence ────────────────────────────────────────
        st.markdown("### ⚡ Supply Intelligence")

        alert_col, insight_col = st.columns([1, 1], gap="large")

        with alert_col:
            # Supply Pressure alert block (amber when active, muted when inactive)
            st.markdown(_pressure_html(report), unsafe_allow_html=True)

        with insight_col:
            # Investment-grade single-sentence insight
            st.markdown(
                f'<div class="insight-card">{report.supply_insight}</div>',
                unsafe_allow_html=True,
            )

        # ── Footer ────────────────────────────────────────────────────────────
        st.divider()
        st.caption(
            f"Data: `data/energy_flow.csv` &nbsp;·&nbsp; "
            f"Supply window: `{SUPPLY_WINDOW} obs` &nbsp;·&nbsp; "
            f"Pressure gate: `>{PRESSURE_GATE_PCT}%` &nbsp;·&nbsp; "
            "Refreshing every 5 s"
        )

    # ── 5-second refresh ──────────────────────────────────────────────────────
    time.sleep(5)
