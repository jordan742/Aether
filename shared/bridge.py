"""
Sovereign Bridge
----------------
Async read/write interface for shared/telemetry.json.
Both the orbital-gateway (writer) and equity-bot (reader) use this module
so the data-link contract stays in one place.

Payload is capped at 1 KB to match orbital-gateway spec.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_BRIDGE_FILE = Path(__file__).parent / "telemetry.json"
_MAX_BYTES = 1024  # 1 KB hard cap
_LOCK = asyncio.Lock()


class TelemetryBridge:
    """Async wrapper around the telemetry.json sovereign bridge file."""

    def __init__(self, path: Path = _BRIDGE_FILE) -> None:
        self.path = path

    # ── Writer API (orbital-gateway) ──────────────────────────────────────────

    async def write(self, payload: dict[str, Any]) -> None:
        """Atomically write *payload* to the bridge file.

        Raises ValueError if the serialised payload exceeds 1 KB.
        """
        payload["timestamp"] = datetime.now(timezone.utc).isoformat()
        raw = json.dumps(payload, separators=(",", ":"))

        if len(raw.encode()) > _MAX_BYTES:
            raise ValueError(
                f"Telemetry payload exceeds 1 KB limit "
                f"({len(raw.encode())} bytes). Trim before writing."
            )

        async with _LOCK:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(raw, encoding="utf-8")
            os.replace(tmp, self.path)  # atomic on POSIX

        logger.debug("Bridge updated (%d bytes)", len(raw.encode()))

    # ── Reader API (equity-bot / dashboard) ───────────────────────────────────

    async def read(self) -> dict[str, Any]:
        """Return the current telemetry snapshot as a dict."""
        async with _LOCK:
            text = self.path.read_text(encoding="utf-8")
        return json.loads(text)

    async def wait_for_signal(
        self,
        poll_interval: float = 1.0,
        timeout: float = 300.0,
    ) -> dict[str, Any]:
        """Block until a non-null signal is present or *timeout* seconds elapse."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            data = await self.read()
            if data.get("signal", {}).get("direction") is not None:
                return data
            await asyncio.sleep(poll_interval)
        raise TimeoutError("No signal received within timeout window.")
