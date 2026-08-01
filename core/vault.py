import os
from cryptography.fernet import Fernet
from core.config import settings

_fernet_instance = None
_default_test_key = Fernet.generate_key()

def get_fernet_instance() -> Fernet:
    global _fernet_instance
    if _fernet_instance is None:
        key_str = settings.encryption_key
        if not key_str:
            # Fallback to in-memory key for local development/testing
            key_bytes = _default_test_key
        else:
            key_bytes = key_str.encode("utf-8")
        _fernet_instance = Fernet(key_bytes)
    return _fernet_instance

def encrypt_token(payload: str) -> str:
    """Encrypt sensitive OAuth token payload using symmetric Fernet AES-128-CBC/HMAC-SHA256."""
    f = get_fernet_instance()
    return f.encrypt(payload.encode("utf-8")).decode("utf-8")

def decrypt_token(ciphertext: str) -> str:
    """Decrypt ciphertext token back to plaintext."""
    f = get_fernet_instance()
    return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")

def generate_key() -> str:
    """Helper to generate a new valid Fernet key."""
    return Fernet.generate_key().decode("utf-8")
