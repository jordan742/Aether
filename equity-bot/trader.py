"""
equity-bot/trader.py — The Hand
---------------------------------
Launched by main.py as:
    python equity-bot/trader.py

Bootstraps the package path, loads EquityBot, and runs the
conviction-weighted, VIX-gated trading loop.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import sys
from pathlib import Path

# ── Path bootstrap ─────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Midas] %(levelname)s — %(message)s",
    stream=sys.stdout,
    force=True,
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


# equity-bot imports orbital_gateway types at runtime (sentinel.SceneResult etc.)
_load_pkg("orbital_gateway", "orbital-gateway")
_load_pkg("equity_bot",      "equity-bot")

from equity_bot.bot import EquityBot  # noqa: E402

# ── Run ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        asyncio.run(EquityBot().run())
    except KeyboardInterrupt:
        pass
