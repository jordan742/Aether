"""
orbital-gateway/on_orbit_sim.py — The Eye
-------------------------------------------
Launched by main.py as:
    python orbital-gateway/on_orbit_sim.py

Bootstraps the package path, loads OrbitalGateway, and runs the
continuous orbital simulation loop.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import sys
from pathlib import Path

# ── Path bootstrap ─────────────────────────────────────────────────────────────
# __file__ is  .../Aether/orbital-gateway/on_orbit_sim.py
# _ROOT   is   .../Aether/
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Orion] %(levelname)s — %(message)s",
    stream=sys.stdout,
    force=True,
)

# ── Load orbital_gateway package (hyphen-safe) ────────────────────────────────
_pkg_dir = _ROOT / "orbital-gateway"
_spec = importlib.util.spec_from_file_location(
    "orbital_gateway",
    _pkg_dir / "__init__.py",
    submodule_search_locations=[str(_pkg_dir)],
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["orbital_gateway"] = _mod
_spec.loader.exec_module(_mod)

from orbital_gateway.gateway import OrbitalGateway  # noqa: E402

# ── Run ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        asyncio.run(OrbitalGateway().run())
    except KeyboardInterrupt:
        pass
