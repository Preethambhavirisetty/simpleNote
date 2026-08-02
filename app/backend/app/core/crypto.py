"""Application-layer encryption for note fields (AES-256-GCM).

Values are stored as a self-describing token string:

    enc:v<key_id>:<base64url(nonce || ciphertext_and_tag)>

so plaintext and ciphertext rows can coexist during rollout (detected by the ``enc:``
prefix) and the key version is recorded for rotation. Each token carries a random 96-bit
nonce and is authenticated with the field label as additional data (AAD), so ciphertext
cannot be silently swapped between different fields.

Keys come from config (env / AWS Secrets Manager), never from the repo:

    NOTES_ENCRYPTION_KEY           base64 of 32 random bytes — the active key
    NOTES_ENCRYPTION_KEY_ID        id/version tag for the active key (default "1")
    NOTES_ENCRYPTION_KEYS_RETIRED  optional JSON {id: base64key} kept for decrypting
                                   data written before a key rotation
"""

from __future__ import annotations

import base64
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_PREFIX = "enc:"
_NONCE_LEN = 12

# Marker key used to store an encrypted JSON document inside a JSONB column.
_JSON_ENC_KEY = "__enc__"


class EncryptionError(RuntimeError):
    """Raised for misconfiguration or failed decryption of a note field."""


_cached_keyring: tuple[str, dict[str, bytes]] | None = None


def _decode_key(b64: str) -> bytes:
    try:
        raw = base64.b64decode(b64, validate=True)
    except Exception as exc:  # noqa: BLE001 — surfaced as a clear config error
        raise EncryptionError("Encryption key is not valid base64.") from exc
    if len(raw) != 32:
        raise EncryptionError("Encryption key must decode to 32 bytes (AES-256).")
    return raw


def _load_keyring() -> tuple[str, dict[str, bytes]]:
    from app.core.config import (
        NOTES_ENCRYPTION_KEY,
        NOTES_ENCRYPTION_KEY_ID,
        NOTES_ENCRYPTION_KEYS_RETIRED,
    )

    if not NOTES_ENCRYPTION_KEY:
        raise EncryptionError(
            "notes.encryption is enabled but NOTES_ENCRYPTION_KEY is not set."
        )

    keys: dict[str, bytes] = {}
    if NOTES_ENCRYPTION_KEYS_RETIRED:
        try:
            retired = json.loads(NOTES_ENCRYPTION_KEYS_RETIRED)
        except json.JSONDecodeError as exc:
            raise EncryptionError("NOTES_ENCRYPTION_KEYS_RETIRED must be valid JSON.") from exc
        for key_id, b64 in retired.items():
            keys[str(key_id)] = _decode_key(b64)

    keys[str(NOTES_ENCRYPTION_KEY_ID)] = _decode_key(NOTES_ENCRYPTION_KEY)
    return str(NOTES_ENCRYPTION_KEY_ID), keys


def _keyring() -> tuple[str, dict[str, bytes]]:
    global _cached_keyring
    if _cached_keyring is None:
        _cached_keyring = _load_keyring()
    return _cached_keyring


def reset_keyring() -> None:
    """Drop the cached keyring so config/env changes are picked up (tests, rotation)."""
    global _cached_keyring
    _cached_keyring = None


def _aad(field: str) -> bytes:
    return field.encode("utf-8")


def is_encrypted(value: object) -> bool:
    return isinstance(value, str) and value.startswith(_PREFIX)


def encrypt(plaintext: str, field: str) -> str:
    active_id, keys = _keyring()
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = AESGCM(keys[active_id]).encrypt(nonce, plaintext.encode("utf-8"), _aad(field))
    token = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")
    return f"{_PREFIX}v{active_id}:{token}"


def decrypt(token: str, field: str) -> str:
    if not is_encrypted(token):
        return token  # legacy plaintext row — return as-is
    try:
        _, version, body = token.split(":", 2)
        key_id = version[1:]  # strip the leading 'v'
    except ValueError as exc:
        raise EncryptionError("Malformed encrypted note field.") from exc

    _active, keys = _keyring()
    key = keys.get(key_id)
    if key is None:
        raise EncryptionError(f"No encryption key for version {key_id!r}.")
    try:
        raw = base64.urlsafe_b64decode(body)
        nonce, ciphertext = raw[:_NONCE_LEN], raw[_NONCE_LEN:]
        return AESGCM(key).decrypt(nonce, ciphertext, _aad(field)).decode("utf-8")
    except Exception as exc:  # noqa: BLE001 — includes InvalidTag on tampering/wrong key
        raise EncryptionError("Failed to decrypt note field.") from exc


# ── JSON documents stored in a JSONB column ─────────────────────────────────────

def is_encrypted_json(value: object) -> bool:
    return isinstance(value, dict) and _JSON_ENC_KEY in value


def encrypt_json(value: dict, field: str) -> dict:
    token = encrypt(json.dumps(value, separators=(",", ":")), field)
    return {_JSON_ENC_KEY: token}


def decrypt_json(value: object, field: str) -> object:
    if not is_encrypted_json(value):
        return value  # legacy plaintext document
    return json.loads(decrypt(value[_JSON_ENC_KEY], field))
