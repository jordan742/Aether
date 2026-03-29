"""
run_system.py — Aether Fund One Process Manager
-------------------------------------------------
Launches on_orbit_sim.py (Orion) and trader.py (Midas) as independent
background subprocesses, monitors them with a heartbeat thread, and
auto-restarts any process that crashes.

All lifecycle events are written to shared/system_health.log and to stdout.

Usage:
    python run_system.py

Signals:
    SIGINT / Ctrl-C  — graceful shutdown: terminate both children, then exit
    SIGTERM          — same
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Paths ──────────────────────────────────────────────────────────────────────
_ROOT         = Path(__file__).parent
_HEALTH_LOG   = _ROOT / "shared" / "system_health.log"
_LOGS_DIR     = _ROOT / "logs"
_OVERRIDE_FLAG = _ROOT / "shared" / "OVERRIDE"

_LOGS_DIR.mkdir(parents=True, exist_ok=True)
(_ROOT / "shared").mkdir(parents=True, exist_ok=True)

# ── Tuning ─────────────────────────────────────────────────────────────────────
HEARTBEAT_INTERVAL  = 5    # seconds between health checks
RESTART_COOLDOWN    = 10   # seconds to wait before restarting a crashed process
MAX_RESTARTS        = 50   # give up after this many restarts (prevents thrash loops)
LOG_TAIL_LINES      = 20   # lines of child stdout to capture on crash for diagnosis

# ── Logging ────────────────────────────────────────────────────────────────────
_HEALTH_LOG.touch()

_fmt = logging.Formatter("%(asctime)s [run_system] %(levelname)s — %(message)s")

_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(_fmt)

_file_handler = logging.FileHandler(_HEALTH_LOG, encoding="utf-8")
_file_handler.setFormatter(_fmt)

logger = logging.getLogger("run_system")
logger.setLevel(logging.DEBUG)
logger.addHandler(_console_handler)
logger.addHandler(_file_handler)


# ══════════════════════════════════════════════════════════════════════════════
# Process descriptor
# ══════════════════════════════════════════════════════════════════════════════

class ManagedProcess:
    """Wraps a subprocess with restart bookkeeping."""

    def __init__(self, name: str, script: str) -> None:
        self.name          = name
        self.script        = script
        self.proc: Optional[subprocess.Popen] = None
        self.restart_count = 0
        self.last_start_ts = 0.0
        self._log_path     = _LOGS_DIR / f"{name}.log"
        self._log_fh       = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._log_fh:
            self._log_fh.close()

        self._log_fh = open(self._log_path, "a", encoding="utf-8", buffering=1)
        header = (
            f"\n{'='*60}\n"
            f"  START  {self.name}  {datetime.now(timezone.utc).isoformat()}\n"
            f"{'='*60}\n"
        )
        self._log_fh.write(header)
        self._log_fh.flush()

        self.proc = subprocess.Popen(
            [sys.executable, "-u", str(_ROOT / self.script)],
            stdout=self._log_fh,
            stderr=subprocess.STDOUT,
            cwd=str(_ROOT),
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        self.last_start_ts = time.monotonic()
        logger.info("Started %-18s PID=%-6d log=%s", self.name, self.proc.pid, self._log_path.name)

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
            logger.info("Stopped %-18s PID=%d", self.name, self.proc.pid)
        if self._log_fh:
            self._log_fh.close()
            self._log_fh = None

    # ── Health ─────────────────────────────────────────────────────────────────

    @property
    def is_alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    @property
    def exit_code(self) -> int | None:
        return self.proc.poll() if self.proc else None

    @property
    def pid(self) -> int | None:
        return self.proc.pid if self.proc else None

    @property
    def uptime_s(self) -> float:
        return time.monotonic() - self.last_start_ts if self.last_start_ts else 0.0

    def log_tail(self, n: int = LOG_TAIL_LINES) -> str:
        """Return the last *n* lines from the child process log."""
        try:
            lines = self._log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            return "\n".join(lines[-n:])
        except OSError:
            return "(log unavailable)"


# ══════════════════════════════════════════════════════════════════════════════
# System Manager
# ══════════════════════════════════════════════════════════════════════════════

class SystemManager:
    """Orchestrates Orion + Midas with heartbeat monitoring."""

    PROCESSES = [
        ManagedProcess("on_orbit_sim", "on_orbit_sim.py"),
        ManagedProcess("trader",       "trader.py"),
    ]

    def __init__(self) -> None:
        self._shutdown = threading.Event()
        self._lock     = threading.Lock()

    # ── Public API ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Start all processes, then block in the heartbeat loop."""
        self._register_signal_handlers()
        logger.info("═" * 60)
        logger.info("  AETHER FUND ONE — SYSTEM MANAGER ONLINE")
        logger.info("  Heartbeat interval: %ds  Max restarts: %d", HEARTBEAT_INTERVAL, MAX_RESTARTS)
        logger.info("═" * 60)

        with self._lock:
            for mp in self.PROCESSES:
                mp.start()

        self._heartbeat_loop()

    def shutdown(self) -> None:
        """Signal the heartbeat loop to exit and stop all children."""
        logger.info("Shutdown requested — stopping all agents…")
        self._shutdown.set()
        with self._lock:
            for mp in self.PROCESSES:
                mp.stop()
        logger.info("All agents stopped. System Manager offline.")

    # ── Heartbeat ──────────────────────────────────────────────────────────────

    def _heartbeat_loop(self) -> None:
        while not self._shutdown.is_set():
            # ── Override flag check ────────────────────────────────────────────
            if _OVERRIDE_FLAG.exists():
                logger.critical(
                    "SYSTEM OVERRIDE FLAG DETECTED — halting all agents."
                )
                self.shutdown()
                return

            with self._lock:
                for mp in self.PROCESSES:
                    self._check_process(mp)

            self._shutdown.wait(timeout=HEARTBEAT_INTERVAL)

    def _check_process(self, mp: ManagedProcess) -> None:
        if mp.is_alive:
            logger.debug(
                "HEARTBEAT %-18s PID=%-6d uptime=%.0fs restarts=%d",
                mp.name, mp.pid, mp.uptime_s, mp.restart_count,
            )
            return

        exit_code = mp.exit_code
        uptime    = mp.uptime_s

        logger.error(
            "PROCESS_DOWN %-18s exit_code=%-4s uptime=%.1fs restarts=%d/%d",
            mp.name, exit_code, uptime, mp.restart_count, MAX_RESTARTS,
        )

        # Capture tail of child log for diagnosis
        tail = mp.log_tail()
        if tail:
            logger.error("Last output from %s:\n%s", mp.name, tail)

        if mp.restart_count >= MAX_RESTARTS:
            logger.critical(
                "MAX_RESTARTS reached for %s — giving up. "
                "Inspect logs/%s.log for root cause.",
                mp.name, mp.name,
            )
            return

        # Cooldown before restart
        elapsed = time.monotonic() - mp.last_start_ts
        if elapsed < RESTART_COOLDOWN:
            wait = RESTART_COOLDOWN - elapsed
            logger.info("Cooldown %.1fs before restarting %s…", wait, mp.name)
            time.sleep(wait)

        mp.restart_count += 1
        logger.warning(
            "RESTART #%d — %s (exit_code=%s)", mp.restart_count, mp.name, exit_code
        )
        mp.start()

    # ── Signals ────────────────────────────────────────────────────────────────

    def _register_signal_handlers(self) -> None:
        def _handler(signum, _frame):
            logger.info("Received signal %d — initiating graceful shutdown.", signum)
            # Run shutdown in a thread so we don't block the signal handler
            threading.Thread(target=self.shutdown, daemon=True).start()

        signal.signal(signal.SIGINT,  _handler)
        signal.signal(signal.SIGTERM, _handler)


# ══════════════════════════════════════════════════════════════════════════════
# Status writer (shared/system_status.json for dashboard)
# ══════════════════════════════════════════════════════════════════════════════

def _write_status_loop(manager: SystemManager) -> None:
    """Write a live system_status.json every heartbeat so the dashboard can read it."""
    import json

    status_path = _ROOT / "shared" / "system_status.json"
    while not manager._shutdown.is_set():
        with manager._lock:
            status = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "processes": {
                    mp.name: {
                        "alive":         mp.is_alive,
                        "pid":           mp.pid,
                        "restart_count": mp.restart_count,
                        "uptime_s":      round(mp.uptime_s, 1),
                        "exit_code":     mp.exit_code,
                    }
                    for mp in manager.PROCESSES
                },
            }
        try:
            tmp = status_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(status, indent=2), encoding="utf-8")
            os.replace(tmp, status_path)
        except OSError:
            pass
        manager._shutdown.wait(timeout=HEARTBEAT_INTERVAL)


# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    manager = SystemManager()

    # Start status writer in background thread
    status_thread = threading.Thread(
        target=_write_status_loop, args=(manager,), daemon=True, name="status-writer"
    )
    status_thread.start()

    try:
        manager.run()
    except Exception as exc:
        logger.critical("Unhandled exception in SystemManager: %s", exc, exc_info=True)
        manager.shutdown()
        sys.exit(1)
