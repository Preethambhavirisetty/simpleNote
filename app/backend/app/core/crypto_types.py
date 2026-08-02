"""SQLAlchemy column types that transparently encrypt note fields at rest.

Doing this at the column bind/result boundary (rather than in service code) means Python
always sees plaintext and the database always holds ciphertext when the feature is on —
safe across every code path (create, update, move, tag ops, agent dispatch) with no risk
of a stray commit writing plaintext back.

Writes encrypt only when the ``notes.encryption`` flag is on; reads always decrypt any
ciphertext. So plaintext (pre-flag) and ciphertext rows coexist during rollout, and
turning the flag off still reads previously-encrypted data.
"""

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import Text, TypeDecorator

from app.core import crypto
from app.core.feature_flags import is_enabled

_FLAG = "notes.encryption"


class EncryptedText(TypeDecorator):
    """TEXT column encrypted with AES-256-GCM when the encryption flag is on."""

    impl = Text
    cache_ok = True

    def __init__(self, field: str, *args, **kwargs):
        self.field = field  # AAD label binding ciphertext to this field
        super().__init__(*args, **kwargs)

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if is_enabled(_FLAG) and not crypto.is_encrypted(value):
            return crypto.encrypt(value, self.field)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return crypto.decrypt(value, self.field)  # no-op for legacy plaintext


class EncryptedJSONB(TypeDecorator):
    """JSONB column whose document is encrypted when the encryption flag is on."""

    impl = JSONB
    cache_ok = True

    def __init__(self, field: str, *args, **kwargs):
        self.field = field
        super().__init__(*args, **kwargs)

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if is_enabled(_FLAG) and not crypto.is_encrypted_json(value):
            return crypto.encrypt_json(value, self.field)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return crypto.decrypt_json(value, self.field)
