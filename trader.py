"""
trader.py — Equity Bot Process
---------------------------------
Managed entry point for the Midas agent.
Launched and monitored by run_system.py heartbeat.

Stdout is line-buffered so run_system.py can capture it in real time.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import sys
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [trader] %(levelname)s — %(message)s",
    stream=sys.stdout,
)


def _load_pkg(alias: str, dir_name: str) -> None:
    pkg_dir = _ROOT / dir_name
    spec = importlib.util.spec_from_file_location(
        alias,
        pkg_dir / "__init__.py",
        submodule_search_locations=[str(pkg_dir)],
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)


# equity-bot imports shared and orbital-gateway types at runtime
_load_pkg("orbital_gateway", "orbital-gateway")
_load_pkg("equity_bot", "equity-bot")

from equity_bot.bot import EquityBot  # noqa: E402


if __name__ == "__main__":
    try:
        asyncio.run(EquityBot().run())
    except KeyboardInterrupt:
        logging.getLogger("trader").info("Shutdown via KeyboardInterrupt.")
        sys.exit(0)
