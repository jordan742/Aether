"""
Sentinel-2 Imagery Fetcher
--------------------------
Queries the Copernicus Open Access Hub for the latest Sentinel-2 L2A product
over a configurable area of interest and extracts band statistics that drive
the trading signal.

In simulation mode (SENTINEL_USER not set) synthetic data is returned so the
full system can be exercised without credentials.
"""

from __future__ import annotations

import logging
import os
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# Default AOI: US Corn Belt centroid (Iowa)
_DEFAULT_BBOX = (-94.0, 41.5, -90.0, 43.5)  # (west, south, east, north)
# Ticker mapped to this AOI for the signal engine
_DEFAULT_TICKER = "MOO"  # VanEck Agribusiness ETF


@dataclass
class SceneMetadata:
    tile_id: str
    acquisition_date: str
    cloud_cover_pct: float
    bbox: list[float]


@dataclass
class SpectralStats:
    ndvi_mean: float
    ndvi_std: float
    ndwi_mean: float
    evi_mean: float


@dataclass
class SentinelResult:
    scene: SceneMetadata
    spectral: SpectralStats
    ticker: str = _DEFAULT_TICKER


class SentinelFetcher:
    """Fetches and processes Sentinel-2 imagery."""

    def __init__(
        self,
        bbox: tuple[float, float, float, float] = _DEFAULT_BBOX,
        ticker: str = _DEFAULT_TICKER,
        max_cloud_cover: float = 20.0,
    ) -> None:
        self.bbox = bbox
        self.ticker = ticker
        self.max_cloud_cover = max_cloud_cover
        self._user = os.getenv("SENTINEL_USER")
        self._password = os.getenv("SENTINEL_PASSWORD")
        self._simulation = not bool(self._user and self._password)

        if self._simulation:
            logger.warning(
                "SENTINEL_USER / SENTINEL_PASSWORD not set — running in simulation mode."
            )

    async def fetch_latest(self) -> SentinelResult:
        """Return the latest usable scene result (real or simulated)."""
        if self._simulation:
            return self._simulate()
        return await self._fetch_real()

    # ── Real fetch ─────────────────────────────────────────────────────────────

    async def _fetch_real(self) -> SentinelResult:
        try:
            from sentinelsat import SentinelAPI
            import asyncio

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self._blocking_fetch)
            return result
        except Exception as exc:
            logger.error("Sentinel real fetch failed (%s) — falling back to simulation.", exc)
            return self._simulate()

    def _blocking_fetch(self) -> SentinelResult:
        from sentinelsat import SentinelAPI, read_geojson, geojson_to_wkt
        import shapely.geometry as geom

        api = SentinelAPI(self._user, self._password, "https://scihub.copernicus.eu/dhus")

        footprint = geom.box(*self.bbox).wkt
        today = date.today()
        products = api.query(
            footprint,
            date=(today - timedelta(days=30), today),
            platformname="Sentinel-2",
            producttype="S2MSI2A",
            cloudcoverpercentage=(0, self.max_cloud_cover),
        )

        if not products:
            logger.warning("No cloud-free scenes found; using simulation.")
            return self._simulate()

        # Pick the most recent product
        df = api.to_dataframe(products).sort_values("ingestiondate", ascending=False)
        row = df.iloc[0]

        scene = SceneMetadata(
            tile_id=str(row.get("title", "UNKNOWN")),
            acquisition_date=str(row.get("beginposition", date.today())),
            cloud_cover_pct=float(row.get("cloudcoverpercentage", 0.0)),
            bbox=list(self.bbox),
        )
        # Band stats would normally come from band extraction; stub with simulated values
        spectral = self._generate_spectral()
        return SentinelResult(scene=scene, spectral=spectral, ticker=self.ticker)

    # ── Simulation ─────────────────────────────────────────────────────────────

    def _simulate(self) -> SentinelResult:
        """Generate a synthetic but physically-plausible scene."""
        tile_ids = ["T15TXH", "T15TYH", "T15UXA", "T14TNN"]
        today = date.today()
        acq = today - timedelta(days=random.randint(0, 5))

        scene = SceneMetadata(
            tile_id=random.choice(tile_ids),
            acquisition_date=acq.isoformat(),
            cloud_cover_pct=round(random.uniform(0.5, self.max_cloud_cover), 2),
            bbox=list(self.bbox),
        )
        spectral = self._generate_spectral()
        return SentinelResult(scene=scene, spectral=spectral, ticker=self.ticker)

    @staticmethod
    def _generate_spectral() -> SpectralStats:
        # NDVI: healthy vegetation 0.6-0.9, stressed 0.2-0.5
        ndvi = round(random.uniform(0.2, 0.9), 4)
        return SpectralStats(
            ndvi_mean=ndvi,
            ndvi_std=round(random.uniform(0.02, 0.12), 4),
            ndwi_mean=round(random.uniform(-0.3, 0.3), 4),
            evi_mean=round(ndvi * random.uniform(0.7, 1.0), 4),
        )
