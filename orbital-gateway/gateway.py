"""
Orbital Gateway
---------------
Main async loop that:
  1. Fetches the latest Sentinel-2 scene via SentinelFetcher.
  2. Runs the signal engine to derive a trading direction.
  3. Packs a ≤1 KB JSON telemetry payload.
  4. Writes it to the Sovereign Bridge (shared/telemetry.json).

Run directly:
    python -m orbital-gateway

Or import OrbitalGateway and call await gateway.run() inside your own event loop.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

# Allow running as __main__ without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from shared.bridge import TelemetryBridge
from .sentinel import SentinelFetcher
from .signal_engine import derive_signal

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)

_DEFAULT_INTERVAL = int(os.getenv("TELEMETRY_INTERVAL", "60"))


class OrbitalGateway:
    """Edge AI simulator — polls Sentinel-2 and writes telemetry to the bridge."""

    def __init__(
        self,
        interval: int = _DEFAULT_INTERVAL,
        bridge: TelemetryBridge | None = None,
    ) -> None:
        self.interval = interval
        self.bridge = bridge or TelemetryBridge()
        self._fetcher = SentinelFetcher()
        self._running = False

    async def run(self) -> None:
        """Start the continuous telemetry update loop."""
        self._running = True
        logger.info("Orbital Gateway online — interval=%ds", self.interval)

        while self._running:
            try:
                await self._tick()
            except Exception as exc:
                logger.error("Tick error: %s", exc, exc_info=True)
            await asyncio.sleep(self.interval)

    async def _tick(self) -> None:
        """Fetch imagery, derive signal, write bridge."""
        result = await self._fetcher.fetch_latest()
        signal = derive_signal(result.ticker, result.spectral, result.scene)

        payload: dict = {
            "schema_version": "1.0.0",
            "source": "orbital-gateway",
            "scene": {
                "tile_id": result.scene.tile_id,
                "acquisition_date": result.scene.acquisition_date,
                "cloud_cover_pct": result.scene.cloud_cover_pct,
                "bbox": result.scene.bbox,
            },
            "spectral": {
                "ndvi_mean": result.spectral.ndvi_mean,
                "ndvi_std": result.spectral.ndvi_std,
                "ndwi_mean": result.spectral.ndwi_mean,
                "evi_mean": result.spectral.evi_mean,
            },
            "anomaly": {
                "detected": signal.anomaly_detected,
                "type": signal.anomaly_type,
                "confidence": signal.strength if signal.anomaly_detected else None,
                "affected_area_km2": signal.affected_area_km2,
            },
            "signal": {
                "ticker": signal.ticker,
                "direction": signal.direction,
                "strength": signal.strength,
            },
            "status": "active",
        }

        await self.bridge.write(payload)
        logger.info(
            "Telemetry written — tile=%s NDVI=%.3f signal=%s(%.2f)",
            result.scene.tile_id,
            result.spectral.ndvi_mean,
            signal.direction,
            signal.strength,
        )

    def stop(self) -> None:
        """Signal the run loop to exit after the current tick."""
        self._running = False
        logger.info("Orbital Gateway shutdown requested.")


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    gateway = OrbitalGateway()
    try:
        asyncio.run(gateway.run())
    except KeyboardInterrupt:
        logger.info("Orbital Gateway interrupted by user.")
