"""
Orbital-to-Equity Cycle Runner
--------------------------------
Designed to be called every 10 minutes by cron (or any scheduler).

Each invocation:
  1. Triggers one orbital gateway tick (Sentinel-2 fetch → YOLOv8 → bridge write).
  2. Reads shared/telemetry.json for the latest signal + confidence.
  3. Checks shared/trades.jsonl for any entry newer than the previous run.
  4. If a new trade was executed, fires a desktop notification via notify-send
     (Linux) with: ticker, direction, notional, confidence score, and a P&L
     estimate based on the signal strength.
  5. Appends a one-line summary to shared/loop.log.

Installation (add to crontab with `crontab -e`):
    */10 * * * * /usr/bin/python3 /path/to/Aether/shared/cycle_runner.py >> /path/to/Aether/shared/loop.log 2>&1

Or run manually for a one-shot execution:
    python shared/cycle_runner.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [cycle_runner] %(levelname)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("cycle_runner")

_TRADES_LOG   = _ROOT / "shared" / "trades.jsonl"
_LOOP_LOG     = _ROOT / "shared" / "loop.log"
_LAST_RUN_TS  = _ROOT / "shared" / ".last_cycle_ts"
_OVERRIDE_FLAG = _ROOT / "shared" / "OVERRIDE"

# ── File handler so cron stdout captures structured logs ───────────────────────
_LOOP_LOG.parent.mkdir(parents=True, exist_ok=True)
_fh = logging.FileHandler(_LOOP_LOG, encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s [cycle_runner] %(levelname)s — %(message)s"))
logger.addHandler(_fh)


# ══════════════════════════════════════════════════════════════════════════════
# Desktop notification
# ══════════════════════════════════════════════════════════════════════════════

def _notify(title: str, body: str, urgency: str = "normal") -> None:
    """Send a desktop notification via notify-send (Linux/D-Bus)."""
    try:
        subprocess.run(
            ["notify-send", "--urgency", urgency, "--app-name", "Aether Fund",
             "--icon", "dialog-information", title, body],
            timeout=5,
            check=False,
            capture_output=True,
        )
        logger.info("Desktop notification sent: %s — %s", title, body)
    except FileNotFoundError:
        # notify-send not installed — log only
        logger.warning("notify-send not found. Notification: [%s] %s", title, body)
    except Exception as exc:
        logger.warning("Notification failed: %s", exc)


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _read_last_run_ts() -> str | None:
    if _LAST_RUN_TS.exists():
        return _LAST_RUN_TS.read_text(encoding="utf-8").strip() or None
    return None


def _write_last_run_ts(ts: str) -> None:
    _LAST_RUN_TS.write_text(ts, encoding="utf-8")


def _new_trades_since(last_ts: str | None) -> list[dict]:
    """Return trade log entries written after *last_ts*."""
    if not _TRADES_LOG.exists():
        return []
    entries = []
    for line in _TRADES_LOG.read_text(encoding="utf-8").strip().splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if last_ts is None or (rec.get("timestamp", "") > last_ts):
            entries.append(rec)
    return entries


def _estimate_pnl(notional: float, strength: float, direction: str) -> float:
    """
    Rough P&L estimate for notification purposes.

    Formula: notional × strength × 0.015 (1.5% expected edge per trade,
    scaled by signal confidence).  Negative for SELL (short).
    """
    edge = notional * strength * 0.015
    return round(edge if direction == "BUY" else -edge, 2)


# ══════════════════════════════════════════════════════════════════════════════
# Orbital tick
# ══════════════════════════════════════════════════════════════════════════════

async def _run_orbital_tick() -> dict:
    """
    Fire one gateway tick and return the resulting telemetry payload.

    Imports are deferred so cycle_runner has no hard dependency on
    orbital-gateway being installed as a package.
    """
    import importlib.util

    def _load(alias: str, dir_name: str) -> None:
        pkg_dir = _ROOT / dir_name
        spec = importlib.util.spec_from_file_location(
            alias, pkg_dir / "__init__.py",
            submodule_search_locations=[str(pkg_dir)],
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[alias] = mod
        spec.loader.exec_module(mod)

    _load("orbital_gateway", "orbital-gateway")
    _load("equity_bot", "equity-bot")

    from orbital_gateway.gateway import OrbitalGateway  # type: ignore
    from shared.bridge import TelemetryBridge

    bridge  = TelemetryBridge()
    gateway = OrbitalGateway(bridge=bridge)

    await gateway._tick()           # single tick, no loop
    return await bridge.read()


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

async def main() -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    logger.info("═══ Cycle start %s ═══", now_iso)

    # ── Override guard ─────────────────────────────────────────────────────────
    if _OVERRIDE_FLAG.exists():
        logger.warning("SYSTEM OVERRIDE active — cycle aborted.")
        return

    last_ts = _read_last_run_ts()
    logger.info("Last run timestamp: %s", last_ts or "none (first run)")

    # ── 1. Orbital tick ────────────────────────────────────────────────────────
    try:
        telemetry = await _run_orbital_tick()
        logger.info(
            "Tick complete — port=%s ships=%s signal=%s(%.2f)",
            (telemetry.get("scene") or {}).get("port", "?"),
            (telemetry.get("detection") or {}).get("ship_count", "?"),
            (telemetry.get("signal") or {}).get("direction", "?"),
            float((telemetry.get("signal") or {}).get("strength") or 0),
        )
    except Exception as exc:
        logger.error("Orbital tick failed: %s", exc, exc_info=True)
        telemetry = {}

    # ── 2. Signal metadata for notification ────────────────────────────────────
    detection = telemetry.get("detection") or {}
    signal    = telemetry.get("signal") or {}
    conf      = detection.get("confidence_mean")
    direction = signal.get("direction", "HOLD")
    strength  = float(signal.get("strength") or 0.0)
    ticker    = signal.get("ticker", "—")

    # ── 3. Check for new trades ────────────────────────────────────────────────
    new_trades = _new_trades_since(last_ts)
    logger.info("New trades since last run: %d", len(new_trades))

    for trade in new_trades:
        t_ticker    = trade.get("ticker", "—")
        t_dir       = trade.get("direction", "—")
        t_notional  = float(trade.get("notional") or 0.0)
        t_ts        = trade.get("timestamp", "—")

        # Use live confidence from telemetry (most recent tick)
        t_conf  = conf if conf is not None else "N/A"
        pnl_est = _estimate_pnl(t_notional, strength, t_dir)

        logger.info(
            "Trade executed — %s %s $%.2f | conf=%.2f pnl_est=$%.2f",
            t_dir, t_ticker, t_notional,
            t_conf if isinstance(t_conf, float) else 0.0,
            pnl_est,
        )

        # ── 4. Desktop notification ────────────────────────────────────────────
        conf_str = f"{t_conf:.2f}" if isinstance(t_conf, float) else str(t_conf)
        pnl_sign = "+" if pnl_est >= 0 else ""
        _notify(
            title=f"Aether — {t_dir} {t_ticker}",
            body=(
                f"Notional: ${t_notional:,.2f}\n"
                f"Confidence: {conf_str}\n"
                f"P&L est: {pnl_sign}${pnl_est:,.2f}\n"
                f"Time: {t_ts}"
            ),
            urgency="critical" if abs(pnl_est) > 500 else "normal",
        )

    # ── 5. Update last-run timestamp ───────────────────────────────────────────
    _write_last_run_ts(now_iso)
    logger.info("═══ Cycle end — next run in ~10 min ═══\n")


if __name__ == "__main__":
    asyncio.run(main())
