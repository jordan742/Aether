"""
Signal Watcher
--------------
Continuously polls the Sovereign Bridge (shared/telemetry.json) and executes
paper trades on Alpaca whenever a fresh, actionable signal is detected.

The telemetry schema this module consumes (written by orbital-gateway):

    {
        "schema_version": "2.0.0",
        "source": "orbital-gateway",
        "timestamp": "2026-03-29T12:00:00+00:00",
        "scene": { "port": "strait_of_gibraltar", ... },
        "detection": { "ship_count": 47, ... },
        "signal": {
            "ticker": "BDRY",
            "direction": "BUY",
            "strength": 0.74,
            "rationale": "ship_count_above_30d_avg"
        },
        "status": "active"
    }
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from shared.bridge import TelemetryBridge
from .alpaca_client import AlpacaClient
from .circuit_breaker import StarkCircuitBreaker, CircuitBreakerTripped

logger = logging.getLogger(__name__)

# ── Module-level constants ─────────────────────────────────────────────────────
MIN_STRENGTH: float = 0.3   # signals below this are ignored
MAX_PCT: float = 0.05       # max fraction of equity risked per trade
DEFAULT_POLL: int = 5       # default polling interval in seconds

_ROOT          = Path(__file__).parent.parent
_OVERRIDE_FLAG = _ROOT / "shared" / "OVERRIDE"
_TRADES_LOG    = _ROOT / "shared" / "trades.jsonl"


class SignalWatcher:
    """
    Reads the Sovereign Bridge on a fixed cadence and converts signals into
    Alpaca paper trades, subject to the Stark Circuit Breaker.
    """

    def __init__(
        self,
        bridge: TelemetryBridge,
        alpaca: AlpacaClient,
        breaker: StarkCircuitBreaker,
        poll_interval: int = DEFAULT_POLL,
        _stop_flag: list[bool] | None = None,
    ) -> None:
        self.bridge = bridge
        self.alpaca = alpaca
        self.breaker = breaker
        self.poll_interval = poll_interval
        self._last_ts: str | None = None
        # Optional shared stop-flag so EquityBot.stop() can halt the loop
        self._stop_flag = _stop_flag if _stop_flag is not None else [False]

    # ── Public API ─────────────────────────────────────────────────────────────

    async def watch(self) -> None:
        """
        Main polling loop.

        Runs until:
        - CircuitBreakerTripped is raised (re-raised to caller), or
        - The shared stop flag is set (clean exit).
        """
        logger.info(
            "SignalWatcher started — poll_interval=%ds MIN_STRENGTH=%.2f MAX_PCT=%.0f%%",
            self.poll_interval,
            MIN_STRENGTH,
            MAX_PCT * 100,
        )

        while not self._stop_flag[0]:
            if _OVERRIDE_FLAG.exists():
                logger.critical("SYSTEM OVERRIDE detected — SignalWatcher halting.")
                self._stop_flag[0] = True
                break
            try:
                telemetry = await self.bridge.read()

                if await self._is_new_signal(telemetry):
                    await self._process(telemetry)

            except CircuitBreakerTripped:
                raise  # propagate to EquityBot.run()
            except Exception as exc:
                logger.error("SignalWatcher cycle error: %s", exc, exc_info=True)

            await asyncio.sleep(self.poll_interval)

    # ── Internal helpers ───────────────────────────────────────────────────────

    async def _is_new_signal(self, telemetry: dict) -> bool:
        """Return True when *telemetry* carries a timestamp we haven't seen."""
        ts = telemetry.get("timestamp")
        if ts is None or ts == self._last_ts:
            return False
        return True

    async def _process(self, telemetry: dict) -> None:
        """Evaluate the telemetry signal and, if actionable, execute a trade."""
        # ── Extract fields per handshake contract ──────────────────────────────
        direction: str = telemetry["signal"]["direction"]
        strength: float = float(telemetry["signal"]["strength"])
        ticker: str = telemetry["signal"]["ticker"]
        ship_count: int = int(telemetry["detection"]["ship_count"])
        port: str = telemetry.get("scene", {}).get("port", "unknown")
        ts: str = telemetry["timestamp"]

        logger.info(
            "Signal — port=%s ship_count=%d direction=%s strength=%.3f ticker=%s",
            port,
            ship_count,
            direction,
            strength,
            ticker,
        )

        # Mark timestamp as processed regardless of whether we trade
        self._last_ts = ts

        # ── Guard checks ───────────────────────────────────────────────────────
        if direction == "HOLD":
            logger.info("Direction=HOLD — no action taken.")
            return

        if strength < MIN_STRENGTH:
            logger.info(
                "Signal strength %.3f below MIN_STRENGTH %.2f — skipping.",
                strength,
                MIN_STRENGTH,
            )
            return

        # ── Size and execute order ─────────────────────────────────────────────
        equity = await self.alpaca.get_equity()
        notional = round(equity * MAX_PCT * strength, 2)

        logger.info(
            "Executing %s %s — equity=$%.2f notional=$%.2f (strength=%.3f)",
            direction,
            ticker,
            equity,
            notional,
            strength,
        )

        if direction == "BUY":
            await self.alpaca.market_buy(ticker, notional)
        elif direction == "SELL":
            await self.alpaca.market_sell(ticker, notional)
        else:
            logger.warning("Unknown direction '%s' — no order placed.", direction)
            return

        # ── Append to trade log (consumed by dashboard P&L ticker) ────────────
        self._log_trade(ticker, direction, notional)

        # ── Post-trade circuit breaker check ──────────────────────────────────
        try:
            await self.breaker.check(await self.alpaca.get_equity())
        except CircuitBreakerTripped as exc:
            logger.critical(
                "Circuit breaker tripped after trade — loss=%.2f%% threshold=%.2f%%. "
                "Initiating emergency shutdown.",
                exc.loss_pct * 100,
                exc.threshold * 100,
            )
            await self.alpaca.cancel_all_orders()
            await self.alpaca.close_all_positions()
            raise

    # ── Trade logger ───────────────────────────────────────────────────────────

    @staticmethod
    def _log_trade(ticker: str, direction: str, notional: float) -> None:
        """Append a trade record to shared/trades.jsonl for dashboard consumption."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ticker": ticker,
            "direction": direction,
            "notional": notional,
            "pnl": None,   # filled in by a future reconciliation pass
        }
        try:
            with _TRADES_LOG.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
        except OSError as exc:
            logger.warning("Could not write trade log: %s", exc)
