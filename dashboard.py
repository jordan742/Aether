"""
dashboard.py — Aether Fund One: The Mind
------------------------------------------
Root-level Streamlit Command Center.

Reads shared/telemetry.json every 5 seconds via st.empty() + time.sleep()
and renders the live Alpha Signal and Midas Trade Log.

Run:
    streamlit run dashboard.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st

_ROOT = Path(__file__).resolve().parent

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Aether Fund One",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS — Dark #0E1117 base with #00D4FF neon-blue accents ────────────────────
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

/* Alpha alert boxes */
.alert-buy {
    background: #00150A;
    border: 2px solid #00FF88;
    border-radius: 8px;
    padding: 20px 28px;
    box-shadow: 0 0 24px #00FF8844;
}
.alert-sell {
    background: #150000;
    border: 2px solid #FF3344;
    border-radius: 8px;
    padding: 20px 28px;
    box-shadow: 0 0 24px #FF334444;
}
.alert-hold {
    background: #0D1117;
    border: 1px solid #334455;
    border-radius: 8px;
    padding: 20px 28px;
}
.alert-dir   { font-size: 2.2rem; font-weight: 800; letter-spacing: .06em; margin-bottom: 4px; }
.alert-meta  { font-size: .9rem; opacity: .75; }
.alert-tag   { font-size: .68rem; letter-spacing: .18em; text-transform: uppercase;
               color: #556677; margin-bottom: 6px; }

/* Trade table */
[data-testid="stDataFrame"] thead th {
    background: #0D1520 !important;
    color: #00D4FF !important;
    font-size: .75rem !important;
    letter-spacing: .08em !important;
}
[data-testid="stDataFrame"] tbody tr:nth-child(even) { background: #0A1018 !important; }
</style>
""", unsafe_allow_html=True)

# ── Helpers ────────────────────────────────────────────────────────────────────

TELEMETRY_PATH = _ROOT / "shared" / "telemetry.json"
TRADES_PATH    = _ROOT / "shared" / "trades.jsonl"


def _read_telemetry() -> dict:
    try:
        return json.loads(TELEMETRY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_trades(n: int = 25) -> list[dict]:
    if not TRADES_PATH.exists():
        return []
    lines = TRADES_PATH.read_text(encoding="utf-8").strip().splitlines()
    out = []
    for line in reversed(lines[-n:]):
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _direction_html(direction: str, ticker: str, conviction: str,
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
    </div>
    """


# ══════════════════════════════════════════════════════════════════════════════
# Static header (rendered once, outside the live loop)
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("# 🛰️  Aether Fund One")
st.caption("Orbital Intelligence · Paper Trading · Live Signal Feed")
st.divider()

# ── Live region placeholder ────────────────────────────────────────────────────
live = st.empty()

# ══════════════════════════════════════════════════════════════════════════════
# Live loop — refreshes every 5 seconds via st.empty() re-render
# ══════════════════════════════════════════════════════════════════════════════

while True:
    t = _read_telemetry()
    trades = _read_trades()

    alpha  = t.get("alpha_signal") or t.get("signal") or {}
    truth  = t.get("orbital_truth") or {}
    scene  = t.get("scene") or {}
    detect = t.get("detection") or {}

    direction  = alpha.get("direction",  "HOLD")
    ticker     = alpha.get("ticker",     "—")
    conviction = alpha.get("conviction", "—")
    strength   = float(alpha.get("strength") or 0.0)
    sector     = alpha.get("sector",     "—")
    thesis     = truth.get("thesis",     "Awaiting first orbital uplink…")
    delta_pct  = truth.get("delta_pct")
    dom_type   = truth.get("dominant_vessel_type", "—")
    ts         = t.get("timestamp", "—")
    schema     = t.get("schema_version", "—")
    status     = t.get("status", "initializing")
    port       = scene.get("port", "—")
    ships      = detect.get("ship_count")
    conf       = detect.get("confidence_mean")

    with live.container():

        # ── Row A — status metrics ─────────────────────────────────────────────
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Gateway",  status.upper())
        with c2:
            st.metric("Port",     (port or "—").replace("_", " ").title())
        with c3:
            st.metric("Ships",    ships if ships is not None else "—",
                      delta=f"{delta_pct:+.1f}%" if delta_pct is not None else None)
        with c4:
            st.metric("Confidence", f"{conf:.2f}" if conf is not None else "—")

        st.divider()

        # ── Row B — Alpha Signal (left) + key numbers (right) ─────────────────
        sig_col, num_col = st.columns([3, 2], gap="large")

        with sig_col:
            st.markdown("### ⬡ Alpha Signal")
            st.markdown(
                _direction_html(direction, ticker, conviction, strength, thesis),
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
                    {"Type": "Tankers",        "Count": vb.get("tankers", 0)},
                    {"Type": "Bulk Carriers",  "Count": vb.get("bulk_carriers", 0)},
                    {"Type": "Container",      "Count": vb.get("container", 0)},
                ]).set_index("Type")
                st.bar_chart(vb_df, use_container_width=True, height=140,
                             color="#00D4FF")

        st.divider()

        # ── Row C — Midas Trade Log ────────────────────────────────────────────
        st.markdown("### 📋 Midas Trade Log")

        if trades:
            df = pd.DataFrame(trades)
            show_cols = [c for c in
                         ["timestamp", "ticker", "direction", "conviction",
                          "notional", "vix", "vix_regime", "sector", "thesis"]
                         if c in df.columns]
            df = df[show_cols].copy()

            if "notional" in df.columns:
                df["notional"] = df["notional"].apply(
                    lambda x: f"${x:,.2f}" if x is not None else "—"
                )
            if "vix" in df.columns:
                df["vix"] = df["vix"].apply(
                    lambda x: f"{x:.1f}" if x is not None else "—"
                )
            if "timestamp" in df.columns:
                df["timestamp"] = df["timestamp"].apply(
                    lambda x: x[:19].replace("T", " ") if x else "—"
                )

            st.dataframe(
                df.rename(columns={
                    "timestamp": "Time",  "ticker": "Ticker",
                    "direction": "Side",  "conviction": "Conv.",
                    "notional": "Notional", "vix": "VIX",
                    "vix_regime": "Regime", "sector": "Sector",
                    "thesis": "Thesis",
                }),
                use_container_width=True,
                hide_index=True,
                height=min(400, 40 + len(df) * 36),
            )
        else:
            st.info(
                "No trades executed yet. "
                "The feed will populate once Midas fires the first order.",
                icon="⏳",
            )

        # ── Footer ─────────────────────────────────────────────────────────────
        st.caption(
            f"Last uplink: `{ts}` · Schema: `{schema}` · "
            f"Refreshing every 5 s · "
            f"Dom type: `{dom_type}`"
        )

    # ── 5-second live refresh ──────────────────────────────────────────────────
    time.sleep(5)
