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
import importlib.util
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))


def _load_from_hyphenated(package_alias: str, dir_name: str) -> None:
    """Register a hyphenated directory as an importable package alias.

    Python cannot import 'orbital-gateway' directly because '-' is not a valid
    identifier character.  This helper loads each module under the directory
    and registers it under the alias (e.g. 'orbital_gateway') so that
    subsequent ``from orbital_gateway.xyz import ...`` statements work.
    """
    pkg_dir = _ROOT / dir_name
    # Register the package itself
    spec = importlib.util.spec_from_file_location(
        package_alias,
        pkg_dir / "__init__.py",
        submodule_search_locations=[str(pkg_dir)],
    )
    pkg = importlib.util.module_from_spec(spec)
    sys.modules[package_alias] = pkg
    spec.loader.exec_module(pkg)


_load_from_hyphenated("orbital_gateway", "orbital-gateway")
_load_from_hyphenated("equity_bot", "equity-bot")

from orbital_gateway.gateway import OrbitalGateway          # noqa: E402
from equity_bot.bot import EquityBot                        # noqa: E402
from equity_bot.circuit_breaker import CircuitBreakerTripped  # noqa: E402

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
