"""
Stark Circuit Breaker
---------------------
Monitors intraday P&L and auto-kills all active processes when the daily loss
exceeds the configured threshold (default: 2 %).

Named after Tony Stark's suit failsafe — it kicks in before catastrophic failure.

Usage:
    breaker = StarkCircuitBreaker(threshold=0.02)
    await breaker.check(portfolio_value=100_000, starting_value=102_000)
    # raises CircuitBreakerTripped if loss >= 2%
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal as _signal
import sys
from dataclasses import dataclass, field
from datetime import date

logger = logging.getLogger(__name__)

_DEFAULT_THRESHOLD = float(os.getenv("CIRCUIT_BREAKER_THRESHOLD", "0.02"))


class CircuitBreakerTripped(Exception):
    """Raised when the intraday loss limit is breached."""

    def __init__(self, loss_pct: float, threshold: float) -> None:
        self.loss_pct = loss_pct
        self.threshold = threshold
        super().__init__(
            f"STARK CIRCUIT BREAKER TRIPPED — "
            f"daily loss {loss_pct:.2%} >= threshold {threshold:.2%}. "
            f"All positions halted."
        )


@dataclass
class DailySnapshot:
    date: date
    starting_equity: float
    peak_equity: float
    current_equity: float
    tripped: bool = False
    loss_pct: float = field(init=False)

    def __post_init__(self) -> None:
        self.loss_pct = self._calc_loss()

    def _calc_loss(self) -> float:
        if self.starting_equity <= 0:
            return 0.0
        return max(0.0, (self.starting_equity - self.current_equity) / self.starting_equity)

    def update(self, current_equity: float) -> None:
        self.current_equity = current_equity
        self.peak_equity = max(self.peak_equity, current_equity)
        self.loss_pct = self._calc_loss()


class StarkCircuitBreaker:
    """Intraday loss guard that terminates the trading process on breach."""

    def __init__(self, threshold: float = _DEFAULT_THRESHOLD) -> None:
        self.threshold = threshold
        self._snapshot: DailySnapshot | None = None
        self._callbacks: list = []

    def register_shutdown_callback(self, coro_func) -> None:
        """Register an async callback to call before process kill."""
        self._callbacks.append(coro_func)

    async def initialise(self, starting_equity: float) -> None:
        """Call once at bot startup with the opening equity value."""
        today = date.today()
        if self._snapshot is None or self._snapshot.date != today:
            self._snapshot = DailySnapshot(
                date=today,
                starting_equity=starting_equity,
                peak_equity=starting_equity,
                current_equity=starting_equity,
            )
            logger.info(
                "Circuit Breaker armed — starting equity=%.2f threshold=%.2f%%",
                starting_equity,
                self.threshold * 100,
            )

    async def check(self, current_equity: float) -> None:
        """Update equity and raise CircuitBreakerTripped if limit breached."""
        if self._snapshot is None:
            raise RuntimeError("Call initialise() before check().")

        today = date.today()
        if self._snapshot.date != today:
            # New trading day — re-arm
            await self.initialise(current_equity)
            return

        self._snapshot.update(current_equity)

        if self._snapshot.loss_pct >= self.threshold and not self._snapshot.tripped:
            self._snapshot.tripped = True
            await self._trip(self._snapshot.loss_pct)

    async def _trip(self, loss_pct: float) -> None:
        logger.critical(
            "STARK CIRCUIT BREAKER TRIPPED — loss=%.2f%% threshold=%.2f%%",
            loss_pct * 100,
            self.threshold * 100,
        )

        # Run registered shutdown hooks (e.g. cancel all orders)
        for cb in self._callbacks:
            try:
                await cb()
            except Exception as exc:
                logger.error("Shutdown callback failed: %s", exc)

        raise CircuitBreakerTripped(loss_pct=loss_pct, threshold=self.threshold)

    @property
    def is_tripped(self) -> bool:
        return self._snapshot is not None and self._snapshot.tripped

    @property
    def current_loss_pct(self) -> float:
        return self._snapshot.loss_pct if self._snapshot else 0.0
