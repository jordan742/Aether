"""
Aether Fund One — Command Center
----------------------------------
Stark-specification Streamlit dashboard.

Theme   : #0E1117 background / #00D4FF neon-blue accents
Gate    : Non-bypassable Legal Disclaimer sidebar checkbox
Feed    : Live PROPRIETARY_ALPHA signal stream (st.empty() pattern)
Risk    : VIX Regime banner — RED / "TRADING HALTED" when VIX ≥ 30
Map     : Real-time Sentinel-2 orbital ground track

Run:
    streamlit run dashboard/dashboard.py
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

# ── Bootstrap ──────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
load_dotenv(_ROOT / ".env")

from shared.bridge import TelemetryBridge  # noqa: E402

# ── Paths ──────────────────────────────────────────────────────────────────────
_TRADES_LOG    = _ROOT / "shared" / "trades.jsonl"
_STATUS_FILE   = _ROOT / "shared" / "system_status.json"
_OVERRIDE_FLAG = _ROOT / "shared" / "OVERRIDE"
_HEALTH_LOG    = _ROOT / "shared" / "system_health.log"

# ── Port AOI centres [lat, lon] ────────────────────────────────────────────────
_PORT_COORDS = {
    "strait_of_gibraltar": (35.9,  -5.4),
    "strait_of_hormuz":    (26.6,  56.5),
    "singapore_strait":    ( 1.25, 103.8),
    "english_channel":     (50.5,   0.5),
}
_PORT_LABELS = {
    "strait_of_gibraltar": "Gibraltar",
    "strait_of_hormuz":    "Hormuz",
    "singapore_strait":    "Singapore",
    "english_channel":     "Channel",
}

# ══════════════════════════════════════════════════════════════════════════════
# Page config — MUST be first Streamlit call
# ══════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Aether Fund One — Command Center",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ══════════════════════════════════════════════════════════════════════════════
# CSS — Stark Dark Theme
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("""
<style>
/* ── Base ──────────────────────────────────────────────────────────────────── */
html, body, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
    background-color: #0E1117 !important;
    color: #C9D1D9 !important;
}
[data-testid="stHeader"]  { background: transparent !important; }
[data-testid="stToolbar"] { display: none !important; }

/* ── Sidebar ───────────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background: #0A0D13 !important;
    border-right: 1px solid #00D4FF22 !important;
}
[data-testid="stSidebar"] * { color: #C9D1D9 !important; }

/* ── Neon-blue accents ─────────────────────────────────────────────────────── */
h1, h2, h3 { color: #00D4FF !important; letter-spacing: .05em; }
hr          { border-color: #00D4FF33 !important; }

/* ── Metric cards ──────────────────────────────────────────────────────────── */
[data-testid="metric-container"] {
    background: #131920 !important;
    border: 1px solid #00D4FF22 !important;
    border-radius: 8px !important;
    padding: 12px 16px !important;
}
[data-testid="stMetricValue"]  { color: #00D4FF !important; font-weight: 700; }
[data-testid="stMetricLabel"]  { color: #6E7C8C !important; font-size: .75rem; }

/* ── VIX PANIC banner ──────────────────────────────────────────────────────── */
.vix-panic {
    background: #1a0000;
    border: 2px solid #FF3030;
    border-radius: 8px;
    padding: 14px 20px;
    text-align: center;
    color: #FF5555;
    font-size: 1.2rem;
    font-weight: 700;
    letter-spacing: .12em;
    box-shadow: 0 0 28px #FF202066;
    animation: vix-pulse 1.4s ease-in-out infinite;
}
.vix-normal {
    background: #0A1A0D;
    border: 1px solid #00D4FF33;
    border-radius: 8px;
    padding: 14px 20px;
    text-align: center;
    color: #00D4FF;
    font-size: 1rem;
    font-weight: 600;
    letter-spacing: .08em;
}
@keyframes vix-pulse {
    0%,100% { opacity: 1; }
    50%      { opacity: .6; }
}

/* ── Alpha signal indicator ────────────────────────────────────────────────── */
.alpha-buy {
    background: #020D1A;
    border: 2px solid #00D4FF;
    border-radius: 10px;
    padding: 20px;
    text-align: center;
    box-shadow: 0 0 32px #00D4FF66, inset 0 0 20px #001A2E;
    animation: alpha-glow 1.6s ease-in-out infinite;
}
.alpha-sell {
    background: #140A0A;
    border: 2px solid #FF3030;
    border-radius: 10px;
    padding: 20px;
    text-align: center;
    box-shadow: 0 0 32px #FF202066, inset 0 0 20px #1A0000;
    animation: alpha-glow 1.6s ease-in-out infinite;
}
.alpha-hold {
    background: #0A0E14;
    border: 1px solid #1E2A38;
    border-radius: 10px;
    padding: 20px;
    text-align: center;
}
.alpha-label { font-size: .7rem; color: #6E7C8C; letter-spacing: .15em; text-transform: uppercase; }
.alpha-dir   { font-size: 2.4rem; font-weight: 800; letter-spacing: .08em; }
.alpha-meta  { font-size: .85rem; margin-top: 6px; opacity: .8; }
@keyframes alpha-glow { 0%,100% { opacity: 1; } 50% { opacity: .65; } }

/* ── Thesis box ────────────────────────────────────────────────────────────── */
.thesis-box {
    background: #0D1520;
    border-left: 3px solid #00D4FF;
    border-radius: 0 6px 6px 0;
    padding: 12px 16px;
    font-style: italic;
    color: #A8B8C8;
    font-size: .9rem;
    line-height: 1.5;
    margin: 8px 0;
}

/* ── Override banner ───────────────────────────────────────────────────────── */
.override-active {
    background: #1A0000;
    border: 2px solid #FF2020;
    border-radius: 8px;
    padding: 12px 20px;
    text-align: center;
    color: #FF5555;
    font-weight: 700;
    font-size: 1rem;
    letter-spacing: .1em;
}

/* ── Disclaimer blur ───────────────────────────────────────────────────────── */
.content-locked {
    filter: blur(9px);
    pointer-events: none;
    user-select: none;
    opacity: .45;
}
.unlock-overlay {
    background: #0E1117EE;
    border: 1px solid #00D4FF44;
    border-radius: 12px;
    padding: 32px 40px;
    text-align: center;
    margin: 40px auto;
    max-width: 480px;
}
.unlock-title {
    font-size: 1.4rem;
    font-weight: 700;
    color: #00D4FF;
    margin-bottom: 8px;
}
.unlock-body { color: #8899AA; font-size: .9rem; line-height: 1.6; }

/* ── Override button ───────────────────────────────────────────────────────── */
div[data-testid="stButton"] > button[kind="primary"] {
    background: #5A0000 !important;
    border: 2px solid #FF2020 !important;
    color: #FFF !important;
    font-weight: 700 !important;
    letter-spacing: .1em !important;
    box-shadow: 0 0 14px #FF000055 !important;
}
div[data-testid="stButton"] > button[kind="primary"]:hover {
    background: #880000 !important;
    box-shadow: 0 0 28px #FF0000AA !important;
}

/* ── Dataframe ─────────────────────────────────────────────────────────────── */
[data-testid="stDataFrame"] thead th { background: #131920 !important; color: #00D4FF !important; }
[data-testid="stDataFrame"] tbody tr:nth-child(even) { background: #0D1520 !important; }

/* ── Sidebar disclaimer checkbox ──────────────────────────────────────────── */
.stCheckbox label { color: #C9D1D9 !important; font-size: .85rem; }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_resource
def _bridge() -> TelemetryBridge:
    return TelemetryBridge()


def _read_telemetry() -> dict:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_bridge().read())
    finally:
        loop.close()


def _load_trades(n: int = 50) -> list[dict]:
    if not _TRADES_LOG.exists():
        return []
    lines = _TRADES_LOG.read_text(encoding="utf-8").strip().splitlines()
    out = []
    for line in reversed(lines[-n:]):
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _load_system_status() -> dict:
    if not _STATUS_FILE.exists():
        return {}
    try:
        return json.loads(_STATUS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _vix_from_trades(trades: list[dict]) -> tuple[float | None, str | None]:
    for t in trades:
        if t.get("vix") is not None:
            return float(t["vix"]), t.get("vix_regime")
    return None, None


def _vix_live() -> tuple[float | None, str | None]:
    try:
        import yfinance as yf
        hist = yf.Ticker("^VIX").history(period="1d", interval="1m")
        if not hist.empty:
            v = float(hist["Close"].iloc[-1])
            regime = (
                "PANIC"    if v >= 40 else
                "FEARFUL"  if v >= 30 else
                "STRESSED" if v >= 25 else
                "ELEVATED" if v >= 20 else
                "NORMAL"
            )
            return round(v, 2), regime
    except Exception:
        pass
    return None, None


def _ground_track(n: int = 120) -> tuple[list, list, float, float]:
    inc = math.radians(98.6)
    now = time.time()
    lats, lons = [], []
    for i in range(-n, 1):
        t  = now + i * 30
        th = (2 * math.pi * t / 5_933) % (2 * math.pi)
        om = math.radians((t / 86_400) * 24.7 % 360)
        la = math.degrees(math.asin(math.sin(inc) * math.sin(th)))
        lo = math.degrees(om + math.atan2(math.cos(inc) * math.sin(th), math.cos(th)))
        lats.append(round(la, 4))
        lons.append(round(((lo + 180) % 360) - 180, 4))
    return lats, lons, lats[-1], lons[-1]


# ══════════════════════════════════════════════════════════════════════════════
# Sidebar — Disclaimer Gate
# ══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("### 🛰️ AETHER FUND ONE")
    st.markdown("<div style='color:#00D4FF;font-size:.7rem;letter-spacing:.2em'>COMMAND CENTER · v3.0</div>", unsafe_allow_html=True)
    st.divider()

    # ── System status (from run_system.py) ────────────────────────────────────
    status = _load_system_status()
    procs  = status.get("processes", {})

    def _dot(alive: bool) -> str:
        return "🟢" if alive else "🔴"

    orion_alive = procs.get("on_orbit_sim", {}).get("alive", False)
    midas_alive = procs.get("trader",       {}).get("alive", False)

    st.markdown("**Agent Status**")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"{_dot(orion_alive)} **Orion**")
        if procs.get("on_orbit_sim"):
            st.caption(f"Restarts: {procs['on_orbit_sim'].get('restart_count', 0)}")
    with c2:
        st.markdown(f"{_dot(midas_alive)} **Midas**")
        if procs.get("trader"):
            st.caption(f"Restarts: {procs['trader'].get('restart_count', 0)}")

    st.divider()

    # ── LEGAL DISCLAIMER — NON-BYPASSABLE ─────────────────────────────────────
    st.markdown("**⚖️ Legal Disclaimer**")
    st.markdown(
        "<div style='font-size:.75rem;color:#6E7C8C;line-height:1.6'>"
        "This system generates <b>simulated</b> paper-trading signals using "
        "synthetic satellite telemetry. It does <b>not</b> constitute financial "
        "advice. All trading activity is executed on the Alpaca <b>paper trading</b> "
        "environment only. Past signal performance does not guarantee future results. "
        "Orbital intelligence is simulated; no actual satellite data is used unless "
        "Copernicus credentials are explicitly configured."
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown("")
    disclaimer_accepted = st.checkbox(
        "I have read and accept the disclaimer",
        key="disclaimer_accepted",
    )

    st.divider()

    # ── Override ───────────────────────────────────────────────────────────────
    st.markdown("**⛔ System Override**")
    if _OVERRIDE_FLAG.exists():
        st.markdown(
            "<div style='color:#FF5555;font-size:.8rem;font-weight:700'>"
            "OVERRIDE ACTIVE</div>",
            unsafe_allow_html=True,
        )
        if st.button("↺ Clear Override", use_container_width=True):
            _OVERRIDE_FLAG.unlink(missing_ok=True)
            st.rerun()
    else:
        if st.button("⛔ KILL ALL AGENTS", type="primary", use_container_width=True):
            _OVERRIDE_FLAG.touch()
            st.rerun()

    st.divider()

    # ── Refresh settings ───────────────────────────────────────────────────────
    st.markdown("**↺ Auto-Refresh**")
    refresh_s = st.slider("Interval (s)", 5, 120, 30, step=5)
    if st.button("Refresh Now", use_container_width=True):
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# Disclaimer gate — blur everything until accepted
# ══════════════════════════════════════════════════════════════════════════════

if not disclaimer_accepted:
    st.markdown("""
    <div class="unlock-overlay">
        <div class="unlock-title">🔒 Dashboard Locked</div>
        <div class="unlock-body">
            This Command Center displays live proprietary alpha signals and
            financial execution data.<br><br>
            You must review and accept the <b>Legal Disclaimer</b> in the
            sidebar before accessing live data.
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Blurred placeholder preview
    st.markdown('<div class="content-locked">', unsafe_allow_html=True)
    _ph1, _ph2, _ph3 = st.columns(3)
    with _ph1:
        st.metric("VIX Regime", "NORMAL ×1.00")
    with _ph2:
        st.metric("Alpha Signal", "BUY XOM")
    with _ph3:
        st.metric("Conviction", "HIGH")
    st.markdown("---")
    st.bar_chart({"Ship Count": [45, 48, 52, 61, 58, 47]})
    st.markdown('</div>', unsafe_allow_html=True)
    st.stop()


# ══════════════════════════════════════════════════════════════════════════════
# LIVE DATA (only reached after disclaimer accepted)
# ══════════════════════════════════════════════════════════════════════════════

telemetry = _read_telemetry()
ts        = telemetry.get("timestamp", "—")
scene     = telemetry.get("scene") or {}
truth     = telemetry.get("orbital_truth") or {}
alpha     = telemetry.get("alpha_signal") or telemetry.get("signal") or {}
detect    = telemetry.get("detection") or {}
status_v  = telemetry.get("status", "initializing")

port       = scene.get("port")
direction  = alpha.get("direction", "HOLD")
conviction = alpha.get("conviction", "LOW")
strength   = float(alpha.get("strength") or 0.0)
ticker     = alpha.get("ticker", "—")
sector     = alpha.get("sector", "—")
thesis     = truth.get("thesis", "Awaiting first orbital uplink…")
delta_pct  = truth.get("delta_pct")
dom_type   = truth.get("dominant_vessel_type", "—")

trades     = _load_trades(50)

# VIX: try trade log first, then live
vix_val, vix_regime = _vix_from_trades(trades)
if vix_val is None:
    vix_val, vix_regime = _vix_live()
if vix_val is None:
    vix_val, vix_regime = 18.0, "NORMAL"

# ── Title row ──────────────────────────────────────────────────────────────────
st.markdown("# 🛰️  AETHER FUND ONE — COMMAND CENTER")
st.caption(f"PROPRIETARY ALPHA · Schema {telemetry.get('schema_version','—')} · Last uplink: {ts}")

if _OVERRIDE_FLAG.exists():
    st.markdown(
        '<div class="override-active">⛔  SYSTEM OVERRIDE ACTIVE — ALL AGENTS HALTED</div>',
        unsafe_allow_html=True,
    )

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# Row 1 — VIX Regime Banner
# ══════════════════════════════════════════════════════════════════════════════

vix_is_danger = vix_val >= 30

if vix_is_danger:
    multipliers = {"≥40 PANIC": "0%", "30-40 FEARFUL": "25%"}
    current_mult = "0%" if vix_val >= 40 else "25%"
    st.markdown(
        f'<div class="vix-panic">'
        f'⚠  VIX = {vix_val:.1f}  ·  REGIME: {vix_regime}  ·  '
        f'POSITION MULTIPLIER: ×{current_mult}  ·  TRADING HALTED'
        f'</div>',
        unsafe_allow_html=True,
    )
else:
    mult_map = {"NORMAL": "100%", "ELEVATED": "75%", "STRESSED": "50%", "CALM": "100%"}
    mult_str = mult_map.get(vix_regime, "100%")
    st.markdown(
        f'<div class="vix-normal">'
        f'VIX = {vix_val:.1f}  ·  {vix_regime}  ·  Position Multiplier ×{mult_str}'
        f'</div>',
        unsafe_allow_html=True,
    )

st.markdown("<br>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# Row 2 — Alpha Signal + Orbital Truth
# ══════════════════════════════════════════════════════════════════════════════

sig_col, truth_col = st.columns([2, 3], gap="large")

with sig_col:
    st.markdown("##### ⬡ Alpha Signal")

    if direction == "BUY" and strength >= 0.3:
        css_cls  = "alpha-buy"
        dir_col  = "#00D4FF"
        icon     = "▲"
    elif direction == "SELL" and strength >= 0.3:
        css_cls  = "alpha-sell"
        dir_col  = "#FF5555"
        icon     = "▼"
    else:
        css_cls  = "alpha-hold"
        dir_col  = "#3A4A5A"
        icon     = "◌"

    st.markdown(
        f"""<div class="{css_cls}">
            <div class="alpha-label">PROPRIETARY ALPHA SIGNAL</div>
            <div class="alpha-dir" style="color:{dir_col}">{icon} {direction}</div>
            <div class="alpha-meta" style="color:{dir_col}">{ticker} · {sector.upper()}</div>
            <div class="alpha-meta">Conviction: {conviction} · Strength: {strength:.0%}</div>
        </div>""",
        unsafe_allow_html=True,
    )

    st.markdown("<br>", unsafe_allow_html=True)

    # Conviction × VIX size table
    mult_val = (
        0.00 if vix_val >= 40 else
        0.25 if vix_val >= 30 else
        0.50 if vix_val >= 25 else
        0.75 if vix_val >= 20 else
        1.00
    )
    base_pcts = {"EXTREME": 0.08, "HIGH": 0.05, "MEDIUM": 0.025, "LOW": 0.0}
    size_rows = []
    for conv, base in base_pcts.items():
        final = base * mult_val
        active = "▶ " if conv == conviction else ""
        size_rows.append({
            "Conviction": f"{active}{conv}",
            "Base":       f"{base:.0%}",
            "×VIX":       f"×{mult_val:.2f}",
            "Final":      f"{final:.2%}" if final > 0 else "SKIP",
        })
    st.dataframe(
        pd.DataFrame(size_rows),
        use_container_width=True,
        hide_index=True,
        height=185,
    )

with truth_col:
    st.markdown("##### 🌍 Orbital Truth")

    # Metrics
    t1, t2, t3 = st.columns(3)
    with t1:
        st.metric("Port", _PORT_LABELS.get(port, port or "—"))
    with t2:
        delta_str = f"{delta_pct:+.1f}%" if delta_pct is not None else "—"
        delta_colour = "normal" if delta_pct is None else ("off" if abs(delta_pct) < 15 else "normal")
        st.metric("Vessel Δ", delta_str)
    with t3:
        st.metric("Type", dom_type.replace("_", " ").title() if dom_type else "—")

    # Thesis
    st.markdown(
        f'<div class="thesis-box">"{thesis}"</div>',
        unsafe_allow_html=True,
    )

    # Live PROPRIETARY_ALPHA feed using st.empty()
    st.markdown("##### 📡 Live Alpha Feed")
    feed_placeholder = st.empty()

    if trades:
        feed_df = pd.DataFrame(trades[:12])
        cols    = [c for c in ["timestamp", "ticker", "direction", "conviction",
                               "notional", "vix", "vix_regime", "thesis"]
                   if c in feed_df.columns]
        feed_df = feed_df[cols].copy()
        if "notional" in feed_df.columns:
            feed_df["notional"] = feed_df["notional"].apply(
                lambda x: f"${x:,.2f}" if x is not None else "—"
            )
        if "timestamp" in feed_df.columns:
            feed_df["timestamp"] = feed_df["timestamp"].apply(
                lambda x: x[:19].replace("T", " ") if x else "—"
            )
        feed_placeholder.dataframe(
            feed_df.rename(columns={
                "timestamp": "Time", "ticker": "Ticker", "direction": "Side",
                "conviction": "Conv.", "notional": "Notional",
                "vix": "VIX", "vix_regime": "Regime", "thesis": "Thesis",
            }),
            use_container_width=True,
            hide_index=True,
            height=260,
        )
    else:
        feed_placeholder.caption("No trades executed yet — feed will populate on first alpha signal.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# Row 3 — Orbital Map + Detection breakdown
# ══════════════════════════════════════════════════════════════════════════════

map_col, det_col = st.columns([3, 2], gap="large")

with map_col:
    st.markdown("##### 🗺️ Orbital Ground Track")
    lats, lons, cur_lat, cur_lon = _ground_track()

    fig = go.Figure()
    fig.add_trace(go.Scattergeo(
        lat=lats, lon=lons, mode="lines",
        line=dict(color="#00D4FF", width=1.5), opacity=0.40,
        name="Track", hoverinfo="skip",
    ))
    fig.add_trace(go.Scattergeo(
        lat=[cur_lat], lon=[cur_lon], mode="markers",
        marker=dict(size=12, color="#00D4FF", symbol="circle",
                    line=dict(color="#FFF", width=1.5)),
        name="Sentinel-2",
        hovertemplate="<b>Sentinel-2</b><br>%.2f° %.2f°<extra></extra>" % (cur_lat, cur_lon),
    ))
    for pname, (plat, plon) in _PORT_COORDS.items():
        active = pname == port
        fig.add_trace(go.Scattergeo(
            lat=[plat], lon=[plon], mode="markers+text",
            marker=dict(size=14 if active else 9,
                        color="#FF6600" if active else "#1E3A5A",
                        symbol="diamond",
                        line=dict(color="#FFF" if active else "#223344", width=1)),
            text=[_PORT_LABELS[pname]], textposition="top center",
            textfont=dict(color="#FFAA44" if active else "#334455", size=11),
            name=_PORT_LABELS[pname],
            hovertemplate=f"<b>{_PORT_LABELS[pname]}</b>{'<br>ACTIVE' if active else ''}<extra></extra>",
        ))
    fig.update_layout(
        geo=dict(showland=True, landcolor="#131920", showocean=True,
                 oceancolor="#0A0E14", showcoastlines=True,
                 coastlinecolor="#1E3A5A", showcountries=True,
                 countrycolor="#0D1929", bgcolor="#0E1117",
                 projection_type="natural earth"),
        paper_bgcolor="#0E1117", margin=dict(l=0, r=0, t=0, b=0), height=360,
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

with det_col:
    st.markdown("##### 📊 Detection Intelligence")

    ship_count = detect.get("ship_count")
    conf_mean  = detect.get("confidence_mean")
    infer_ms   = detect.get("inference_ms")
    vb         = detect.get("vessel_breakdown") or {}

    d1, d2 = st.columns(2)
    with d1:
        st.metric("Ships Detected", ship_count if ship_count is not None else "—")
        st.metric("Confidence",
                  f"{conf_mean:.2f}" if conf_mean is not None else "—")
    with d2:
        st.metric("Inference", f"{infer_ms}ms" if infer_ms is not None else "—")
        st.metric("Cloud Cover",
                  f"{scene.get('cloud_cover_pct', '—'):.1f}%"
                  if scene.get("cloud_cover_pct") is not None else "—")

    # Vessel breakdown bar chart
    if vb:
        vb_df = pd.DataFrame([{
            "Type":  "Tankers",       "Count": vb.get("tankers", 0),
        }, {
            "Type":  "Bulk Carriers", "Count": vb.get("bulk_carriers", 0),
        }, {
            "Type":  "Container",     "Count": vb.get("container", 0),
        }]).set_index("Type")

        vb_fig = go.Figure(go.Bar(
            x=vb_df.index.tolist(),
            y=vb_df["Count"].tolist(),
            marker_color=["#00D4FF", "#0088AA", "#004466"],
            text=vb_df["Count"].tolist(),
            textposition="outside",
            textfont=dict(color="#C9D1D9"),
        ))
        vb_fig.update_layout(
            paper_bgcolor="#0E1117", plot_bgcolor="#131920",
            margin=dict(l=10, r=10, t=20, b=20), height=200,
            yaxis=dict(gridcolor="#1E2A38", color="#6E7C8C"),
            xaxis=dict(color="#6E7C8C"),
            font=dict(color="#C9D1D9"),
        )
        st.plotly_chart(vb_fig, use_container_width=True, config={"displayModeBar": False})
    else:
        st.caption("Vessel breakdown will populate after decryption of detection_enc block.")

    # Tile info
    st.caption(
        f"Tile: `{scene.get('tile_id','—')}`  |  "
        f"Acq: `{scene.get('acquisition_date','—')}`  |  "
        f"Model: `{detect.get('model','yolov8n-ship')}`"
    )

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# Row 4 — System Health Log tail
# ══════════════════════════════════════════════════════════════════════════════

with st.expander("🏥 System Health Log", expanded=False):
    if _HEALTH_LOG.exists():
        lines = _HEALTH_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        st.code("\n".join(lines[-40:]), language=None)
    else:
        st.caption("system_health.log not found — start run_system.py to populate.")

# ── Footer ─────────────────────────────────────────────────────────────────────
st.caption(
    f"Last uplink: `{ts}`  ·  "
    f"Schema: `{telemetry.get('schema_version','—')}`  ·  "
    f"Auto-refresh: {refresh_s}s  ·  "
    f"Override: {'ACTIVE ⛔' if _OVERRIDE_FLAG.exists() else 'off'}"
)

# ── Auto-refresh via meta-refresh tag ─────────────────────────────────────────
st.markdown(
    f'<meta http-equiv="refresh" content="{refresh_s}">',
    unsafe_allow_html=True,
)
