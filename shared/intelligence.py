"""
shared/intelligence.py — Aether Intelligence Engine
------------------------------------------------------
Stateless analytics layer.  Takes ship count observations and returns:
  - trend_label          Human-readable trend narrative
  - recommendation       Sector / action recommendation
  - insight_category     BULLISH | BEARISH | NEUTRAL | WATCH
  - ship_series          pd.DataFrame for the Satellite Trend line chart
  - xom_series           pd.DataFrame of recent XOM closing prices
  - insights             Bullet list for the Strategic Insights sidebar

No file I/O, no subprocess calls — safe for Streamlit Cloud.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import yfinance as yf


# ── Output dataclass ────────────────────────────────────────────────────────────

@dataclass
class TrendReport:
    trend_label:        str
    recommendation:     str
    insight_category:   str                # BULLISH | BEARISH | NEUTRAL | WATCH
    delta_vs_baseline:  Optional[float]    # e.g. 0.15 → +15 %
    current_count:      Optional[int]
    baseline_count:     Optional[float]
    dominant_type:      str
    ship_series:        pd.DataFrame       # index=timestamp, col=ship_count
    xom_series:         pd.DataFrame       # cols=[Date, Close]
    insights:           list[str] = field(default_factory=list)


# ── Vessel-type → sector recommendation map ────────────────────────────────────

_RECO: dict[str, dict[str, tuple[str, str]]] = {
    "tanker": {
        "up":   ("BULLISH",
                 "Energy supply pressure detected — crude tanker congestion at chokepoint. "
                 "Consider Energy sector exposure ($XOM, $USO, $OIH)."),
        "down": ("BEARISH",
                 "Tanker flow easing — potential crude supply relief. "
                 "Energy sector headwinds likely near-term."),
        "flat": ("NEUTRAL",
                 "Tanker flow stable — no directional energy signal detected. "
                 "Hold existing Energy positions."),
    },
    "bulk_carrier": {
        "up":   ("BULLISH",
                 "Bulk carrier surge detected — commodity demand expansion signal. "
                 "Monitor Baltic Dry Index and mining equities ($BDRY, $BHP)."),
        "down": ("BEARISH",
                 "Bulk carrier decline — commodity demand softening. "
                 "Defensive positioning in materials sector warranted."),
        "flat": ("WATCH",
                 "Bulk carrier flow neutral — await volume confirmation before positioning."),
    },
    "container": {
        "up":   ("BULLISH",
                 "Container ship acceleration — global trade flow expansion confirmed. "
                 "Consider logistics and shipping exposure ($ZIM, $MATX)."),
        "down": ("BEARISH",
                 "Container traffic contracting — supply chain tightening signal. "
                 "Monitor tech and retail margin compression."),
        "flat": ("NEUTRAL",
                 "Container throughput stable — no macro disruption signal detected."),
    },
    "unknown": {
        "up":   ("WATCH",  "Vessel activity increasing — type classification pending. Monitor chokepoint."),
        "down": ("WATCH",  "Vessel activity declining — insufficient data for sector mapping."),
        "flat": ("NEUTRAL","Vessel activity nominal. Awaiting classification data."),
    },
}


# ── Internal helpers ────────────────────────────────────────────────────────────

def _direction(delta: Optional[float]) -> str:
    if delta is None:
        return "flat"
    return "up" if delta > 0.05 else "down" if delta < -0.05 else "flat"


def _trend_label(
    dominant_type: str,
    delta: Optional[float],
    current: Optional[int],
    baseline: Optional[float],
    direction: str,
    port: str,
) -> str:
    port_name  = port.replace("_", " ").title() if port else "chokepoint"
    type_label = dominant_type.replace("_", " ") if dominant_type else "vessel"

    if delta is None or baseline is None:
        return f"Accumulating orbital baseline at {port_name}… (need ≥ 3 observations)"

    pct      = abs(delta) * 100
    dir_word = "above" if direction == "up" else "below" if direction == "down" else "at"
    return (
        f"Inward {type_label} flow is {pct:.0f}% {dir_word} 30-observation baseline "
        f"at {port_name}  ({current} ships observed vs {baseline:.0f} avg)"
    )


def _build_insights(
    dominant_type: str,
    direction: str,
    delta: Optional[float],
    current: Optional[int],
    port: str,
) -> list[str]:
    port_name = port.replace("_", " ").title() if port else "chokepoint"
    out: list[str] = []

    if delta is not None:
        pct    = abs(delta) * 100
        symbol = "▲" if direction == "up" else "▼" if direction == "down" else "→"
        out.append(f"{symbol} **{pct:.0f}% flow deviation** at {port_name}")

    if dominant_type == "tanker":
        out.append("⚡ **Energy correlation**: crude tanker density → WTI price pressure")
        out.append("🛢️  Watch: `$XOM` `$CVX` `$USO` `$OIH`")
    elif dominant_type == "bulk_carrier":
        out.append("⚓ **Commodity demand**: bulk carrier surge → iron ore / coal flow")
        out.append("📦 Watch: `$BDRY` `$BHP` `$RIO`")
    elif dominant_type == "container":
        out.append("🏭 **Trade flow signal**: container throughput → global supply chain health")
        out.append("🚢 Watch: `$ZIM` `$MATX` `$SOXS`")

    if current is not None:
        if current > 20:
            out.append(f"🔴 **Anomalous traffic**: {current} vessels in AOI — high-density event")
        elif current > 10:
            out.append(f"🟡 Moderate traffic: {current} vessels — elevated but within normal range")
        else:
            out.append(f"🟢 Normal traffic: {current} vessels in AOI")

    return out


def _fetch_xom(period: str = "1mo") -> pd.DataFrame:
    try:
        raw = yf.download("XOM", period=period, interval="1d",
                          progress=False, auto_adjust=True)
        if raw.empty:
            return pd.DataFrame(columns=["Date", "Close"])
        df = raw[["Close"]].reset_index()
        df.columns = ["Date", "Close"]
        df["Date"] = pd.to_datetime(df["Date"]).dt.date
        return df.dropna()
    except Exception:
        return pd.DataFrame(columns=["Date", "Close"])


# ── Public API ──────────────────────────────────────────────────────────────────

def analyse(
    current_detection: dict,
    history: list[dict],
    port: str = "",
) -> TrendReport:
    """
    Parameters
    ----------
    current_detection : dict
        The ``detection`` block from telemetry.json:
        ``{"ship_count": 14, "confidence_mean": 0.83,
           "vessel_breakdown": {"tankers": 8, "bulk_carriers": 3, "container": 3}}``
    history : list[dict]
        Prior observations accumulated in ``st.session_state``:
        ``[{"timestamp": "<iso>", "ship_count": <int>}, ...]``
    port : str
        Port identifier from the telemetry ``scene`` block.
    """
    detect = current_detection or {}
    ship_count: Optional[int] = detect.get("ship_count")
    vb: dict = detect.get("vessel_breakdown") or {}

    # Dominant vessel type
    dominant_type = max(vb, key=lambda k: vb.get(k) or 0) if vb else "unknown"

    # Baseline
    counts = [h["ship_count"] for h in history if h.get("ship_count") is not None]
    baseline: Optional[float] = sum(counts) / len(counts) if len(counts) >= 3 else None
    delta: Optional[float] = (
        (ship_count - baseline) / baseline
        if baseline and ship_count is not None else None
    )
    direction = _direction(delta)

    type_key = dominant_type if dominant_type in _RECO else "unknown"
    insight_category, recommendation = _RECO[type_key][direction]

    label    = _trend_label(dominant_type, delta, ship_count, baseline, direction, port)
    insights = _build_insights(dominant_type, direction, delta, ship_count, port)

    # Ship series
    all_pts = list(history)
    if ship_count is not None:
        all_pts.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ship_count": ship_count,
        })
    if all_pts:
        ship_df = pd.DataFrame(all_pts)[["timestamp", "ship_count"]].dropna()
        ship_df["timestamp"] = pd.to_datetime(ship_df["timestamp"])
        ship_df = ship_df.sort_values("timestamp").set_index("timestamp")
    else:
        ship_df = pd.DataFrame(columns=["ship_count"])

    return TrendReport(
        trend_label=label,
        recommendation=recommendation,
        insight_category=insight_category,
        delta_vs_baseline=delta,
        current_count=ship_count,
        baseline_count=baseline,
        dominant_type=dominant_type,
        ship_series=ship_df,
        xom_series=_fetch_xom(),
        insights=insights,
    )
