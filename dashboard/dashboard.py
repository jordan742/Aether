"""
Aether Fund One — Master Mission Control
-----------------------------------------
Four-panel Streamlit dashboard:

  1. Orbital Map        — real-time simulated Sentinel-2 ground track over
                          the four maritime chokepoints, auto-advancing each
                          tick based on wall-clock time (100 min orbit).
  2. Alpha Signal       — neon-blue pulsing indicator when a ship-count alpha
                          is detected; dims to grey on HOLD.
  3. Live P&L Ticker    — equity, cash, open P&L, and a scrollable trade log
                          sourced from shared/trades.jsonl + Alpaca live data.
  4. System Override    — single red button that writes shared/OVERRIDE and
                          immediately halts both the gateway and equity-bot loops.

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

# ── Path bootstrap ─────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
load_dotenv(_ROOT / ".env")

from shared.bridge import TelemetryBridge  # noqa: E402

# ── Override flag path ─────────────────────────────────────────────────────────
_OVERRIDE_FLAG = _ROOT / "shared" / "OVERRIDE"
_TRADES_LOG    = _ROOT / "shared" / "trades.jsonl"

# ── Port AOI centres [lat, lon] ────────────────────────────────────────────────
_PORT_COORDS: dict[str, tuple[float, float]] = {
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

# ── Orbital simulation constants ───────────────────────────────────────────────
_ORBIT_PERIOD_S  = 5_933   # Sentinel-2: ~98.9 min in seconds
_ORBIT_INCLINATION = 98.6  # sun-synchronous, degrees


# ══════════════════════════════════════════════════════════════════════════════
# Page config — must be first Streamlit call
# ══════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Aether — Mission Control",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Custom CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Dark space background */
[data-testid="stAppViewContainer"] {
    background: #080c14;
    color: #e0e8f0;
}
[data-testid="stHeader"] { background: transparent; }
[data-testid="stSidebar"] { background: #0d1321; }

/* Metric cards */
[data-testid="metric-container"] {
    background: #0d1929;
    border: 1px solid #1e3050;
    border-radius: 8px;
    padding: 12px 16px;
}

/* Neon blue alpha signal — active */
.alpha-active {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 180px;
    border-radius: 12px;
    background: #020d1a;
    border: 2px solid #00c8ff;
    box-shadow: 0 0 24px #00c8ff, 0 0 60px #0077aa, inset 0 0 30px #001a2e;
    animation: pulse 1.6s ease-in-out infinite;
}
.alpha-active-text {
    font-size: 1.5rem;
    font-weight: 700;
    color: #00e5ff;
    text-shadow: 0 0 12px #00c8ff, 0 0 24px #0099cc;
    letter-spacing: 0.08em;
}

/* Grey — no signal */
.alpha-inactive {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 180px;
    border-radius: 12px;
    background: #0a0e14;
    border: 2px solid #1e2a38;
    box-shadow: none;
}
.alpha-inactive-text {
    font-size: 1.4rem;
    font-weight: 600;
    color: #3a4a5a;
    letter-spacing: 0.06em;
}

/* Sell signal — red glow */
.alpha-sell {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 180px;
    border-radius: 12px;
    background: #140a0a;
    border: 2px solid #ff3030;
    box-shadow: 0 0 24px #ff2020, 0 0 60px #880000, inset 0 0 30px #1a0000;
    animation: pulse 1.6s ease-in-out infinite;
}
.alpha-sell-text {
    font-size: 1.5rem;
    font-weight: 700;
    color: #ff5555;
    text-shadow: 0 0 12px #ff2222;
    letter-spacing: 0.08em;
}

@keyframes pulse {
    0%,100% { opacity: 1.0; }
    50%      { opacity: 0.65; }
}

/* Override button */
div[data-testid="stButton"] > button[kind="primary"] {
    background: #8b0000 !important;
    border: 2px solid #ff2020 !important;
    color: #ffffff !important;
    font-weight: 700 !important;
    letter-spacing: 0.1em !important;
    box-shadow: 0 0 16px #ff000066;
}
div[data-testid="stButton"] > button[kind="primary"]:hover {
    background: #cc0000 !important;
    box-shadow: 0 0 32px #ff0000aa;
}

/* Trade log table */
[data-testid="stDataFrame"] { background: #0a1020; }

/* Divider */
hr { border-color: #1e3050; }

/* P&L positive/negative colouring handled inline */
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


def _alpaca_safe() -> dict | None:
    """Return {equity, cash, positions} or None if Alpaca is unavailable."""
    try:
        spec = importlib.util.spec_from_file_location(
            "equity_bot.alpaca_client",
            _ROOT / "equity-bot" / "alpaca_client.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        client = mod.AlpacaClient()

        loop = asyncio.new_event_loop()
        try:
            equity = loop.run_until_complete(client.get_equity())
            cash   = loop.run_until_complete(client.get_cash())
        finally:
            loop.close()

        return {"equity": equity, "cash": cash}
    except Exception:
        return None


def _load_trades(n: int = 30) -> list[dict]:
    """Read the last *n* entries from shared/trades.jsonl."""
    if not _TRADES_LOG.exists():
        return []
    lines = _TRADES_LOG.read_text(encoding="utf-8").strip().splitlines()
    parsed = []
    for line in reversed(lines[-n:]):
        try:
            parsed.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return parsed


def _override_active() -> bool:
    return _OVERRIDE_FLAG.exists()


def _ground_track(n_trail: int = 120) -> tuple[list[float], list[float], float, float]:
    """
    Simulate a sun-synchronous ground track centred on the current wall-clock time.

    Returns (lats, lons, current_lat, current_lon) where (lats, lons) is the
    trail of the last *n_trail* simulation steps (1 step = 30 s of orbit).
    """
    now_s = time.time()
    inc   = math.radians(_ORBIT_INCLINATION)
    lats, lons = [], []

    for i in range(-n_trail, 1):
        t = now_s + i * 30          # 30-second steps back in time
        # Orbital angle [0, 2π)
        theta = (2 * math.pi * t / _ORBIT_PERIOD_S) % (2 * math.pi)
        # Ascending-node longitude drifts ~24.7°/day (sun-synchronous)
        omega = math.radians((t / 86_400) * 24.7 % 360)

        lat = math.degrees(math.asin(math.sin(inc) * math.sin(theta)))
        lon = math.degrees(omega + math.atan2(
            math.cos(inc) * math.sin(theta), math.cos(theta)
        ))
        lon = ((lon + 180) % 360) - 180   # wrap to [-180, 180]

        lats.append(round(lat, 4))
        lons.append(round(lon, 4))

    return lats, lons, lats[-1], lons[-1]


def _build_map(telemetry: dict) -> go.Figure:
    port  = (telemetry.get("scene") or {}).get("port")
    lats, lons, cur_lat, cur_lon = _ground_track()

    fig = go.Figure()

    # ── Ground track trail ─────────────────────────────────────────────────────
    fig.add_trace(go.Scattergeo(
        lat=lats,
        lon=lons,
        mode="lines",
        line=dict(color="#00c8ff", width=1.5),
        opacity=0.45,
        name="Ground Track",
        hoverinfo="skip",
    ))

    # ── Current satellite position ─────────────────────────────────────────────
    fig.add_trace(go.Scattergeo(
        lat=[cur_lat],
        lon=[cur_lon],
        mode="markers",
        marker=dict(
            size=12,
            color="#00e5ff",
            symbol="circle",
            line=dict(color="#ffffff", width=1.5),
        ),
        name="Sentinel-2",
        hovertemplate="<b>Sentinel-2</b><br>Lat: %{lat:.2f}°<br>Lon: %{lon:.2f}°<extra></extra>",
    ))

    # ── Port AOI markers ───────────────────────────────────────────────────────
    for pname, (plat, plon) in _PORT_COORDS.items():
        is_active = pname == port
        label     = _PORT_LABELS[pname]
        fig.add_trace(go.Scattergeo(
            lat=[plat],
            lon=[plon],
            mode="markers+text",
            marker=dict(
                size=14 if is_active else 9,
                color="#ff6600" if is_active else "#334466",
                symbol="diamond",
                line=dict(color="#ffffff" if is_active else "#223344", width=1),
            ),
            text=[label],
            textposition="top center",
            textfont=dict(
                color="#ffaa44" if is_active else "#445566",
                size=11,
            ),
            name=label,
            hovertemplate=(
                f"<b>{label}</b><br>{'ACTIVE AOI' if is_active else ''}<extra></extra>"
            ),
        ))

    fig.update_layout(
        geo=dict(
            showland=True,
            landcolor="#0d1929",
            showocean=True,
            oceancolor="#060e1a",
            showcoastlines=True,
            coastlinecolor="#1e3a5a",
            showlakes=False,
            showcountries=True,
            countrycolor="#102030",
            bgcolor="#080c14",
            projection_type="natural earth",
        ),
        paper_bgcolor="#080c14",
        plot_bgcolor="#080c14",
        margin=dict(l=0, r=0, t=0, b=0),
        height=380,
        showlegend=False,
    )
    return fig


def _build_ship_gauge(ship_count: int | None, port: str | None) -> go.Figure:
    hist = {
        "strait_of_gibraltar": 45,
        "strait_of_hormuz":    38,
        "singapore_strait":    62,
        "english_channel":     55,
    }
    baseline = hist.get(port or "", 45)
    value    = ship_count if ship_count is not None else 0
    maximum  = int(baseline * 1.8)

    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=value,
        delta={"reference": baseline, "valueformat": ".0f",
               "increasing": {"color": "#00c8ff"},
               "decreasing": {"color": "#ff4444"}},
        title={"text": "Ships Detected", "font": {"color": "#8ab4cc", "size": 13}},
        number={"font": {"color": "#e0f0ff", "size": 36}},
        gauge={
            "axis": {"range": [0, maximum], "tickcolor": "#445566",
                     "tickfont": {"color": "#445566"}},
            "bar": {"color": "#00c8ff"},
            "bgcolor": "#0a1520",
            "bordercolor": "#1e3050",
            "steps": [
                {"range": [0, baseline * 0.85],          "color": "#0d1929"},
                {"range": [baseline * 0.85, baseline * 1.15], "color": "#112233"},
                {"range": [baseline * 1.15, maximum],    "color": "#0d1929"},
            ],
            "threshold": {
                "line": {"color": "#ff8800", "width": 2},
                "thickness": 0.8,
                "value": baseline,
            },
        },
    ))
    fig.update_layout(
        paper_bgcolor="#080c14",
        height=200,
        margin=dict(l=10, r=10, t=30, b=10),
    )
    return fig


def _pl_colour(value: float) -> str:
    return "#00e676" if value >= 0 else "#ff5252"


# ══════════════════════════════════════════════════════════════════════════════
# Header row
# ══════════════════════════════════════════════════════════════════════════════

hcol1, hcol2, hcol3 = st.columns([3, 5, 2])
with hcol1:
    st.markdown("## 🛰️  Aether Fund One")
    st.caption("Master Mission Control · v2.0")
with hcol2:
    override_already = _override_active()
    if override_already:
        st.markdown(
            "<div style='text-align:center;padding:12px;background:#1a0000;"
            "border:2px solid #ff2020;border-radius:8px;color:#ff5555;"
            "font-weight:700;letter-spacing:.1em;font-size:1.1rem'>"
            "⛔  SYSTEM OVERRIDE ACTIVE — ALL AGENTS HALTED"
            "</div>",
            unsafe_allow_html=True,
        )
with hcol3:
    if not override_already:
        if st.button("⛔  SYSTEM OVERRIDE", type="primary", use_container_width=True):
            _OVERRIDE_FLAG.touch()
            st.session_state["override_fired"] = True
            st.rerun()
    else:
        if st.button("↺  Clear Override", use_container_width=True):
            _OVERRIDE_FLAG.unlink(missing_ok=True)
            st.rerun()

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# Read live data
# ══════════════════════════════════════════════════════════════════════════════

telemetry   = _read_telemetry()
ts          = telemetry.get("timestamp", "—")
status      = telemetry.get("status", "initializing")
scene       = telemetry.get("scene") or {}
detection   = telemetry.get("detection") or {}
signal      = telemetry.get("signal") or {}

port        = scene.get("port")
tile_id     = scene.get("tile_id", "—")
cloud_pct   = scene.get("cloud_cover_pct")
acq_date    = scene.get("acquisition_date", "—")

ship_count  = detection.get("ship_count")
conf_mean   = detection.get("confidence_mean")
large_v     = detection.get("large_vessels")
small_v     = detection.get("small_vessels")
infer_ms    = detection.get("inference_ms")

direction   = signal.get("direction", "HOLD")
strength    = signal.get("strength") or 0.0
ticker      = signal.get("ticker", "—")
rationale   = signal.get("rationale", "—")

alpaca_data = _alpaca_safe()
trades      = _load_trades(50)

# ══════════════════════════════════════════════════════════════════════════════
# Row 1 — Status metrics
# ══════════════════════════════════════════════════════════════════════════════

mc1, mc2, mc3, mc4, mc5 = st.columns(5)
with mc1:
    st.metric("Gateway", status.upper(),
              delta="LIVE" if status == "active" else None)
with mc2:
    st.metric("Active Port", _PORT_LABELS.get(port, "—") if port else "—")
with mc3:
    st.metric("Tile", tile_id)
with mc4:
    st.metric("Cloud Cover", f"{cloud_pct:.1f}%" if cloud_pct is not None else "—")
with mc5:
    st.metric("Model", detection.get("model", "yolov8n-ship"))

st.markdown("<br>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# Row 2 — Orbital Map (left) + Alpha Signal Indicator (right)
# ══════════════════════════════════════════════════════════════════════════════

map_col, sig_col = st.columns([3, 2], gap="large")

with map_col:
    st.markdown("##### Orbital Ground Track")
    st.plotly_chart(_build_map(telemetry), use_container_width=True,
                    config={"displayModeBar": False})

with sig_col:
    st.markdown("##### Alpha Signal")

    # ── Neon indicator ────────────────────────────────────────────────────────
    if direction == "BUY" and strength >= 0.3:
        st.markdown(
            f"""<div class="alpha-active">
                <div class="alpha-active-text">
                    ⬡ ALPHA DETECTED<br>
                    <span style="font-size:.9rem;opacity:.85">{ticker} · BUY · {strength:.0%}</span>
                </div>
            </div>""",
            unsafe_allow_html=True,
        )
    elif direction == "SELL" and strength >= 0.3:
        st.markdown(
            f"""<div class="alpha-sell">
                <div class="alpha-sell-text">
                    ⬡ SHORT SIGNAL<br>
                    <span style="font-size:.9rem;opacity:.85">{ticker} · SELL · {strength:.0%}</span>
                </div>
            </div>""",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            """<div class="alpha-inactive">
                <div class="alpha-inactive-text">◌ NO SIGNAL — HOLD</div>
            </div>""",
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Ship gauge ────────────────────────────────────────────────────────────
    st.plotly_chart(_build_ship_gauge(ship_count, port),
                    use_container_width=True, config={"displayModeBar": False})

    # ── Detection breakdown ───────────────────────────────────────────────────
    dc1, dc2, dc3 = st.columns(3)
    with dc1:
        st.metric("Large", large_v if large_v is not None else "—")
    with dc2:
        st.metric("Small", small_v if small_v is not None else "—")
    with dc3:
        st.metric("Infer ms", infer_ms if infer_ms is not None else "—")

    st.caption(f"Rationale: `{rationale}`  |  Conf: "
               f"{f'{conf_mean:.2f}' if conf_mean is not None else '—'}")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# Row 3 — Live P&L Ticker
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("##### Live P&L Ticker")

pl_c1, pl_c2, pl_c3, pl_c4 = st.columns(4)

if alpaca_data:
    equity = alpaca_data["equity"]
    cash   = alpaca_data["cash"]
    invested = equity - cash
    # Approximate session P&L from trade log
    session_pl = sum(t.get("pnl", 0.0) for t in trades)

    with pl_c1:
        st.metric("Portfolio Equity", f"${equity:,.2f}")
    with pl_c2:
        st.metric("Cash", f"${cash:,.2f}")
    with pl_c3:
        st.metric("Invested", f"${invested:,.2f}")
    with pl_c4:
        colour = _pl_colour(session_pl)
        st.markdown(
            f"<div style='padding:12px;background:#0d1929;border:1px solid #1e3050;"
            f"border-radius:8px;text-align:center'>"
            f"<div style='font-size:.75rem;color:#8ab4cc;margin-bottom:4px'>Session P&L</div>"
            f"<div style='font-size:1.6rem;font-weight:700;color:{colour}'>"
            f"{'+'if session_pl>=0 else ''}${session_pl:,.2f}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
else:
    st.info("Alpaca connection unavailable — set ALPACA_API_KEY / ALPACA_SECRET_KEY in .env")
    # Derive session P&L from trade log only
    session_pl = sum(t.get("pnl", 0.0) for t in trades)
    with pl_c4:
        colour = _pl_colour(session_pl)
        st.markdown(
            f"<div style='padding:12px;background:#0d1929;border:1px solid #1e3050;"
            f"border-radius:8px;text-align:center'>"
            f"<div style='font-size:.75rem;color:#8ab4cc;margin-bottom:4px'>Log P&L</div>"
            f"<div style='font-size:1.5rem;font-weight:700;color:{colour}'>"
            f"{'+'if session_pl>=0 else ''}${session_pl:,.2f}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

st.markdown("<br>", unsafe_allow_html=True)

# ── Trade log table ────────────────────────────────────────────────────────────
if trades:
    df = pd.DataFrame(trades)
    # Normalise columns
    for col in ["timestamp", "ticker", "direction", "notional", "pnl"]:
        if col not in df.columns:
            df[col] = None
    df = df[["timestamp", "ticker", "direction", "notional", "pnl"]].copy()
    df["notional"] = df["notional"].apply(
        lambda x: f"${x:,.2f}" if x is not None else "—"
    )
    df["pnl"] = df["pnl"].apply(
        lambda x: f"{'+'if x and x>=0 else ''}${x:,.2f}" if x is not None else "—"
    )
    st.dataframe(
        df.rename(columns={
            "timestamp": "Time", "ticker": "Ticker",
            "direction": "Side", "notional": "Notional", "pnl": "P&L",
        }),
        use_container_width=True,
        hide_index=True,
        height=220,
    )
else:
    st.caption("No trades logged yet — trades appear here once the equity-bot executes orders.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# Row 4 — Footer: last telemetry + auto-refresh
# ══════════════════════════════════════════════════════════════════════════════

fc1, fc2 = st.columns([4, 1])
with fc1:
    st.caption(
        f"Last telemetry: `{ts}`  |  "
        f"Acq date: `{acq_date}`  |  "
        f"Schema: `{telemetry.get('schema_version', '—')}`"
    )
with fc2:
    if st.button("↺ Refresh", use_container_width=True):
        st.rerun()
