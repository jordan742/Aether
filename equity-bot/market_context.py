"""
Market Context — VIX Volatility Gate
--------------------------------------
Fetches the CBOE Volatility Index (^VIX) and applies a regime-aware
position-size multiplier to Midas's execution.

The Executioner must trust Orion's physical signal — but never ignore
the market's current fear level.  A correct thesis expressed in a
50-VIX environment can still lose money to gap moves and wide spreads.

VIX Regime Table
    VIX < 15    CALM        multiplier = 1.00   (full size)
    15 ≤ VIX < 20  NORMAL  multiplier = 1.00
    20 ≤ VIX < 25  ELEVATED multiplier = 0.75  (−25%)
    25 ≤ VIX < 30  STRESSED multiplier = 0.50  (−50%)
    30 ≤ VIX < 40  FEARFUL  multiplier = 0.25  (−75%)
    VIX ≥ 40    PANIC       multiplier = 0.00   (BLOCK — no execution)

Conviction Override
    EXTREME conviction reduces the VIX penalty by one tier
    (e.g. STRESSED → ELEVATED multiplier) because a very high-confidence
    physical signal justifies extra risk.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

VixRegime = Literal["CALM", "NORMAL", "ELEVATED", "STRESSED", "FEARFUL", "PANIC"]

# Cache VIX for this many seconds to avoid hammering the data source
_VIX_CACHE_TTL = int(os.getenv("VIX_CACHE_TTL", "300"))   # 5 minutes

_VIX_REGIMES: list[tuple[float, VixRegime, float]] = [
    # (upper_bound, regime_name, multiplier)
    (15.0,  "CALM",     1.00),
    (20.0,  "NORMAL",   1.00),
    (25.0,  "ELEVATED", 0.75),
    (30.0,  "STRESSED", 0.50),
    (40.0,  "FEARFUL",  0.25),
    (999.0, "PANIC",    0.00),
]

# One-tier upgrade when conviction is EXTREME
_EXTREME_TIER_BOOST = 1


@dataclass
class VixSnapshot:
    value: float
    regime: VixRegime
    base_multiplier: float
    fetched_at: float        # epoch seconds


class MarketContext:
    """
    Async VIX oracle with in-memory caching.

    Usage:
        ctx = MarketContext()
        snapshot = await ctx.get_vix()
        multiplier = ctx.position_multiplier(snapshot, conviction="HIGH")
    """

    def __init__(self) -> None:
        self._cache: VixSnapshot | None = None

    # ── Public API ─────────────────────────────────────────────────────────────

    async def get_vix(self) -> VixSnapshot:
        """Return a (possibly cached) VIX snapshot."""
        now = time.monotonic()
        if self._cache and (now - self._cache.fetched_at) < _VIX_CACHE_TTL:
            logger.debug("VIX cache hit — %.2f (%s)", self._cache.value, self._cache.regime)
            return self._cache

        snapshot = await self._fetch()
        self._cache = snapshot
        return snapshot

    def position_multiplier(self, snapshot: VixSnapshot, conviction: str) -> float:
        """
        Return the VIX-adjusted position-size multiplier [0.0, 1.0].

        EXTREME conviction earns a one-tier bonus (STRESSED → ELEVATED).
        """
        multiplier = snapshot.base_multiplier

        if conviction == "EXTREME" and multiplier < 1.0:
            # Boost by one tier
            regime_idx = next(
                (i for i, (_, r, _) in enumerate(_VIX_REGIMES) if r == snapshot.regime),
                len(_VIX_REGIMES) - 1,
            )
            boosted_idx = max(0, regime_idx - _EXTREME_TIER_BOOST)
            multiplier = _VIX_REGIMES[boosted_idx][2]
            logger.info(
                "EXTREME conviction VIX boost: %s → %s (×%.2f → ×%.2f)",
                snapshot.regime,
                _VIX_REGIMES[boosted_idx][1],
                snapshot.base_multiplier,
                multiplier,
            )

        return multiplier

    # ── Fetch ──────────────────────────────────────────────────────────────────

    async def _fetch(self) -> VixSnapshot:
        """Try yfinance; fall back to a neutral (VIX=18) estimate on failure."""
        loop = asyncio.get_event_loop()
        try:
            vix_value = await loop.run_in_executor(None, self._blocking_fetch)
        except Exception as exc:
            logger.warning(
                "VIX fetch failed (%s) — defaulting to VIX=18 (NORMAL).", exc
            )
            vix_value = 18.0

        regime, multiplier = self._classify(vix_value)
        snapshot = VixSnapshot(
            value=round(vix_value, 2),
            regime=regime,
            base_multiplier=multiplier,
            fetched_at=time.monotonic(),
        )
        logger.info("VIX=%.2f regime=%s multiplier=×%.2f", vix_value, regime, multiplier)
        return snapshot

    @staticmethod
    def _blocking_fetch() -> float:
        import yfinance as yf
        ticker = yf.Ticker("^VIX")
        hist   = ticker.history(period="1d", interval="1m")
        if hist.empty:
            raise ValueError("Empty VIX history from yfinance.")
        return float(hist["Close"].iloc[-1])

    @staticmethod
    def _classify(vix: float) -> tuple[VixRegime, float]:
        for upper, regime, multiplier in _VIX_REGIMES:
            if vix < upper:
                return regime, multiplier
        return "PANIC", 0.0
