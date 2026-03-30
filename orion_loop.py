"""
orion_loop.py — Orion Continuous Feed Runner
=============================================
Runs orion_feed.run_observation() on a fixed interval, writing each
observation to data/energy_flow.csv for dashboard.py to consume.

This is the production runner for the Orion pipeline.  Run it in a
separate terminal alongside the Streamlit dashboard:

    Terminal 1:  python orion_loop.py
    Terminal 2:  streamlit run dashboard.py

Environment variables
---------------------
ORION_INTERVAL_SECONDS  Seconds between observations (default: 300 = 5 min).
SENTINEL_USER           Copernicus username (blank → simulation mode).
SENTINEL_PASSWORD       Copernicus password (blank → simulation mode).

Cron alternative (hourly)
-------------------------
    0 * * * * cd /path/to/Aether && python orion_feed.py >> data/orion.log 2>&1
"""

from __future__ import annotations

import logging
import os
import time

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [OrionLoop] %(levelname)s — %(message)s",
)

# Default cadence: one observation every 5 minutes.
# Reduce for development (e.g. ORION_INTERVAL_SECONDS=30).
DEFAULT_INTERVAL = 300


def run_loop(interval: int = DEFAULT_INTERVAL) -> None:
    """
    Run the Orion observation pipeline indefinitely at a fixed interval.

    Parameters
    ----------
    interval : int
        Seconds between each observation cycle.
    """
    # Import here so path errors surface immediately with a clear message
    try:
        from orion_feed import run_observation
    except ImportError as exc:
        log.error("Cannot import orion_feed: %s", exc)
        raise

    log.info("Orion loop started — interval=%ds  (Ctrl-C to stop)", interval)

    cycle = 0
    while True:
        cycle += 1
        try:
            result = run_observation()
            log.info(
                "Cycle %d — tankers=%d  confidence=%.2f  cloud=%s  source=%s",
                cycle,
                result.tanker_count,
                result.confidence_score,
                result.cloud_flag,
                result.source,
            )
        except Exception as exc:
            # Log and continue — a single bad observation should not kill the loop
            log.error("Cycle %d failed: %s", cycle, exc)

        log.debug("Sleeping %ds until next observation…", interval)
        time.sleep(interval)


if __name__ == "__main__":
    interval = int(os.getenv("ORION_INTERVAL_SECONDS", str(DEFAULT_INTERVAL)))
    try:
        run_loop(interval)
    except KeyboardInterrupt:
        log.info("Orion loop stopped.")
