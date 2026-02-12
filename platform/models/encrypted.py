"""Shared EncryptedString column type — imported by user.py and credential.py."""

from __future__ import annotations

import os

from cryptography.fernet import Fernet
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

_fernet_key = os.environ.get("FIELD_ENCRYPTION_KEY", "")
_fernet = Fernet(_fernet_key.encode()) if _fernet_key else None


class EncryptedString(TypeDecorator):
    """Transparently encrypts/decrypts string values using Fernet."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value and _fernet:
            return _fernet.encrypt(value.encode()).decode()
        return value

    def process_result_value(self, value, dialect):
        if value and _fernet:
            try:
                return _fernet.decrypt(value.encode()).decode()
            except Exception:
                return value
        return value
