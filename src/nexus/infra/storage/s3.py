"""The receipt archive in a private S3-compatible bucket (a Railway bucket in prod).

Objects are never public. Downloads go through presigned links that expire in
minutes, created only after the app has checked who is asking.
"""

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


class S3ReceiptStore:
    def __init__(
        self,
        *,
        bucket: str,
        endpoint: str,
        region: str,
        access_key_id: str,
        secret_access_key: str,
        path_style: bool = False,
    ) -> None:
        self._bucket = bucket
        self._client: S3Client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path" if path_style else "virtual"},
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )

    async def delete(self, key: str) -> None:
        """Deleting a missing key succeeds, so a retried purge is harmless."""
        await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)

    def download_url(self, key: str, *, filename: str, expires: timedelta) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self._bucket,
                "Key": key,
                "ResponseContentDisposition": f'inline; filename="{filename}"',
            },
            ExpiresIn=int(expires.total_seconds()),
        )
