"""
Signal Engine — Ship-Count Model
----------------------------------
Translates ship-count statistics from YOLOv8 detection into a directional
trading signal for the port's associated ticker.

Rules
    BUY  if ship_count > historical_mean * 1.15   (port congestion → rate spike)
    SELL if ship_count < historical_mean * 0.85   (slack demand / low traffic)
    HOLD otherwise

Signal strength = abs(ship_count - historical_mean) / historical_mean, clamped
to [0.0, 1.0].
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .sentinel import SceneResult
from .yolo_detector import DetectionResult

Direction = Literal["BUY", "SELL", "HOLD"]

# Historical 30-day mean ship counts per port (vessels observed per scene)
_HISTORICAL_MEAN: dict[str, float] = {
    "strait_of_gibraltar": 45.0,
    "strait_of_hormuz":    38.0,
    "singapore_strait":    62.0,
    "english_channel":     55.0,
}

_BUY_THRESHOLD  = 1.15   # 15 % above baseline
_SELL_THRESHOLD = 0.85   # 15 % below baseline


@dataclass
class Signal:
    ticker: str
    direction: Direction
    strength: float      # [0.0, 1.0]
    rationale: str


def derive_signal(scene: SceneResult, detection: DetectionResult) -> Signal:
    """Compute a ship-count-based trading signal.

    Parameters
    ----------
    scene:
        The ``SceneResult`` produced by ``SentinelFetcher.fetch_latest()``.
    detection:
        The ``DetectionResult`` produced by ``ShipDetector.detect()``.

    Returns
    -------
    Signal
    """
    hist_mean = _HISTORICAL_MEAN.get(scene.port, 45.0)
    count = detection.ship_count

    raw_strength = abs(count - hist_mean) / hist_mean if hist_mean > 0 else 0.0
    strength = round(min(1.0, max(0.0, raw_strength)), 4)

    if count > hist_mean * _BUY_THRESHOLD:
        direction: Direction = "BUY"
        rationale = "ship_count_above_30d_avg"
    elif count < hist_mean * _SELL_THRESHOLD:
        direction = "SELL"
        rationale = "ship_count_below_30d_avg"
    else:
        direction = "HOLD"
        rationale = "ship_count_within_30d_avg"

    return Signal(
        ticker=scene.ticker,
        direction=direction,
        strength=strength,
        rationale=rationale,
    )
