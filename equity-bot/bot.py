"""
Equity Bot
----------
Quantitative execution engine for Aether Fund One.

Lifecycle:
  1. On startup: read opening equity, arm the Stark Circuit Breaker.
  2. Create a SignalWatcher and hand it control.
  3. SignalWatcher polls the Sovereign Bridge and fires trades.
  4. Circuit breaker auto-kills on daily loss >= threshold (default 2 %).

Run directly:
    python -m equity-bot

Or import EquityBot and call await bot.run() inside your own event loop.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from shared.bridge import TelemetryBridge
from .alpaca_client import AlpacaClient
from .circuit_breaker import StarkCircuitBreaker, CircuitBreakerTripped
from .signal_watcher import SignalWatcher

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)


class EquityBot:
    """Reads telemetry signals via SignalWatcher and executes paper trades."""

    def __init__(
        self,
        bridge: TelemetryBridge | None = None,
        alpaca: AlpacaClient | None = None,
        breaker: StarkCircuitBreaker | None = None,
    ) -> None:
        self.bridge = bridge or TelemetryBridge()
        self.alpaca = alpaca or AlpacaClient()
        self.breaker = breaker or StarkCircuitBreaker()
        # Shared mutable stop flag — a single-element list so SignalWatcher
        # can observe mutations made by stop().
        self._stop_flag: list[bool] = [False]

    async def run(self) -> None:
        """Start the trading loop: arm the breaker, then delegate to SignalWatcher."""
        equity = await self.alpaca.get_equity()
        await self.breaker.initialise(starting_equity=equity)
        logger.info("Equity Bot online — opening equity=$%.2f", equity)

        watcher = SignalWatcher(
            bridge=self.bridge,
            alpaca=self.alpaca,
            breaker=self.breaker,
            _stop_flag=self._stop_flag,
        )

        try:
            await watcher.watch()
        except CircuitBreakerTripped as exc:
            logger.critical(
                "EquityBot halted by circuit breaker — loss=%.2f%% threshold=%.2f%%",
                exc.loss_pct * 100,
                exc.threshold * 100,
            )
            # Clean exit — positions already closed inside SignalWatcher._process
        finally:
            logger.info("Equity Bot stopped.")

    def stop(self) -> None:
        """Signal the SignalWatcher loop to exit cleanly after the current poll."""
        self._stop_flag[0] = True
        logger.info("Equity Bot shutdown requested.")


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    bot = EquityBot()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Equity Bot interrupted by user.")
