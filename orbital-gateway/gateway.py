"""
Orbital Gateway
---------------
Main async loop that:
  1. Fetches the latest Sentinel-2 maritime scene via SentinelFetcher.
  2. Runs quantized YOLOv8 ship-count inference via ShipDetector.
  3. Derives a directional trading signal via signal_engine.derive_signal().
  4. Builds a ≤1 KB JSON telemetry payload matching schema v2.0.0.
  5. Writes it to the Sovereign Bridge (shared/telemetry.json).

Run directly:
    python -m orbital-gateway

Or import OrbitalGateway and call ``await gateway.run()`` inside your own
event loop.
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
from .yolo_detector import ShipDetector
from .signal_engine import derive_signal

_OVERRIDE_FLAG = Path(__file__).parent.parent / "shared" / "OVERRIDE"

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)

_DEFAULT_INTERVAL = int(os.getenv("TELEMETRY_INTERVAL", "60"))
_DEFAULT_PORT     = os.getenv("ORBITAL_PORT", "strait_of_gibraltar")


class OrbitalGateway:
    """Edge AI simulator — polls Sentinel-2 and writes ship-count telemetry."""

    def __init__(
        self,
        port: str = _DEFAULT_PORT,
        interval: int = _DEFAULT_INTERVAL,
        bridge: TelemetryBridge | None = None,
    ) -> None:
        self.interval = interval
        self.bridge   = bridge or TelemetryBridge()
        self._fetcher = SentinelFetcher(port=port)           # type: ignore[arg-type]
        self._detector = ShipDetector(port=port)
        self._running  = False

    async def run(self) -> None:
        """Start the continuous telemetry update loop."""
        self._running = True
        logger.info("Orbital Gateway online — port=%s interval=%ds",
                    self._fetcher.port, self.interval)

        while self._running:
            if _OVERRIDE_FLAG.exists():
                logger.critical("SYSTEM OVERRIDE detected — Orbital Gateway halting.")
                self._running = False
                break
            try:
                await self._tick()
            except Exception as exc:
                logger.error("Tick error: %s", exc, exc_info=True)
            await asyncio.sleep(self.interval)

    async def _tick(self) -> None:
        """Fetch scene, detect ships, derive signal, write bridge payload."""
        # 1. Fetch latest Sentinel-2 scene for the configured port
        scene = await self._fetcher.fetch_latest()

        # 2. Run YOLOv8 ship detection (simulation when no image on disk)
        detection = self._detector.detect(scene.image_path)

        # 3. Derive trading signal from ship count vs. historical baseline
        signal = derive_signal(scene, detection)

        # 4. Build schema v2.0.0 payload (timestamp injected by bridge.write)
        payload: dict = {
            "schema_version": "2.0.0",
            "source": "orbital-gateway",
            "scene": {
                "tile_id":          scene.tile_id,
                "acquisition_date": scene.acquisition_date,
                "cloud_cover_pct":  scene.cloud_cover_pct,
                "bbox":             scene.bbox,
                "port":             scene.port,
            },
            "detection": {
                "model":           "yolov8n-ship",
                "ship_count":      detection.ship_count,
                "confidence_mean": detection.confidence_mean,
                "large_vessels":   detection.large_vessels,
                "small_vessels":   detection.small_vessels,
                "inference_ms":    detection.inference_ms,
            },
            "signal": {
                "ticker":    signal.ticker,
                "direction": signal.direction,
                "strength":  signal.strength,
                "rationale": signal.rationale,
            },
            "status": "active",
        }

        # 5. Atomic write to shared/telemetry.json (bridge stamps timestamp)
        await self.bridge.write(payload)
        logger.info(
            "Telemetry written — port=%s tile=%s ships=%d signal=%s(%.2f)",
            scene.port,
            scene.tile_id,
            detection.ship_count,
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
