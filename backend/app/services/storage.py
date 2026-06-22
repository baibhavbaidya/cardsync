"""Cloudflare R2 (S3-compatible) for card images and voice notes."""

import asyncio
import os

import boto3

_BUCKET = os.environ.get("R2_BUCKET")
_PUBLIC_URL = os.environ.get("R2_PUBLIC_URL", "").rstrip("/")


def _client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


async def save(key: str, data: bytes, content_type: str | None = None) -> None:
    """Upload bytes to R2. boto3 is sync so offload to a thread."""
    kwargs: dict = {"Bucket": _BUCKET, "Key": key, "Body": data}
    if content_type:
        kwargs["ContentType"] = content_type
    await asyncio.to_thread(lambda: _client().put_object(**kwargs))


def get_bytes(key: str) -> bytes:
    """Download an object from R2."""
    response = _client().get_object(Bucket=_BUCKET, Key=key)
    return response["Body"].read()


def public_url(key: str) -> str:
    """Return the public URL for an object (assumes the bucket has public access)."""
    return f"{_PUBLIC_URL}/{key}"
