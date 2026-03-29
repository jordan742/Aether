"""
Aether Fund One — Mission Control Dashboard
--------------------------------------------
Streamlit app that visualises live telemetry from the Sovereign Bridge and
equity-bot performance via the Alpaca paper trading account.

Run:
    streamlit run dashboard/app.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

from shared.bridge import TelemetryBridge

# ── Page config ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Aether Fund One",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.title("🛰️  Aether Fund One — Mission Control")
st.caption("Sovereign Bridge | Orbital Gateway | Equity Bot")

# ── Helpers ────────────────────────────────────────────────────────────────────

@st.cache_resource
def get_bridge() -> TelemetryBridge:
    return TelemetryBridge()


def read_telemetry() -> dict:
    bridge = get_bridge()
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(bridge.read())
    finally:
        loop.close()


def signal_colour(direction: str | None) -> str:
    return {"BUY": "green", "SELL": "red", "HOLD": "orange"}.get(direction or "HOLD", "grey")


# ── Live telemetry ─────────────────────────────────────────────────────────────

telemetry = read_telemetry()
status = telemetry.get("status", "unknown")
ts = telemetry.get("timestamp", "—")
signal = telemetry.get("signal", {})
spectral = telemetry.get("spectral", {})
scene = telemetry.get("scene", {})
anomaly = telemetry.get("anomaly", {})

direction = signal.get("direction", "—")
strength = signal.get("strength")
ticker = signal.get("ticker", "—")

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Gateway Status", status.upper())
with col2:
    colour = signal_colour(direction)
    st.metric("Signal", f"{direction} ({ticker})")
with col3:
    st.metric("Signal Strength", f"{strength:.0%}" if strength is not None else "—")
with col4:
    st.metric("Anomaly", "YES ⚠️" if anomaly.get("detected") else "NO ✓")

st.divider()

# ── Spectral stats ─────────────────────────────────────────────────────────────

st.subheader("Spectral Indices")
scol1, scol2, scol3, scol4 = st.columns(4)

with scol1:
    ndvi = spectral.get("ndvi_mean")
    st.metric("NDVI Mean", f"{ndvi:.4f}" if ndvi is not None else "—",
              help="Normalised Difference Vegetation Index. >0.65 = healthy crop.")
with scol2:
    ndwi = spectral.get("ndwi_mean")
    st.metric("NDWI Mean", f"{ndwi:.4f}" if ndwi is not None else "—",
              help="Normalised Difference Water Index. Negative = water-stressed.")
with scol3:
    evi = spectral.get("evi_mean")
    st.metric("EVI Mean", f"{evi:.4f}" if evi is not None else "—",
              help="Enhanced Vegetation Index.")
with scol4:
    std = spectral.get("ndvi_std")
    st.metric("NDVI Std Dev", f"{std:.4f}" if std is not None else "—",
              help="Spatial variability — high values suggest heterogeneous stress.")

# ── NDVI gauge ─────────────────────────────────────────────────────────────────

if ndvi is not None:
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=ndvi,
        title={"text": "NDVI"},
        gauge={
            "axis": {"range": [-1, 1]},
            "bar": {"color": "green"},
            "steps": [
                {"range": [-1, 0.35], "color": "#ff4b4b"},
                {"range": [0.35, 0.65], "color": "#ffa500"},
                {"range": [0.65, 1.0],  "color": "#21c354"},
            ],
            "threshold": {
                "line": {"color": "white", "width": 4},
                "thickness": 0.75,
                "value": ndvi,
            },
        },
    ))
    fig.update_layout(height=280, margin=dict(t=30, b=10))
    st.plotly_chart(fig, use_container_width=True)

# ── Scene info ─────────────────────────────────────────────────────────────────

st.subheader("Scene Metadata")
st.json({
    "tile_id": scene.get("tile_id", "—"),
    "acquisition_date": scene.get("acquisition_date", "—"),
    "cloud_cover_pct": scene.get("cloud_cover_pct", "—"),
    "bbox": scene.get("bbox", "—"),
    "last_update": ts,
})

# ── Anomaly panel ──────────────────────────────────────────────────────────────

if anomaly.get("detected"):
    st.warning(
        f"**Anomaly detected:** {anomaly.get('type')}  |  "
        f"Confidence: {anomaly.get('confidence', 0):.0%}  |  "
        f"Affected area: {anomaly.get('affected_area_km2')} km²"
    )

# ── Alpaca equity (optional) ───────────────────────────────────────────────────

st.divider()
st.subheader("Paper Portfolio")

try:
    from equity_bot.alpaca_client import AlpacaClient  # noqa: F401
    alpaca = AlpacaClient()
    equity = alpaca.get_equity()
    cash = alpaca.get_cash()
    position = alpaca.get_position(ticker) if ticker != "—" else None

    pcol1, pcol2, pcol3 = st.columns(3)
    with pcol1:
        st.metric("Equity", f"${equity:,.2f}")
    with pcol2:
        st.metric("Cash", f"${cash:,.2f}")
    with pcol3:
        if position:
            pl = position["unrealised_pl"]
            st.metric(f"{ticker} P&L", f"${pl:,.2f}", delta=f"${pl:,.2f}")
        else:
            st.metric(f"{ticker} Position", "Flat")
except Exception as exc:
    st.info(f"Alpaca connection unavailable: {exc}")

# ── Auto-refresh ───────────────────────────────────────────────────────────────

st.caption(f"Last telemetry timestamp: {ts}")
if st.button("Refresh"):
    st.rerun()
