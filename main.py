"""
main.py — Aether Fund One Orchestrator
----------------------------------------
Launches the three pillars of Aether Fund One as independent subprocesses
and guarantees a clean exit regardless of how the terminal is closed.

    The Eye  →  orbital-gateway/on_orbit_sim.py
    The Hand →  equity-bot/trader.py
    The Mind →  dashboard.py  (Streamlit on http://localhost:8501)

Usage:
    python main.py

Exit:
    Ctrl-C, SIGTERM, or closing the terminal sends SIGTERM to all three
    children, waits up to 8 s, then SIGKILL stragglers.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# ── Setup ──────────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [main] %(levelname)s — %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("main")

# ── Process table ──────────────────────────────────────────────────────────────
_PROCESSES: dict[str, subprocess.Popen] = {}

_LAUNCH = [
    ("eye",  [sys.executable, "orbital-gateway/on_orbit_sim.py"]),
    ("hand", [sys.executable, "equity-bot/trader.py"]),
    ("mind", [sys.executable, "-m", "streamlit", "run", "dashboard.py",
              "--server.port", "8501",
              "--server.headless", "true",
              "--theme.base", "dark",
              "--theme.backgroundColor", "#0E1117",
              "--theme.primaryColor", "#00D4FF"]),
]

# ── Shutdown ───────────────────────────────────────────────────────────────────

def _shutdown(signum=None, frame=None) -> None:
    """Terminate all children cleanly, then exit."""
    log.info("Shutdown signal received — stopping all agents…")
    for name, proc in _PROCESSES.items():
        if proc.poll() is None:
            log.info("  Stopping %-6s (PID %d)…", name, proc.pid)
            proc.terminate()

    # Give processes up to 8 s to exit gracefully
    deadline = time.monotonic() + 8
    for name, proc in _PROCESSES.items():
        remaining = max(0.0, deadline - time.monotonic())
        try:
            proc.wait(timeout=remaining)
            log.info("  %-6s exited (code %s).", name, proc.returncode)
        except subprocess.TimeoutExpired:
            log.warning("  %-6s did not stop — sending SIGKILL.", name)
            proc.kill()
            proc.wait()

    log.info("All agents stopped. Aether Fund One offline.")
    sys.exit(0)


# Register every signal that means "we're going away"
for _sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(_sig, _shutdown)

# SIGHUP = terminal window closed (POSIX only)
if hasattr(signal, "SIGHUP"):
    signal.signal(signal.SIGHUP, _shutdown)

# ── Launch ─────────────────────────────────────────────────────────────────────

def _start(name: str, cmd: list[str]) -> subprocess.Popen:
    proc = subprocess.Popen(
        cmd,
        cwd=str(_ROOT),
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    log.info("Started %-6s → %s  (PID %d)", name, " ".join(cmd[:3]), proc.pid)
    return proc


print()
print("  ╔══════════════════════════════════════════╗")
print("  ║        AETHER FUND ONE — LAUNCHING       ║")
print("  ╚══════════════════════════════════════════╝")
print()

for _name, _cmd in _LAUNCH:
    _PROCESSES[_name] = _start(_name, _cmd)
    time.sleep(1)   # stagger startup so Streamlit sees a live bridge on first load

print()
log.info("All systems online.")
log.info("Command Center → http://localhost:8501")
log.info("Press Ctrl-C or close this terminal to shut down.")
print()

# ── Monitor loop ───────────────────────────────────────────────────────────────
# Block until all children exit (or a signal fires _shutdown).
try:
    while True:
        for name, proc in list(_PROCESSES.items()):
            code = proc.poll()
            if code is not None:
                log.warning("%-6s exited unexpectedly (code %s).", name, code)
        time.sleep(5)
except KeyboardInterrupt:
    _shutdown()
