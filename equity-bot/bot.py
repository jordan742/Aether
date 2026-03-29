"""
Equity Bot
----------
Quantitative execution engine.

Lifecycle:
  1. On startup: read opening equity, arm the Stark Circuit Breaker.
  2. Every cycle: read the Sovereign Bridge for a fresh telemetry signal.
  3. Execute a market order sized by signal strength (max 5 % of portfolio per trade).
  4. Check the circuit breaker — auto-kill if daily loss >= 2 %.

Run directly:
    python -m equity-bot

Or import EquityBot and call await bot.run() inside your own event loop.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from shared.bridge import TelemetryBridge
from .alpaca_client import AlpacaClient
from .circuit_breaker import StarkCircuitBreaker, CircuitBreakerTripped

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)

_POLL_INTERVAL = int(os.getenv("TELEMETRY_INTERVAL", "60"))
_MAX_POSITION_PCT = 0.05   # max 5 % of equity per trade
_MIN_SIGNAL_STRENGTH = 0.3  # ignore weak signals below this threshold


class EquityBot:
    """Reads telemetry signals and executes paper trades via Alpaca."""

    def __init__(
        self,
        bridge: TelemetryBridge | None = None,
        alpaca: AlpacaClient | None = None,
        breaker: StarkCircuitBreaker | None = None,
    ) -> None:
        self.bridge = bridge or TelemetryBridge()
        self.alpaca = alpaca or AlpacaClient()
        self.breaker = breaker or StarkCircuitBreaker()
        self._running = False
        self._last_signal_ts: str | None = None

        # Register emergency shutdown hook with the circuit breaker
        self.breaker.register_shutdown_callback(self._emergency_shutdown)

    async def run(self) -> None:
        """Start the main trading loop."""
        self._running = True
        equity = self.alpaca.get_equity()
        await self.breaker.initialise(starting_equity=equity)
        logger.info("Equity Bot online — equity=$%.2f", equity)

        while self._running:
            try:
                await self._cycle()
            except CircuitBreakerTripped as exc:
                logger.critical(str(exc))
                self._running = False
                break
            except Exception as exc:
                logger.error("Cycle error: %s", exc, exc_info=True)
            await asyncio.sleep(_POLL_INTERVAL)

    async def _cycle(self) -> None:
        """Single trading cycle: read bridge → evaluate → execute → check breaker."""
        telemetry = await self.bridge.read()

        # Skip stale or uninitialised signals
        ts = telemetry.get("timestamp")
        if ts == self._last_signal_ts:
            logger.debug("No new telemetry since last cycle.")
            return

        signal = telemetry.get("signal", {})
        direction = signal.get("direction")
        strength = float(signal.get("strength") or 0.0)
        ticker = signal.get("ticker")

        if not ticker or not direction or direction == "HOLD":
            logger.info("Signal: HOLD — no action.")
        elif strength < _MIN_SIGNAL_STRENGTH:
            logger.info("Signal strength %.2f below threshold — skipping.", strength)
        else:
            equity = self.alpaca.get_equity()
            notional = round(equity * _MAX_POSITION_PCT * strength, 2)
            logger.info(
                "Executing %s %s — notional=$%.2f (strength=%.2f)",
                direction, ticker, notional, strength,
            )
            if direction == "BUY":
                self.alpaca.market_buy(ticker, notional)
            elif direction == "SELL":
                self.alpaca.market_sell(ticker, notional)

        self._last_signal_ts = ts

        # Circuit breaker check after every cycle
        current_equity = self.alpaca.get_equity()
        await self.breaker.check(current_equity)

    async def _emergency_shutdown(self) -> None:
        """Called by the circuit breaker before it trips — cancel and flatten."""
        logger.warning("Emergency shutdown initiated by Stark Circuit Breaker.")
        self._running = False
        try:
            self.alpaca.cancel_all_orders()
            self.alpaca.close_all_positions()
        except Exception as exc:
            logger.error("Emergency shutdown error: %s", exc)

    def stop(self) -> None:
        self._running = False
        logger.info("Equity Bot shutdown requested.")


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    bot = EquityBot()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Equity Bot interrupted by user.")
