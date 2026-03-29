"""
Signal Engine — Orbital Intelligence Model v3.0
-------------------------------------------------
Translates physical vessel observations from YOLOv8 into Proprietary Truth:
a conviction-graded, sector-mapped alpha signal.

The Thesis
    Terrestrial traders wait for news. We observe physical supply chains
    directly. A 15% tanker surge at Hormuz is a crude supply disruption
    signal before any Bloomberg headline. A bulk carrier exodus from Singapore
    signals iron ore demand collapse before futures markets react.

Conviction Framework
    EXTREME  strength > 0.80   → HIGH-conviction alpha, max position
    HIGH     0.60 – 0.80       → Strong signal, full standard position
    MEDIUM   0.35 – 0.60       → Moderate signal, reduced position
    LOW      < 0.35            → Below threshold, Midas will skip

Vessel-to-Sector Mapping
    Dominant vessel type + port → sector → ticker
    ─────────────────────────────────────────────
    tankers      + hormuz    → energy      → XOM   (ExxonMobil)
    tankers      + gibraltar → energy      → USO   (US Oil Fund ETF)
    tankers      + channel   → energy      → XOM
    tankers      + singapore → energy      → USO
    bulk_carriers+ singapore → dry_bulk    → BDRY  (Breakwave Dry Bulk)
    bulk_carriers+ channel   → dry_bulk    → BDRY
    bulk_carriers+ hormuz    → materials   → XME   (SPDR Metals & Mining)
    bulk_carriers+ gibraltar → materials   → XME
    container    + gibraltar → shipping    → ZIM   (ZIM Integrated Shipping)
    container    + channel   → shipping    → ZIM
    container    + singapore → tech_supply → SOXS  (Direxion Semi Bear — congestion signal)
    container    + hormuz    → shipping    → ZIM
    mixed        (fallback)  → uses port default ticker
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from .sentinel import SceneResult
from .yolo_detector import DetectionResult, VesselBreakdown

Direction   = Literal["BUY", "SELL", "HOLD"]
Conviction  = Literal["EXTREME", "HIGH", "MEDIUM", "LOW"]

# ── Historical 30-day mean ship counts per port ────────────────────────────────
_HISTORICAL_MEAN: dict[str, float] = {
    "strait_of_gibraltar": 45.0,
    "strait_of_hormuz":    38.0,
    "singapore_strait":    62.0,
    "english_channel":     55.0,
}

_BUY_THRESHOLD  = 1.15   # >15% above baseline → BUY
_SELL_THRESHOLD = 0.85   # >15% below baseline → SELL

# ── Conviction thresholds ──────────────────────────────────────────────────────
_EXTREME_THRESH = 0.80
_HIGH_THRESH    = 0.60
_MEDIUM_THRESH  = 0.35

# ── Vessel-type dominance threshold (pct of total fleet) ──────────────────────
_DOMINANT_TYPE_PCT = 0.40   # >40% of vessels = dominant type

# ── Physical-to-financial sector/ticker mapping ────────────────────────────────
# Key: (dominant_vessel_type, port)  Value: (sector, ticker)
_PHYSICAL_TO_FINANCIAL: dict[tuple[str, str], tuple[str, str]] = {
    # Tanker signals → energy sector
    ("tankers", "strait_of_hormuz"):    ("energy",      "XOM"),
    ("tankers", "strait_of_gibraltar"): ("energy",      "USO"),
    ("tankers", "english_channel"):     ("energy",      "XOM"),
    ("tankers", "singapore_strait"):    ("energy",      "USO"),
    # Bulk carrier signals → materials / dry bulk
    ("bulk_carriers", "singapore_strait"):    ("dry_bulk",   "BDRY"),
    ("bulk_carriers", "english_channel"):     ("dry_bulk",   "BDRY"),
    ("bulk_carriers", "strait_of_hormuz"):    ("materials",  "XME"),
    ("bulk_carriers", "strait_of_gibraltar"): ("materials",  "XME"),
    # Container signals → shipping / tech supply chain
    ("container", "strait_of_gibraltar"): ("shipping",     "ZIM"),
    ("container", "english_channel"):     ("shipping",     "ZIM"),
    ("container", "singapore_strait"):    ("tech_supply",  "SOXS"),
    ("container", "strait_of_hormuz"):    ("shipping",     "ZIM"),
}

# Port default tickers (fallback when vessel mix is not dominant)
_PORT_DEFAULT_TICKER: dict[str, tuple[str, str]] = {
    "strait_of_hormuz":    ("energy",   "XOM"),
    "strait_of_gibraltar": ("shipping", "ZIM"),
    "singapore_strait":    ("dry_bulk", "BDRY"),
    "english_channel":     ("shipping", "ZIM"),
}


# ── Output dataclass ───────────────────────────────────────────────────────────

@dataclass
class AlphaSignal:
    ticker:           str
    sector:           str
    direction:        Direction
    conviction:       Conviction
    strength:         float       # [0.0, 1.0] normalised delta magnitude
    rationale:        str         # machine-readable tag
    delta_pct:        float       # % change vs historical mean (signed)
    dominant_type:    str         # "tankers" | "bulk_carriers" | "container" | "mixed"
    thesis:           str         # human-readable physical observation


# ── Helpers ────────────────────────────────────────────────────────────────────

def _dominant_vessel_type(vb: VesselBreakdown, total: int) -> str:
    """Return the dominant vessel category or 'mixed' if none exceeds threshold."""
    if total == 0:
        return "mixed"
    breakdown = {
        "tankers":       vb.tankers,
        "bulk_carriers": vb.bulk_carriers,
        "container":     vb.container,
    }
    dominant, count = max(breakdown.items(), key=lambda x: x[1])
    if count / total >= _DOMINANT_TYPE_PCT:
        return dominant
    return "mixed"


def _conviction(strength: float) -> Conviction:
    if strength >= _EXTREME_THRESH:
        return "EXTREME"
    if strength >= _HIGH_THRESH:
        return "HIGH"
    if strength >= _MEDIUM_THRESH:
        return "MEDIUM"
    return "LOW"


def _build_thesis(
    port: str,
    dominant_type: str,
    delta_pct: float,
    direction: Direction,
    vb: VesselBreakdown,
) -> str:
    """Compose a one-sentence physical-world thesis for the signal."""
    port_name = port.replace("_", " ").title()
    sign      = "surplus" if delta_pct > 0 else "deficit"
    abs_delta = abs(round(delta_pct, 1))

    if dominant_type == "tankers":
        commodity = "crude / LNG"
        implication = (
            "supply disruption risk → energy premium" if direction == "BUY"
            else "demand weakness → energy discount"
        )
        return (
            f"{abs_delta}% tanker {sign} at {port_name} "
            f"signals {commodity} {implication} "
            f"({vb.tankers} tankers observed)"
        )
    if dominant_type == "bulk_carriers":
        commodity = "iron ore / coal / grain"
        implication = (
            "demand surge → materials premium" if direction == "BUY"
            else "inventory glut → materials weakness"
        )
        return (
            f"{abs_delta}% bulk carrier {sign} at {port_name} "
            f"signals {commodity} {implication} "
            f"({vb.bulk_carriers} bulkers observed)"
        )
    if dominant_type == "container":
        implication = (
            "supply chain pressure → shipping rate spike" if direction == "BUY"
            else "slack demand → shipping rate compression"
        )
        return (
            f"{abs_delta}% container {sign} at {port_name} "
            f"signals {implication} "
            f"({vb.container} boxships observed)"
        )
    # mixed
    return (
        f"{abs_delta}% mixed-fleet {sign} at {port_name} "
        f"— no single vessel type dominant; composite signal"
    )


# ── Main entry point ───────────────────────────────────────────────────────────

def derive_signal(scene: SceneResult, detection: DetectionResult) -> AlphaSignal:
    """
    Translate a physical satellite observation into an alpha signal.

    Parameters
    ----------
    scene:
        ``SceneResult`` from ``SentinelFetcher.fetch_latest()``.
    detection:
        ``DetectionResult`` from ``ShipDetector.detect()``.

    Returns
    -------
    AlphaSignal
        Conviction-graded, sector-mapped trading signal with embedded thesis.
    """
    hist_mean = _HISTORICAL_MEAN.get(scene.port, 45.0)
    count     = detection.ship_count
    vb        = detection.vessel_breakdown

    # ── Compute delta ──────────────────────────────────────────────────────────
    delta_pct  = ((count - hist_mean) / hist_mean * 100) if hist_mean > 0 else 0.0
    raw_str    = abs(count - hist_mean) / hist_mean if hist_mean > 0 else 0.0
    strength   = round(min(1.0, max(0.0, raw_str)), 4)

    # ── Direction ──────────────────────────────────────────────────────────────
    if count > hist_mean * _BUY_THRESHOLD:
        direction: Direction = "BUY"
        rationale_tag = f"vessel_count_{abs(round(delta_pct,1))}pct_above_30d_avg"
    elif count < hist_mean * _SELL_THRESHOLD:
        direction = "SELL"
        rationale_tag = f"vessel_count_{abs(round(delta_pct,1))}pct_below_30d_avg"
    else:
        direction = "HOLD"
        rationale_tag = "vessel_count_within_30d_avg_band"

    # ── Conviction ─────────────────────────────────────────────────────────────
    conviction = _conviction(strength)

    # ── Vessel type dominance + sector/ticker mapping ──────────────────────────
    dominant_type = _dominant_vessel_type(vb, count)
    sector, ticker = _PHYSICAL_TO_FINANCIAL.get(
        (dominant_type, scene.port),
        _PORT_DEFAULT_TICKER.get(scene.port, ("shipping", scene.ticker)),
    )

    # ── Thesis ─────────────────────────────────────────────────────────────────
    thesis = _build_thesis(scene.port, dominant_type, delta_pct, direction, vb)

    return AlphaSignal(
        ticker=ticker,
        sector=sector,
        direction=direction,
        conviction=conviction,
        strength=strength,
        rationale=rationale_tag,
        delta_pct=round(delta_pct, 2),
        dominant_type=dominant_type,
        thesis=thesis,
    )
