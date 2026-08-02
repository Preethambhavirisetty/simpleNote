"""Tests for note field encryption (crypto + Encrypted* column types) and PII helpers."""
import base64
import os

import pytest

from app.core import crypto, pii


@pytest.fixture
def enc_key(monkeypatch):
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setattr("app.core.config.NOTES_ENCRYPTION_KEY", key, raising=False)
    monkeypatch.setattr("app.core.config.NOTES_ENCRYPTION_KEY_ID", "1", raising=False)
    monkeypatch.setattr("app.core.config.NOTES_ENCRYPTION_KEYS_RETIRED", "", raising=False)
    crypto.reset_keyring()
    yield key
    crypto.reset_keyring()


class TestNoteCrypto:
    def test_round_trip(self, enc_key):
        token = crypto.encrypt("secret note", "note.title")
        assert crypto.is_encrypted(token) and token.startswith("enc:v1:")
        assert crypto.decrypt(token, "note.title") == "secret note"

    def test_aad_field_binding(self, enc_key):
        token = crypto.encrypt("secret", "note.title")
        with pytest.raises(crypto.EncryptionError):
            crypto.decrypt(token, "note.content_text")

    def test_tampered_ciphertext_rejected(self, enc_key):
        token = crypto.encrypt("secret", "note.title")
        bad = token[:-2] + ("AA" if token[-2:] != "AA" else "BB")
        with pytest.raises(crypto.EncryptionError):
            crypto.decrypt(bad, "note.title")

    def test_legacy_plaintext_passthrough(self, enc_key):
        assert not crypto.is_encrypted("legacy plaintext")
        assert crypto.decrypt("legacy plaintext", "note.title") == "legacy plaintext"

    def test_json_round_trip(self, enc_key):
        doc = {"type": "doc", "content": [{"type": "text", "text": "x"}]}
        enc = crypto.encrypt_json(doc, "note.content")
        assert crypto.is_encrypted_json(enc) and set(enc) == {"__enc__"}
        assert crypto.decrypt_json(enc, "note.content") == doc
        assert crypto.decrypt_json(doc, "note.content") == doc  # legacy passthrough

    def test_key_rotation(self, monkeypatch):
        k1 = base64.b64encode(os.urandom(32)).decode()
        k2 = base64.b64encode(os.urandom(32)).decode()
        # write under key 1
        monkeypatch.setattr("app.core.config.NOTES_ENCRYPTION_KEY", k1, raising=False)
        monkeypatch.setattr("app.core.config.NOTES_ENCRYPTION_KEY_ID", "1", raising=False)
        monkeypatch.setattr("app.core.config.NOTES_ENCRYPTION_KEYS_RETIRED", "", raising=False)
        crypto.reset_keyring()
        old_token = crypto.encrypt("older", "note.title")
        # rotate to key 2, retire key 1
        monkeypatch.setattr("app.core.config.NOTES_ENCRYPTION_KEY", k2, raising=False)
        monkeypatch.setattr("app.core.config.NOTES_ENCRYPTION_KEY_ID", "2", raising=False)
        monkeypatch.setattr("app.core.config.NOTES_ENCRYPTION_KEYS_RETIRED", f'{{"1": "{k1}"}}', raising=False)
        crypto.reset_keyring()
        assert crypto.decrypt(old_token, "note.title") == "older"  # old data still readable
        assert crypto.encrypt("newer", "note.title").startswith("enc:v2:")
        crypto.reset_keyring()

    def test_missing_key_raises(self, monkeypatch):
        monkeypatch.setattr("app.core.config.NOTES_ENCRYPTION_KEY", "", raising=False)
        crypto.reset_keyring()
        with pytest.raises(crypto.EncryptionError):
            crypto.encrypt("x", "note.title")
        crypto.reset_keyring()


class TestEncryptedColumnTypes:
    def test_encrypts_on_write_when_flag_on(self, enc_key, monkeypatch):
        from app.core import crypto_types

        monkeypatch.setattr(crypto_types, "is_enabled", lambda flag: True)
        col = crypto_types.EncryptedText("note.title")
        stored = col.process_bind_param("hello", None)
        assert crypto.is_encrypted(stored)
        assert col.process_result_value(stored, None) == "hello"

    def test_plaintext_on_write_when_flag_off_but_reads_old_ciphertext(self, enc_key, monkeypatch):
        from app.core import crypto_types

        monkeypatch.setattr(crypto_types, "is_enabled", lambda flag: False)
        col = crypto_types.EncryptedText("note.title")
        assert col.process_bind_param("hello", None) == "hello"  # not encrypted
        token = crypto.encrypt("old", "note.title")
        assert col.process_result_value(token, None) == "old"  # still decrypts

    def test_jsonb_column(self, enc_key, monkeypatch):
        from app.core import crypto_types

        monkeypatch.setattr(crypto_types, "is_enabled", lambda flag: True)
        col = crypto_types.EncryptedJSONB("note.content")
        doc = {"a": 1, "b": [2, 3]}
        stored = col.process_bind_param(doc, None)
        assert crypto.is_encrypted_json(stored)
        assert col.process_result_value(stored, None) == doc

    def test_none_passes_through(self, enc_key, monkeypatch):
        from app.core import crypto_types

        monkeypatch.setattr(crypto_types, "is_enabled", lambda flag: True)
        col = crypto_types.EncryptedText("note.description")
        assert col.process_bind_param(None, None) is None
        assert col.process_result_value(None, None) is None


class TestPII:
    def test_contains_pii(self):
        assert pii.contains_pii("mail me at a.b@example.com")
        assert pii.contains_pii("ssn 123-45-6789")
        assert not pii.contains_pii("a plain note about postgres")
        assert not pii.contains_pii(None)

    def test_redact(self):
        out = pii.redact("a.b@example.com and 123-45-6789")
        assert "a.b@example.com" not in out and "123-45-6789" not in out
        assert "[REDACTED_EMAIL]" in out and "[REDACTED_SSN]" in out
