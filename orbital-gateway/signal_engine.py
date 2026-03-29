"""
Signal Engine
-------------
Translates spectral statistics from Sentinel-2 into a directional trading signal.

Rules (v1 — vegetation stress model):
  BUY  if NDVI_mean > 0.65 and NDWI_mean > -0.1   (healthy / well-watered crop)
  SELL if NDVI_mean < 0.35 or  NDWI_mean < -0.2   (stressed / drought risk)
  HOLD otherwise

Confidence is a normalised score [0, 1] derived from the NDVI margin above/below
the threshold and inversely weighted by cloud cover and NDVI standard deviation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .sentinel import SpectralStats, SceneMetadata

Direction = Literal["BUY", "SELL", "HOLD"]

_NDVI_BUY_THRESH = 0.65
_NDVI_SELL_THRESH = 0.35
_NDWI_BUY_THRESH = -0.10
_NDWI_SELL_THRESH = -0.20


@dataclass
class Signal:
    ticker: str
    direction: Direction
    strength: float  # [0.0, 1.0]
    anomaly_detected: bool
    anomaly_type: str | None
    affected_area_km2: float | None


def derive_signal(
    ticker: str,
    spectral: SpectralStats,
    scene: SceneMetadata,
) -> Signal:
    """Compute a trading signal from spectral statistics."""
    ndvi = spectral.ndvi_mean
    ndwi = spectral.ndwi_mean
    cloud = scene.cloud_cover_pct / 100.0  # normalise to [0, 1]

    # ── Anomaly detection ────────────────────────────────────────────────────
    anomaly_detected = False
    anomaly_type: str | None = None
    affected_area_km2: float | None = None

    if ndvi < 0.25 and ndwi < -0.25:
        anomaly_detected = True
        anomaly_type = "severe_drought"
        affected_area_km2 = round(((0.35 - ndvi) / 0.35) * 500, 1)
    elif ndwi > 0.25:
        anomaly_detected = True
        anomaly_type = "flooding"
        affected_area_km2 = round(ndwi * 200, 1)
    elif spectral.ndvi_std > 0.15:
        anomaly_detected = True
        anomaly_type = "heterogeneous_stress"
        affected_area_km2 = round(spectral.ndvi_std * 300, 1)

    # ── Direction ────────────────────────────────────────────────────────────
    if ndvi > _NDVI_BUY_THRESH and ndwi > _NDWI_BUY_THRESH:
        direction: Direction = "BUY"
        raw_margin = (ndvi - _NDVI_BUY_THRESH) / (1.0 - _NDVI_BUY_THRESH)
    elif ndvi < _NDVI_SELL_THRESH or ndwi < _NDWI_SELL_THRESH:
        direction = "SELL"
        raw_margin = (_NDVI_SELL_THRESH - ndvi) / _NDVI_SELL_THRESH if ndvi < _NDVI_SELL_THRESH else 0.5
    else:
        direction = "HOLD"
        raw_margin = 0.2

    # Reduce confidence for high cloud cover and high spatial variability
    quality_penalty = cloud * 0.4 + min(spectral.ndvi_std / 0.2, 1.0) * 0.2
    strength = round(max(0.0, min(1.0, raw_margin - quality_penalty)), 4)

    return Signal(
        ticker=ticker,
        direction=direction,
        strength=strength,
        anomaly_detected=anomaly_detected,
        anomaly_type=anomaly_type,
        affected_area_km2=affected_area_km2,
    )
