"""
Signal Watcher — Midas: The Executioner
-----------------------------------------
Continuously polls the Sovereign Bridge and converts Orion's Proprietary
Truth into conviction-weighted, volatility-adjusted Alpaca paper trades.

Schema v3.0.0 contract (written by orbital-gateway):

    {
        "schema_version": "3.0.0",
        "classification": "PROPRIETARY_ALPHA",
        "source": "orbital-gateway",
        "timestamp": "...",
        "scene": { "port": "strait_of_hormuz", ... },
        "detection_enc": "<fernet_token>",        ← Orion encrypts
        "orbital_truth": {
            "observation_type": "tanker_density_spike",
            "delta_pct": 15.2,
            "dominant_vessel_type": "tankers",
            "thesis": "15.2% tanker surplus at Hormuz ..."
        },
        "alpha_signal": {
            "ticker": "XOM",
            "sector": "energy",
            "direction": "BUY",
            "conviction": "HIGH",
            "strength": 0.82,
            "rationale": "vessel_count_15.2pct_above_30d_avg"
        },
        "status": "active"
    }

Execution Logic
    1. Decrypt detection block (Fernet).
    2. Extract alpha_signal: direction, conviction, strength, ticker.
    3. Fetch VIX. Determine regime and position multiplier.
    4. If PANIC (VIX ≥ 40): BLOCK execution entirely.
    5. Compute notional = equity × conviction_pct × vix_multiplier.
    6. Execute market order. Log to shared/trades.jsonl.
    7. Post-trade circuit breaker check.

Conviction → Base Position PCT
    EXTREME  → 8 % of equity
    HIGH     → 5 % of equity
    MEDIUM   → 2.5 % of equity
    LOW      → skip (below threshold)
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from shared.bridge import TelemetryBridge
from shared.crypto import cipher as _cipher
from .alpaca_client import AlpacaClient
from .circuit_breaker import StarkCircuitBreaker, CircuitBreakerTripped
from .market_context import MarketContext

logger = logging.getLogger(__name__)

# ── Conviction → base position percentage ──────────────────────────────────────
_CONVICTION_PCT: dict[str, float] = {
    "EXTREME": 0.08,
    "HIGH":    0.05,
    "MEDIUM":  0.025,
    "LOW":     0.0,    # skipped
}

DEFAULT_POLL: int = 5   # seconds between bridge polls

_ROOT          = Path(__file__).parent.parent
_OVERRIDE_FLAG = _ROOT / "shared" / "OVERRIDE"
_TRADES_LOG    = _ROOT / "shared" / "trades.jsonl"


class SignalWatcher:
    """
    Reads the Sovereign Bridge, verifies against VIX, and fires trades.
    Midas does not trade blind — he is The Executioner, not a gambler.
    """

    def __init__(
        self,
        bridge: TelemetryBridge,
        alpaca: AlpacaClient,
        breaker: StarkCircuitBreaker,
        poll_interval: int = DEFAULT_POLL,
        _stop_flag: list[bool] | None = None,
    ) -> None:
        self.bridge        = bridge
        self.alpaca        = alpaca
        self.breaker       = breaker
        self.poll_interval = poll_interval
        self._last_ts: str | None = None
        self._stop_flag    = _stop_flag if _stop_flag is not None else [False]
        self._market_ctx   = MarketContext()

    # ── Public API ─────────────────────────────────────────────────────────────

    async def watch(self) -> None:
        """
        Main polling loop. Runs until CircuitBreakerTripped or stop flag set.
        """
        logger.info(
            "Midas (The Executioner) online — poll=%ds conviction_pcts=%s",
            self.poll_interval,
            {k: f"{v:.0%}" for k, v in _CONVICTION_PCT.items() if v > 0},
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
                raise
            except Exception as exc:
                logger.error("Cycle error: %s", exc, exc_info=True)

            await asyncio.sleep(self.poll_interval)

    # ── Internal helpers ───────────────────────────────────────────────────────

    async def _is_new_signal(self, telemetry: dict) -> bool:
        ts = telemetry.get("timestamp")
        return bool(ts and ts != self._last_ts)

    async def _process(self, telemetry: dict) -> None:
        """Evaluate signal, apply VIX gate, execute conviction-sized trade."""

        # ── 1. Midas decrypts Orion's proprietary detection block ──────────────
        if "detection_enc" in telemetry:
            telemetry["detection"] = _cipher.decrypt(telemetry["detection_enc"])
            logger.debug("Detection block decrypted (Fernet).")

        # ── 2. Extract v3.0.0 fields ───────────────────────────────────────────
        alpha   = telemetry.get("alpha_signal") or telemetry.get("signal") or {}
        truth   = telemetry.get("orbital_truth") or {}
        detect  = telemetry.get("detection") or {}
        scene   = telemetry.get("scene") or {}

        direction  = alpha.get("direction", "HOLD")
        conviction = alpha.get("conviction", "LOW")
        strength   = float(alpha.get("strength") or 0.0)
        ticker     = alpha.get("ticker", "—")
        sector     = alpha.get("sector", "unknown")
        thesis     = truth.get("thesis", "—")
        delta_pct  = float(truth.get("delta_pct") or 0.0)
        dom_type   = truth.get("dominant_vessel_type", "mixed")
        port       = scene.get("port", "unknown")
        ts         = telemetry.get("timestamp", "")

        self._last_ts = ts

        logger.info(
            "Uplink received — port=%s Δ=%.1f%% type=%s conviction=%s "
            "direction=%s %s",
            port, delta_pct, dom_type, conviction, direction, ticker,
        )
        logger.info("Thesis: %s", thesis)

        # ── 3. Skip non-actionable signals ─────────────────────────────────────
        if direction == "HOLD":
            logger.info("Direction=HOLD — standing down.")
            return

        base_pct = _CONVICTION_PCT.get(conviction, 0.0)
        if base_pct == 0.0:
            logger.info("Conviction=LOW — below execution threshold.")
            return

        # ── 4. VIX gate — Midas verifies against market volatility ────────────
        vix_snap   = await self._market_ctx.get_vix()
        vix_mult   = self._market_ctx.position_multiplier(vix_snap, conviction)

        if vix_mult == 0.0:
            logger.critical(
                "VIX PANIC GATE ACTIVE — VIX=%.2f (%s). "
                "Thesis blocked: %s",
                vix_snap.value, vix_snap.regime, thesis,
            )
            return

        logger.info(
            "VIX=%.2f %s — position multiplier=×%.2f",
            vix_snap.value, vix_snap.regime, vix_mult,
        )

        # ── 5. Size the order ──────────────────────────────────────────────────
        equity   = await self.alpaca.get_equity()
        notional = round(equity * base_pct * vix_mult, 2)

        logger.info(
            "EXECUTING %s %s [%s] — equity=$%.2f "
            "base=%.0f%% vix_mult=×%.2f notional=$%.2f | %s",
            direction, ticker, conviction,
            equity, base_pct * 100, vix_mult, notional, thesis,
        )

        # ── 6. Fire the order ──────────────────────────────────────────────────
        if direction == "BUY":
            await self.alpaca.market_buy(ticker, notional)
        elif direction == "SELL":
            await self.alpaca.market_sell(ticker, notional)
        else:
            logger.warning("Unknown direction '%s' — no order placed.", direction)
            return

        # ── 7. Trade log for dashboard + cycle_runner ──────────────────────────
        self._log_trade(
            ticker=ticker,
            direction=direction,
            notional=notional,
            conviction=conviction,
            sector=sector,
            delta_pct=delta_pct,
            vix=vix_snap.value,
            vix_regime=vix_snap.regime,
            thesis=thesis,
        )

        # ── 8. Post-trade circuit breaker check ────────────────────────────────
        try:
            await self.breaker.check(await self.alpaca.get_equity())
        except CircuitBreakerTripped as exc:
            logger.critical(
                "STARK CIRCUIT BREAKER — loss=%.2f%% threshold=%.2f%%. "
                "Flattening all positions.",
                exc.loss_pct * 100, exc.threshold * 100,
            )
            await self.alpaca.cancel_all_orders()
            await self.alpaca.close_all_positions()
            raise

    # ── Trade logger ───────────────────────────────────────────────────────────

    @staticmethod
    def _log_trade(
        ticker: str, direction: str, notional: float,
        conviction: str, sector: str, delta_pct: float,
        vix: float, vix_regime: str, thesis: str,
    ) -> None:
        record = {
            "timestamp":  datetime.now(timezone.utc).isoformat(),
            "ticker":     ticker,
            "direction":  direction,
            "notional":   notional,
            "conviction": conviction,
            "sector":     sector,
            "delta_pct":  delta_pct,
            "vix":        vix,
            "vix_regime": vix_regime,
            "thesis":     thesis,
            "pnl":        None,
        }
        try:
            with _TRADES_LOG.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
        except OSError as exc:
            logger.warning("Could not write trade log: %s", exc)
