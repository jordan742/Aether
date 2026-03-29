"""
Alpaca Client
-------------
Async wrapper around alpaca-py for paper-trading operations used by the
equity bot. All sync alpaca-py calls are dispatched to a thread-pool
executor so they never block the event loop.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

logger = logging.getLogger(__name__)

_PAPER = True  # always paper-trade


class AlpacaClient:
    """Fully async facade over the Alpaca paper trading API."""

    def __init__(
        self,
        api_key: str | None = None,
        secret_key: str | None = None,
    ) -> None:
        api_key = api_key or os.getenv("ALPACA_API_KEY", "")
        secret_key = secret_key or os.getenv("ALPACA_SECRET_KEY", "")

        if not api_key or not secret_key:
            raise EnvironmentError(
                "ALPACA_API_KEY and ALPACA_SECRET_KEY must be set as environment "
                "variables (or in .env). Neither value may be empty."
            )

        self._client = TradingClient(api_key, secret_key, paper=_PAPER)
        self._loop_executor = None  # uses default executor

    # ── Internal helper ────────────────────────────────────────────────────────

    async def _run(self, fn, *args, **kwargs):
        """Run a sync callable in the default thread-pool executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))

    # ── Account ────────────────────────────────────────────────────────────────

    async def get_equity(self) -> float:
        """Return current portfolio equity in USD."""
        account = await self._run(self._client.get_account)
        return float(account.equity)

    async def get_cash(self) -> float:
        """Return current cash balance in USD."""
        account = await self._run(self._client.get_account)
        return float(account.cash)

    # ── Orders ─────────────────────────────────────────────────────────────────

    async def market_buy(self, ticker: str, notional_usd: float) -> str:
        """Submit a notional market buy. Returns the order ID."""
        req = MarketOrderRequest(
            symbol=ticker,
            notional=round(notional_usd, 2),
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )
        order = await self._run(self._client.submit_order, req)
        logger.info("BUY submitted — %s $%.2f order_id=%s", ticker, notional_usd, order.id)
        return str(order.id)

    async def market_sell(self, ticker: str, notional_usd: float) -> str:
        """Submit a notional market sell. Returns the order ID."""
        req = MarketOrderRequest(
            symbol=ticker,
            notional=round(notional_usd, 2),
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        order = await self._run(self._client.submit_order, req)
        logger.info("SELL submitted — %s $%.2f order_id=%s", ticker, notional_usd, order.id)
        return str(order.id)

    async def cancel_all_orders(self) -> int:
        """Cancel every open order. Returns the count of cancelled orders."""
        cancel_statuses = await self._run(self._client.cancel_orders)
        count = len(cancel_statuses)
        logger.warning("Cancelled %d open orders.", count)
        return count

    async def close_all_positions(self) -> None:
        """Flatten all open positions — emergency liquidation."""
        await self._run(self._client.close_all_positions, cancel_orders=True)
        logger.warning("All positions closed (emergency liquidation).")

    # ── Positions ──────────────────────────────────────────────────────────────

    async def get_position(self, ticker: str) -> Optional[dict]:
        """Return position dict for *ticker*, or None if flat."""
        try:
            pos = await self._run(self._client.get_open_position, ticker)
            return {
                "ticker": ticker,
                "qty": float(pos.qty),
                "market_value": float(pos.market_value),
                "unrealised_pl": float(pos.unrealized_pl),
                "side": str(pos.side),
            }
        except Exception:
            return None
