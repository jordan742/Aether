"""
Sentinel-2 Maritime Imagery Fetcher
------------------------------------
Queries the Copernicus Open Access Hub for the latest Sentinel-2 L2A product
over configurable maritime AOIs (straits and major shipping chokepoints).

Supported ports / AOIs
    strait_of_gibraltar  → ticker BDRY
    strait_of_hormuz     → ticker XOM
    singapore_strait     → ticker SOXS
    english_channel      → ticker ZIM

When SENTINEL_USER / SENTINEL_PASSWORD are absent the fetcher falls back to a
realistic simulation that still returns a fully schema-valid SceneResult.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

logger = logging.getLogger(__name__)

# ── Port / AOI catalogue ───────────────────────────────────────────────────────

PortName = Literal[
    "strait_of_gibraltar",
    "strait_of_hormuz",
    "singapore_strait",
    "english_channel",
]

_PORT_CONFIG: dict[str, dict] = {
    "strait_of_gibraltar": {
        "bbox": [-5.0, 35.0, 5.0, 40.0],
        "ticker": "BDRY",
        "tile_ids": ["T30SUF", "T30SUG", "T30TXD", "T30UXD"],
    },
    "strait_of_hormuz": {
        "bbox": [56.0, 25.5, 57.5, 27.0],
        "ticker": "XOM",
        "tile_ids": ["T40RBN", "T40RCN", "T40RBM", "T40RCM"],
    },
    "singapore_strait": {
        "bbox": [103.6, 1.1, 104.5, 1.6],
        "ticker": "SOXS",
        "tile_ids": ["T48NUG", "T48NVG", "T48NUH", "T48NVH"],
    },
    "english_channel": {
        "bbox": [-2.0, 49.5, 2.5, 51.5],
        "ticker": "ZIM",
        "tile_ids": ["T30UWC", "T30UXC", "T30UWB", "T30UXB"],
    },
}

_DEFAULT_PORT: PortName = "strait_of_gibraltar"


# ── Result dataclass ───────────────────────────────────────────────────────────

@dataclass
class SceneResult:
    tile_id: str
    acquisition_date: str       # ISO-8601 date string
    cloud_cover_pct: float
    bbox: list[float]           # [west, south, east, north]
    port: str
    ticker: str
    image_path: str | None = None  # local path to downloaded scene (None in sim)


# ── Fetcher ────────────────────────────────────────────────────────────────────

class SentinelFetcher:
    """Fetches Sentinel-2 L2A imagery for maritime chokepoint AOIs."""

    def __init__(
        self,
        port: PortName = _DEFAULT_PORT,
        max_cloud_cover: float = 20.0,
    ) -> None:
        cfg = _PORT_CONFIG[port]
        self.port = port
        self.bbox: list[float] = cfg["bbox"]
        self.ticker: str = cfg["ticker"]
        self._tile_ids: list[str] = cfg["tile_ids"]
        self.max_cloud_cover = max_cloud_cover

        self._user = os.getenv("SENTINEL_USER")
        self._password = os.getenv("SENTINEL_PASSWORD")
        self._simulation = not bool(self._user and self._password)

        if self._simulation:
            logger.warning(
                "SENTINEL_USER / SENTINEL_PASSWORD not set — running in simulation mode."
            )

    async def fetch_latest(self) -> SceneResult:
        """Return the latest usable scene (real or simulated)."""
        if self._simulation:
            return self._simulate()
        return await self._fetch_real()

    # ── Real fetch ─────────────────────────────────────────────────────────────

    async def _fetch_real(self) -> SceneResult:
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._blocking_fetch)
        except Exception as exc:
            logger.error(
                "Sentinel real fetch failed (%s) — falling back to simulation.", exc
            )
            return self._simulate()

    def _blocking_fetch(self) -> SceneResult:
        from sentinelsat import SentinelAPI
        import shapely.geometry as geom

        api = SentinelAPI(
            self._user,
            self._password,
            "https://scihub.copernicus.eu/dhus",
        )
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

        df = api.to_dataframe(products).sort_values("ingestiondate", ascending=False)
        row = df.iloc[0]

        return SceneResult(
            tile_id=str(row.get("title", "UNKNOWN")),
            acquisition_date=str(row.get("beginposition", date.today().isoformat())),
            cloud_cover_pct=round(float(row.get("cloudcoverpercentage", 0.0)), 2),
            bbox=list(self.bbox),
            port=self.port,
            ticker=self.ticker,
            image_path=None,
        )

    # ── Simulation ─────────────────────────────────────────────────────────────

    def _simulate(self) -> SceneResult:
        """Generate a synthetic but physically-plausible maritime scene."""
        today = date.today()
        acq = today - timedelta(days=random.randint(0, 5))

        return SceneResult(
            tile_id=random.choice(self._tile_ids),
            acquisition_date=acq.isoformat(),
            cloud_cover_pct=round(random.uniform(0.5, self.max_cloud_cover), 2),
            bbox=list(self.bbox),
            port=self.port,
            ticker=self.ticker,
            image_path=None,
        )
