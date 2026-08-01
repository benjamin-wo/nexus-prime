import pytest
from core.vault import encrypt_token, decrypt_token, generate_key

def test_fernet_encryption_and_decryption():
    secret_payload = "1//0g_oauth2_refresh_token_secret_12345"
    ciphertext = encrypt_token(secret_payload)

    assert ciphertext != secret_payload
    assert len(ciphertext) > len(secret_payload)

    plaintext = decrypt_token(ciphertext)
    assert plaintext == secret_payload

def test_generate_key():
    key = generate_key()
    assert isinstance(key, str)
    assert len(key) == 44  # Base64 encoded 32-byte Fernet key
