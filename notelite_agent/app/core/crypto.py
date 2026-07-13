"""Note field decryption for the agent (mirrors the backend's app/core/crypto.py).

The backend encrypts note title/description/content_text at rest (AES-256-GCM). The agent
reads note content directly from Postgres in its self-healing ingestion paths
(reconciliation, authoritative re-read), so it must be able to decrypt those fields with
the same key. ``decrypt`` is a no-op for legacy plaintext, so it is safe to call
unconditionally whether or not encryption is enabled.
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_PREFIX = "enc:"
_NONCE_LEN = 12


class EncryptionError(RuntimeError):
    """Raised for misconfiguration or failed decryption of a note field."""


_cached_keyring: dict[str, bytes] | None = None


def _decode_key(b64: str) -> bytes:
    try:
        raw = base64.b64decode(b64, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise EncryptionError("Encryption key is not valid base64.") from exc
    if len(raw) != 32:
        raise EncryptionError("Encryption key must decode to 32 bytes (AES-256).")
    return raw


def _keyring() -> dict[str, bytes]:
    global _cached_keyring
    if _cached_keyring is not None:
        return _cached_keyring

    import json

    from app.core.config import (
        NOTES_ENCRYPTION_KEY,
        NOTES_ENCRYPTION_KEY_ID,
        NOTES_ENCRYPTION_KEYS_RETIRED,
    )

    if not NOTES_ENCRYPTION_KEY:
        raise EncryptionError(
            "An encrypted note field was read but NOTES_ENCRYPTION_KEY is not set. "
            "Set the same key as the backend when notes.encryption is enabled."
        )
    keys: dict[str, bytes] = {}
    if NOTES_ENCRYPTION_KEYS_RETIRED:
        for key_id, b64 in json.loads(NOTES_ENCRYPTION_KEYS_RETIRED).items():
            keys[str(key_id)] = _decode_key(b64)
    keys[str(NOTES_ENCRYPTION_KEY_ID)] = _decode_key(NOTES_ENCRYPTION_KEY)
    _cached_keyring = keys
    return keys


def reset_keyring() -> None:
    global _cached_keyring
    _cached_keyring = None


def is_encrypted(value: object) -> bool:
    return isinstance(value, str) and value.startswith(_PREFIX)


def decrypt(token: str | None, field: str) -> str | None:
    if token is None or not is_encrypted(token):
        return token  # legacy plaintext — return as-is
    try:
        _, version, body = token.split(":", 2)
        key_id = version[1:]
    except ValueError as exc:
        raise EncryptionError("Malformed encrypted note field.") from exc

    key = _keyring().get(key_id)
    if key is None:
        raise EncryptionError(f"No encryption key for version {key_id!r}.")
    try:
        raw = base64.urlsafe_b64decode(body)
        nonce, ciphertext = raw[:_NONCE_LEN], raw[_NONCE_LEN:]
        return AESGCM(key).decrypt(nonce, ciphertext, field.encode("utf-8")).decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        raise EncryptionError("Failed to decrypt note field.") from exc
