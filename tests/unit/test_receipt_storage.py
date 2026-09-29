from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.fernet import Fernet

from nexus.domain.errors import InvalidInput
from nexus.domain.receipts import check_file
from nexus.infra.storage.s3 import S3ReceiptStore
from nexus.settings import Settings


def store(path_style: bool = False) -> S3ReceiptStore:
    return S3ReceiptStore(
        bucket="nexus-receipts",
        endpoint="https://storage.example.com",
        region="auto",
        access_key_id="AKIDTEST",
        secret_access_key="not-a-real-secret",
        path_style=path_style,
    )


def test_download_links_are_signed_and_expire() -> None:
    url = urlparse(
        store().download_url("receipts/u/r", filename="receipt-r.jpg", expires=timedelta(minutes=5))
    )
    assert url.hostname == "nexus-receipts.storage.example.com"
    assert url.path == "/receipts/u/r"
    query = parse_qs(url.query)
    assert query["X-Amz-Expires"] == ["300"]
    assert "X-Amz-Signature" in query
    assert query["response-content-disposition"] == ['inline; filename="receipt-r.jpg"']


def test_path_style_buckets() -> None:
    url = urlparse(store(path_style=True).download_url("k", filename="f", expires=timedelta(1)))
    assert (url.hostname, url.path) == ("storage.example.com", "/nexus-receipts/k")


def test_file_types() -> None:
    assert check_file(b"x", "image/jpg") == "image/jpeg"
    assert check_file(b"x", "application/pdf; charset=binary") == "application/pdf"
    with pytest.raises(InvalidInput):
        check_file(b"x", "image/svg+xml")


def settings(**storage: Any) -> Settings:
    return Settings(_env_file=None, database_url="postgresql://u:p@h/db", **storage)


def test_storage_is_all_or_nothing() -> None:
    assert not settings().storage_enabled
    with pytest.raises(ValueError, match="STORAGE_ENDPOINT"):
        settings(storage_bucket="b", storage_access_key_id="k", storage_secret_access_key="s")
    full = settings(
        storage_bucket="b",
        storage_endpoint="https://e",
        storage_access_key_id="k",
        storage_secret_access_key="s",
    )
    assert full.storage_enabled


def test_connecting_gmail_needs_an_encryption_key() -> None:
    google = {"google_client_id": "cid", "google_client_secret": "s"}
    with pytest.raises(ValueError, match="TOKEN_ENCRYPTION_KEY"):
        settings(**google)
    with pytest.raises(ValueError, match="Fernet"):
        settings(**google, token_encryption_key="not-a-key")
    with pytest.raises(ValueError, match="go together"):
        settings(google_client_id="cid")
    key = Fernet.generate_key().decode()
    assert settings(**google, token_encryption_key=f"{key}, {Fernet.generate_key().decode()}")
