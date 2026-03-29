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
from shared.crypto import cipher as _cipher
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

        # 4. Build schema v3.0.0 payload (timestamp injected by bridge.write)
        vb = detection.vessel_breakdown
        _detection_plain = {
            "model":           "yolov8n-ship",
            "ship_count":      detection.ship_count,
            "confidence_mean": detection.confidence_mean,
            "large_vessels":   detection.large_vessels,
            "small_vessels":   detection.small_vessels,
            "inference_ms":    detection.inference_ms,
            "vessel_breakdown": {
                "tankers":       vb.tankers,
                "bulk_carriers": vb.bulk_carriers,
                "container":     vb.container,
            },
        }

        # Orion encrypts the full detection block via Fernet.
        # Proprietary vessel intelligence never touches disk in plaintext.
        if _cipher.is_active:
            detection_field = {"detection_enc": _cipher.encrypt(_detection_plain)}
            logger.debug("Detection block encrypted (Fernet).")
        else:
            detection_field = {"detection": _detection_plain}

        payload: dict = {
            "schema_version": "3.0.0",
            "classification":  "PROPRIETARY_ALPHA",
            "source":          "orbital-gateway",
            "scene": {
                "tile_id":          scene.tile_id,
                "acquisition_date": scene.acquisition_date,
                "cloud_cover_pct":  scene.cloud_cover_pct,
                "bbox":             scene.bbox,
                "port":             scene.port,
            },
            **detection_field,
            # ── Orbital Truth — physical world observation ─────────────────────
            "orbital_truth": {
                "observation_type": (
                    f"{signal.dominant_type}_density_spike"
                    if signal.direction == "BUY"
                    else f"{signal.dominant_type}_density_drop"
                    if signal.direction == "SELL"
                    else "vessel_count_nominal"
                ),
                "delta_pct":           signal.delta_pct,
                "dominant_vessel_type": signal.dominant_type,
                "thesis":              signal.thesis,
            },
            # ── Alpha Signal — financial instruction to Midas ──────────────────
            "alpha_signal": {
                "ticker":     signal.ticker,
                "sector":     signal.sector,
                "direction":  signal.direction,
                "conviction": signal.conviction,
                "strength":   signal.strength,
                "rationale":  signal.rationale,
            },
            "status": "active",
        }

        # 5. Atomic write to shared/telemetry.json (bridge stamps timestamp)
        await self.bridge.write(payload)
        logger.info(
            "Uplink — port=%s ships=%d Δ=%.1f%% type=%s conviction=%s "
            "signal=%s %s(%.2f) enc=%s",
            scene.port,
            detection.ship_count,
            signal.delta_pct,
            signal.dominant_type,
            signal.conviction,
            signal.direction,
            signal.ticker,
            signal.strength,
            _cipher.is_active,
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
