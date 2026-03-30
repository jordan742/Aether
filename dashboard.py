"""
dashboard.py — Aether Intelligence: Streamlit Cloud Command Center
-------------------------------------------------------------------
Reads shared/telemetry.json every 5 s (st.empty + while True).
Uses st.secrets (Streamlit Cloud) with os.getenv fallback (local).
Renders:
  - Satellite Trend line chart   (ship count history)
  - XOM Correlation chart        (yfinance $XOM closing prices)
  - Alpha Signal alert box       (Orion's proprietary signal)
  - Strategic Insights sidebar   (from shared/intelligence.py)

Run locally:
    streamlit run dashboard.py

Deploy:
    Push to GitHub → connect to share.streamlit.io
    Add secrets in the Streamlit Cloud dashboard under Settings → Secrets.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pandas as pd
import streamlit as st

_ROOT = Path(__file__).resolve().parent

# ── Secrets helper (st.secrets → os.getenv fallback) ───────────────────────────

def _secret(key: str, default: str = "") -> str:
    try:
        return st.secrets[key]
    except (KeyError, FileNotFoundError):
        return os.getenv(key, default)


# ── Intelligence engine ─────────────────────────────────────────────────────────
import sys
sys.path.insert(0, str(_ROOT))
from shared.intelligence import analyse, TrendReport, ValuationImpact  # noqa: E402

# ── Page config ─────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Aether Intelligence",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS ──────────────────────────────────────────────────────────────────
st.markdown("""
<style>
html, body,
[data-testid="stAppViewContainer"],
[data-testid="stMain"]            { background: #0E1117 !important; color: #C9D1D9; }
[data-testid="stHeader"]          { background: transparent !important; }
[data-testid="stToolbar"]         { display: none !important; }
[data-testid="stSidebar"]         { background: #080B10 !important; }

h1, h2, h3 { color: #00D4FF !important; letter-spacing: .04em; }
hr          { border-color: #00D4FF22 !important; }

[data-testid="metric-container"] {
    background: #131920 !important;
    border: 1px solid #00D4FF22 !important;
    border-radius: 8px !important;
    padding: 12px 16px !important;
}
[data-testid="stMetricValue"] { color: #00D4FF !important; font-weight: 700; }
[data-testid="stMetricLabel"] { color: #556677 !important; font-size: .75rem; }

.alert-buy  { background:#00150A; border:2px solid #00FF88; border-radius:8px;
              padding:20px 28px; box-shadow:0 0 24px #00FF8844; }
.alert-sell { background:#150000; border:2px solid #FF3344; border-radius:8px;
              padding:20px 28px; box-shadow:0 0 24px #FF334444; }
.alert-hold { background:#0D1117; border:1px solid #334455;
              border-radius:8px; padding:20px 28px; }

.alert-dir  { font-size:2.2rem; font-weight:800; letter-spacing:.06em; margin-bottom:4px; }
.alert-meta { font-size:.9rem; opacity:.75; }
.alert-tag  { font-size:.68rem; letter-spacing:.18em; text-transform:uppercase;
              color:#556677; margin-bottom:6px; }

.insight-box { background:#0A1020; border:1px solid #00D4FF33; border-radius:8px;
               padding:14px 18px; margin-bottom:10px; }
.insight-cat-BULLISH { color:#00FF88; font-weight:700; }
.insight-cat-BEARISH { color:#FF3344; font-weight:700; }
.insight-cat-WATCH   { color:#FFB800; font-weight:700; }
.insight-cat-NEUTRAL { color:#556677; font-weight:700; }

.valuation-box { background:#070D18; border:2px solid #00D4FF55;
                 border-radius:8px; padding:16px 20px; margin-top:6px; }
.valuation-triggered { border-color:#00FF88 !important;
                       box-shadow:0 0 18px #00FF8833; }
.val-label { font-size:.65rem; letter-spacing:.16em; text-transform:uppercase;
             color:#00D4FF; margin-bottom:8px; }
.val-delta-pos { font-size:1.4rem; font-weight:800; color:#00FF88; }
.val-delta-neg { font-size:1.4rem; font-weight:800; color:#FF3344; }
.val-delta-nil { font-size:1.0rem; color:#556677; font-style:italic; }

[data-testid="stDataFrame"] thead th {
    background:#0D1520 !important; color:#00D4FF !important;
    font-size:.75rem !important; letter-spacing:.08em !important;
}
</style>
""", unsafe_allow_html=True)


# ── Data readers ────────────────────────────────────────────────────────────────

TELEMETRY_PATH = _ROOT / "shared" / "telemetry.json"


def _read_telemetry() -> dict:
    try:
        return json.loads(TELEMETRY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _alpha_html(direction: str, ticker: str, conviction: str,
                strength: float, thesis: str) -> str:
    if direction == "BUY":
        css, colour, arrow = "alert-buy",  "#00FF88", "▲"
    elif direction == "SELL":
        css, colour, arrow = "alert-sell", "#FF3344", "▼"
    else:
        css, colour, arrow = "alert-hold", "#334455", "◌"
    return f"""
    <div class="{css}">
        <div class="alert-tag">PROPRIETARY ALPHA SIGNAL</div>
        <div class="alert-dir" style="color:{colour}">{arrow} {direction}</div>
        <div class="alert-meta" style="color:{colour}">
            {ticker} &nbsp;·&nbsp; {conviction} &nbsp;·&nbsp; {strength:.0%}
        </div>
        <div class="alert-meta" style="margin-top:8px;font-style:italic;color:#8899AA">
            "{thesis}"
        </div>
    </div>"""


# ── Session state — ship count history ─────────────────────────────────────────

if "ship_history" not in st.session_state:
    st.session_state.ship_history: list[dict] = []


# ══════════════════════════════════════════════════════════════════════════════
# Static header
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("# 🛰️  Aether Intelligence")
st.caption("Orbital Vessel Analytics · $XOM Correlation · Strategic Insights")
st.divider()

live = st.empty()

# ══════════════════════════════════════════════════════════════════════════════
# Live loop
# ══════════════════════════════════════════════════════════════════════════════

while True:
    t      = _read_telemetry()
    alpha  = t.get("alpha_signal") or t.get("signal") or {}
    truth  = t.get("orbital_truth") or {}
    scene  = t.get("scene") or {}
    detect = t.get("detection") or {}

    direction  = alpha.get("direction",  "HOLD")
    ticker     = alpha.get("ticker",     "—")
    conviction = alpha.get("conviction", "—")
    strength   = float(alpha.get("strength") or 0.0)
    sector     = alpha.get("sector",     "—")
    thesis     = truth.get("thesis") or "Awaiting first orbital uplink…"
    delta_pct  = truth.get("delta_pct")
    dom_type   = truth.get("dominant_vessel_type", "—")
    ts         = t.get("timestamp", "—")
    schema     = t.get("schema_version", "—")
    status     = t.get("status", "initializing")
    port       = scene.get("port", "")
    ships      = detect.get("ship_count")
    conf       = detect.get("confidence_mean")

    # Accumulate ship count into session history
    if ships is not None:
        st.session_state.ship_history.append({
            "timestamp": ts if ts != "—" else pd.Timestamp.utcnow().isoformat(),
            "ship_count": ships,
        })
        # Keep last 288 observations (24 h at 5-min intervals)
        st.session_state.ship_history = st.session_state.ship_history[-288:]

    # Run intelligence engine (caches XOM for 5 min via yfinance)
    report: TrendReport = analyse(detect, st.session_state.ship_history, port, ticker)

    # ── Sidebar: Strategic Insights ─────────────────────────────────────────────
    with st.sidebar:
        st.markdown("## 🧠 Strategic Insights")
        st.divider()

        cat   = report.insight_category
        color = {"BULLISH": "#00FF88", "BEARISH": "#FF3344",
                 "WATCH": "#FFB800", "NEUTRAL": "#556677"}.get(cat, "#556677")
        st.markdown(
            f'<div class="insight-box">'
            f'<span class="insight-cat-{cat}">{cat}</span><br/>'
            f'<small>{report.recommendation}</small>'
            f'</div>',
            unsafe_allow_html=True,
        )

        st.markdown("**Data Points**")
        for ins in report.insights:
            st.markdown(f"- {ins}")

        st.divider()
        st.markdown("**$XOM Correlation**")
        if not report.xom_series.empty:
            latest_xom = report.xom_series["Close"].iloc[-1]
            prev_xom   = report.xom_series["Close"].iloc[-2] if len(report.xom_series) > 1 else latest_xom
            xom_delta  = latest_xom - prev_xom
            st.metric("XOM Last Close",
                      f"${latest_xom:.2f}",
                      delta=f"{xom_delta:+.2f}")
        else:
            st.info("XOM data unavailable.")

        # ── Strategic Valuation Insight ─────────────────────────────────────────
        st.divider()
        st.markdown("**📐 Strategic Valuation Insight**")
        v: ValuationImpact | None = report.valuation
        if v is None:
            st.caption("Valuation module active once ticker is identified.")
        else:
            triggered_cls = "valuation-triggered" if v.triggered else ""

            # Projected delta HTML
            if v.triggered and v.projected_delta_pct is not None and v.projected_delta_usd is not None:
                sign       = "+" if v.projected_delta_usd >= 0 else ""
                delta_cls  = "val-delta-pos" if v.projected_delta_usd >= 0 else "val-delta-neg"
                delta_html = (
                    f'<div class="{delta_cls}">'
                    f'{sign}{v.projected_delta_pct:.1%} &nbsp; ({sign}${v.projected_delta_usd:.2f})'
                    f'</div>'
                    f'<div style="font-size:.75rem;color:#8899AA;margin-top:4px">'
                    f'Corr. coeff: {v.correlation_coeff:.2f} &nbsp;·&nbsp; '
                    f'Congestion gate: &gt;10% ✅'
                    f'</div>'
                )
                gate_note = ""
            else:
                delta_html = (
                    '<div class="val-delta-nil">Gate not triggered</div>'
                    '<div style="font-size:.75rem;color:#556677;margin-top:4px">'
                    'Requires ship congestion &gt;10% above baseline</div>'
                )
                gate_note = ""

            mcap_str = (
                f"${v.market_cap / 1e9:.1f}B"
                if v.market_cap and v.market_cap >= 1e9
                else f"${v.market_cap / 1e6:.0f}M"
                if v.market_cap
                else "—"
            )
            pe_str = f"{v.pe_ratio:.1f}×" if v.pe_ratio else "—"
            price_str = f"${v.current_price:.2f}" if v.current_price else "—"

            st.markdown(
                f'<div class="valuation-box {triggered_cls}">'
                f'<div class="val-label">Projected Value Delta — ${v.ticker}</div>'
                f'{delta_html}'
                f'<hr style="border-color:#00D4FF11;margin:10px 0"/>'
                f'<table style="width:100%;font-size:.8rem;color:#C9D1D9">'
                f'<tr><td>Price</td><td style="text-align:right">{price_str}</td></tr>'
                f'<tr><td>Market Cap</td><td style="text-align:right">{mcap_str}</td></tr>'
                f'<tr><td>P/E Ratio</td><td style="text-align:right">{pe_str}</td></tr>'
                f'</table>'
                f'</div>',
                unsafe_allow_html=True,
            )

        st.divider()
        st.markdown("**Configuration**")
        st.caption(f"Port: `{port or '—'}`")
        st.caption(f"Schema: `{schema}`")
        st.caption(f"Encryption: `{'ON' if _secret('TELEMETRY_FERNET_KEY') else 'OFF'}`")
        st.caption("Streamlit Cloud secrets via `st.secrets`")

    # ── Main panel ──────────────────────────────────────────────────────────────
    with live.container():

        # Row A — status metrics
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Gateway",    status.upper())
        with c2:
            st.metric("Port",       (port or "—").replace("_", " ").title())
        with c3:
            st.metric("Ships",      ships if ships is not None else "—",
                      delta=f"{delta_pct:+.1f}%" if delta_pct is not None else None)
        with c4:
            st.metric("Confidence", f"{conf:.2f}" if conf is not None else "—")

        st.divider()

        # Row B — Satellite Trend + XOM Correlation
        chart_col, xom_col = st.columns([3, 2], gap="large")

        with chart_col:
            st.markdown("### 📡 Satellite Trend")
            st.caption(report.trend_label)
            if not report.ship_series.empty:
                st.line_chart(
                    report.ship_series.rename(columns={"ship_count": "Vessel Count"}),
                    use_container_width=True,
                    height=220,
                    color="#00D4FF",
                )
            else:
                st.info("Accumulating orbital data… first chart renders after 1 observation.", icon="🛰️")

        with xom_col:
            st.markdown("### 🛢️  XOM Correlation")
            st.caption("ExxonMobil 1-month closing price via yfinance")
            if not report.xom_series.empty:
                xom_chart = report.xom_series.set_index("Date")[["Close"]]
                st.line_chart(xom_chart, use_container_width=True, height=220, color="#FFB800")
            else:
                st.warning("yfinance data unavailable — check network.", icon="⚠️")

        st.divider()

        # Row C — Alpha Signal + Signal Breakdown
        sig_col, num_col = st.columns([3, 2], gap="large")

        with sig_col:
            st.markdown("### ⬡ Alpha Signal")
            st.markdown(
                _alpha_html(direction, ticker, conviction, strength, thesis),
                unsafe_allow_html=True,
            )

        with num_col:
            st.markdown("### 📊 Signal Breakdown")
            n1, n2 = st.columns(2)
            with n1:
                st.metric("Direction",  direction)
                st.metric("Ticker",     ticker)
            with n2:
                st.metric("Conviction", conviction)
                st.metric("Sector",     sector.replace("_", " ").title())

            vb = detect.get("vessel_breakdown") or {}
            if vb:
                vb_df = pd.DataFrame([
                    {"Type": "Tankers",       "Count": vb.get("tankers",       0)},
                    {"Type": "Bulk Carriers", "Count": vb.get("bulk_carriers", 0)},
                    {"Type": "Container",     "Count": vb.get("container",     0)},
                ]).set_index("Type")
                st.bar_chart(vb_df, use_container_width=True, height=140, color="#00D4FF")

        # Footer
        st.divider()
        st.caption(
            f"Last uplink: `{ts}` · Schema: `{schema}` · "
            f"Dominant type: `{dom_type}` · Refreshing every 5 s"
        )

    time.sleep(5)
