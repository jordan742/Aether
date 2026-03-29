"""
Alpaca Client
-------------
Thin async wrapper around alpaca-py for paper-trading operations used by the
equity bot. Handles account info, order submission, and position management.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce, OrderStatus
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest

logger = logging.getLogger(__name__)

_API_KEY = os.getenv("ALPACA_API_KEY", "")
_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
_PAPER = True  # always paper-trade


class AlpacaClient:
    """Async-friendly facade over the Alpaca paper trading API."""

    def __init__(
        self,
        api_key: str = _API_KEY,
        secret_key: str = _SECRET_KEY,
    ) -> None:
        if not api_key or not secret_key:
            raise EnvironmentError(
                "ALPACA_API_KEY and ALPACA_SECRET_KEY must be set in .env"
            )
        self._client = TradingClient(api_key, secret_key, paper=_PAPER)

    # ── Account ────────────────────────────────────────────────────────────────

    def get_equity(self) -> float:
        """Return current portfolio equity in USD."""
        account = self._client.get_account()
        return float(account.equity)

    def get_cash(self) -> float:
        account = self._client.get_account()
        return float(account.cash)

    # ── Orders ─────────────────────────────────────────────────────────────────

    def market_buy(self, ticker: str, notional_usd: float) -> str:
        """Submit a notional market buy. Returns the order ID."""
        req = MarketOrderRequest(
            symbol=ticker,
            notional=round(notional_usd, 2),
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )
        order = self._client.submit_order(req)
        logger.info("BUY submitted — %s $%.2f order_id=%s", ticker, notional_usd, order.id)
        return str(order.id)

    def market_sell(self, ticker: str, notional_usd: float) -> str:
        """Submit a notional market sell. Returns the order ID."""
        req = MarketOrderRequest(
            symbol=ticker,
            notional=round(notional_usd, 2),
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        order = self._client.submit_order(req)
        logger.info("SELL submitted — %s $%.2f order_id=%s", ticker, notional_usd, order.id)
        return str(order.id)

    def cancel_all_orders(self) -> None:
        """Cancel every open order — called by the circuit breaker shutdown hook."""
        cancel_statuses = self._client.cancel_orders()
        logger.warning("Cancelled %d open orders.", len(cancel_statuses))

    def close_all_positions(self) -> None:
        """Flatten all open positions — emergency liquidation."""
        self._client.close_all_positions(cancel_orders=True)
        logger.warning("All positions closed (emergency liquidation).")

    # ── Positions ──────────────────────────────────────────────────────────────

    def get_position(self, ticker: str) -> Optional[dict]:
        """Return position dict for *ticker*, or None if flat."""
        try:
            pos = self._client.get_open_position(ticker)
            return {
                "ticker": ticker,
                "qty": float(pos.qty),
                "market_value": float(pos.market_value),
                "unrealised_pl": float(pos.unrealized_pl),
                "side": str(pos.side),
            }
        except Exception:
            return None
