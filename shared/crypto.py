"""
Sovereign Bridge — Fernet Encryption Layer
-------------------------------------------
Provides symmetric AES-128-CBC encryption (via the `cryptography` Fernet
implementation) for the detection block written to shared/telemetry.json.

Key management
    The key is a URL-safe base64-encoded 32-byte secret stored in the
    environment variable TELEMETRY_FERNET_KEY.

    To generate a new key (run once, store output in .env):
        python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

    If the key is absent the module falls back to plaintext mode and logs a
    warning — this allows the system to boot without encryption configured,
    but it will NOT encrypt any data.

Orion (writer) usage:
    from shared.crypto import cipher
    payload["detection_enc"] = cipher.encrypt(payload.pop("detection"))

Midas (reader) usage:
    from shared.crypto import cipher
    if "detection_enc" in telemetry:
        telemetry["detection"] = cipher.decrypt(telemetry["detection_enc"])
"""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

_KEY_ENV = "TELEMETRY_FERNET_KEY"


class FernetCipher:
    """
    Fernet symmetric cipher for dict payloads.

    When no key is configured the instance operates in passthrough mode:
    encrypt() returns the original dict unchanged and decrypt() returns
    whatever it receives — so callers need not branch on key presence.
    """

    def __init__(self) -> None:
        raw_key = os.getenv(_KEY_ENV, "").strip()
        self._fernet = None

        if raw_key:
            try:
                from cryptography.fernet import Fernet
                self._fernet = Fernet(raw_key.encode())
                logger.info("FernetCipher initialised — encryption ACTIVE.")
            except Exception as exc:
                logger.error(
                    "Invalid TELEMETRY_FERNET_KEY (%s). "
                    "Falling back to plaintext mode.",
                    exc,
                )
        else:
            logger.warning(
                "TELEMETRY_FERNET_KEY not set — "
                "detection block will be written in plaintext."
            )

    # ── Public API ─────────────────────────────────────────────────────────────

    @property
    def is_active(self) -> bool:
        """True when a valid key is loaded and encryption is enabled."""
        return self._fernet is not None

    def encrypt(self, data: dict) -> str | dict:
        """
        Serialise *data* to JSON and Fernet-encrypt it.

        Returns a URL-safe base64 token string when encryption is active,
        or the original *data* dict when in passthrough mode.
        """
        if self._fernet is None:
            return data   # passthrough — return dict unchanged

        raw   = json.dumps(data, separators=(",", ":")).encode("utf-8")
        token = self._fernet.encrypt(raw)
        return token.decode("utf-8")   # str — safe to store in JSON

    def decrypt(self, payload: str | dict) -> dict:
        """
        Fernet-decrypt *payload* and deserialise from JSON.

        Accepts either:
          - a Fernet token string (encrypted path), or
          - a plain dict (passthrough / key not configured).

        Returns the original dict in both cases.
        """
        if isinstance(payload, dict):
            return payload   # passthrough

        if self._fernet is None:
            # Token present but no key — we cannot decrypt; return sentinel
            logger.error(
                "Received encrypted detection_enc but TELEMETRY_FERNET_KEY "
                "is not configured. Cannot decrypt."
            )
            return {}

        raw  = self._fernet.decrypt(payload.encode("utf-8"))
        return json.loads(raw.decode("utf-8"))


# ── Module-level singleton — import this everywhere ────────────────────────────
cipher = FernetCipher()
