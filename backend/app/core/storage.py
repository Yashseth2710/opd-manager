"""Where uploaded files are kept.

Vercel Blob, in a private store: a file there cannot be fetched without the
store's token, so nobody reaches a patient's scan by guessing or leaking its
address. Every read comes through the API, which checks who is asking first.

With no token in development, files go to a folder on disk instead, so the
application and the browser suite run on a machine with no account. Anywhere
else an upload with nowhere to go is refused rather than lost.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

import httpx

from app.core.config import get_settings

logger = logging.getLogger("opd.storage")

_LOCAL = "local://"
# The version of the Blob API these requests are written against.
_API_VERSION = "12"
_TIMEOUT = httpx.Timeout(30.0, connect=5.0)


class StorageUnavailable(Exception):
    """The store refused, timed out, or is not configured."""


class Missing(Exception):
    """The store answered, and the file is not there."""


def _blob_headers() -> dict[str, str]:
    token = get_settings().blob_read_write_token
    return {"authorization": f"Bearer {token}", "x-api-version": _API_VERSION}


def _local_path(url: str) -> Path:
    root = get_settings().local_files_dir.resolve()
    path = (root / url.removeprefix(_LOCAL)).resolve()
    # Paths are generated, never typed, but a row edited by hand should still
    # not be able to read the rest of the disk.
    if not path.is_relative_to(root):
        raise Missing
    return path


async def put(pathname: str, content: bytes, content_type: str) -> str:
    """Stores the file and returns the address to read it back from. A random
    suffix is added, so two uploads never land on one address."""
    mode = get_settings().storage
    if mode == "none":
        raise StorageUnavailable("no store is configured")

    if mode == "local":
        stem, _, extension = pathname.rpartition(".")
        relative = f"{stem}-{uuid.uuid4().hex}.{extension}"
        path = _local_path(_LOCAL + relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return _LOCAL + relative

    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.put(
                f"{settings.blob_api_url}/",
                params={"pathname": pathname},
                content=content,
                headers={
                    **_blob_headers(),
                    "x-vercel-blob-access": "private",
                    "x-content-type": content_type,
                    "x-add-random-suffix": "1",
                },
            )
            response.raise_for_status()
            url = response.json()["url"]
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        logger.error("blob store refused an upload: %s", type(exc).__name__)
        raise StorageUnavailable from exc
    return str(url)


async def read(url: str) -> bytes:
    if url.startswith(_LOCAL):
        path = _local_path(url)
        if not path.is_file():
            raise Missing
        return path.read_bytes()

    if not get_settings().blob_read_write_token:
        raise StorageUnavailable("no store is configured")
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(
                url, headers={"authorization": _blob_headers()["authorization"]}
            )
    except httpx.HTTPError as exc:
        logger.error("blob store did not answer a read: %s", type(exc).__name__)
        raise StorageUnavailable from exc
    if response.status_code == 404:
        raise Missing
    if response.status_code != 200:
        logger.error("blob store refused a read: %s", response.status_code)
        raise StorageUnavailable
    return response.content


async def delete(url: str) -> None:
    """Deleting something already gone is not an error."""
    if url.startswith(_LOCAL):
        _local_path(url).unlink(missing_ok=True)
        return

    settings = get_settings()
    if not settings.blob_read_write_token:
        raise StorageUnavailable("no store is configured")
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                f"{settings.blob_api_url}/delete", json={"urls": [url]}, headers=_blob_headers()
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("blob store refused a delete: %s", type(exc).__name__)
        raise StorageUnavailable from exc
