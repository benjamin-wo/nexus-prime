"""Encryption for stored secrets (mailbox refresh tokens).

TOKEN_ENCRYPTION_KEY holds one or more Fernet keys, comma separated. The first
encrypts; all of them decrypt, so a key can be rotated without losing access.
"""

from cryptography.fernet import Fernet, InvalidToken, MultiFernet


class CipherError(ValueError):
    pass


class FernetCipher:
    def __init__(self, keys: str) -> None:
        parts = [k.strip() for k in keys.split(",") if k.strip()]
        if not parts:
            raise CipherError("TOKEN_ENCRYPTION_KEY is empty")
        try:
            self._fernet = MultiFernet([Fernet(k.encode()) for k in parts])
        except ValueError as exc:
            raise CipherError("TOKEN_ENCRYPTION_KEY must be Fernet keys") from exc

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode())

    def decrypt(self, ciphertext: bytes) -> str:
        try:
            return self._fernet.decrypt(ciphertext).decode()
        except InvalidToken as exc:
            raise CipherError(
                "a stored secret can't be decrypted with the configured keys"
            ) from exc
