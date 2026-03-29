"""
Aether Fund One — Main Launcher
--------------------------------
Starts the Orbital Gateway and Equity Bot as concurrent async tasks
in a single process.  The Sovereign Bridge (shared/telemetry.json) is the
only communication channel between them.

Usage:
    python main.py

Individual components can also be run standalone:
    python -m orbital-gateway
    python -m equity-bot
    streamlit run dashboard/app.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))

from orbital_gateway.gateway import OrbitalGateway
from equity_bot.bot import EquityBot
from equity_bot.circuit_breaker import CircuitBreakerTripped

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("aether.main")


async def main() -> None:
    gateway = OrbitalGateway()
    bot = EquityBot()

    async def run_gateway() -> None:
        await gateway.run()

    async def run_bot() -> None:
        try:
            await bot.run()
        except CircuitBreakerTripped as exc:
            logger.critical("Circuit breaker killed the bot: %s", exc)
            gateway.stop()

    logger.info("Aether Fund One starting up…")
    await asyncio.gather(run_gateway(), run_bot())
    logger.info("Aether Fund One shut down cleanly.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Manual shutdown.")
