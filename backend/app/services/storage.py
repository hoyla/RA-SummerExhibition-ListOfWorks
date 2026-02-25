"""
Pluggable file-storage backend.

Set the ``STORAGE_BACKEND`` env var to select an implementation:

* ``local`` (default) – reads/writes to ``UPLOAD_DIR`` on the local filesystem.
* ``s3`` – reads/writes to an S3 bucket (requires ``boto3``, ``S3_BUCKET``,
  and optionally ``AWS_REGION``).

Usage::

    from backend.app.services.storage import storage

    key = storage.save("myfile.xlsx", raw_bytes)
    data = storage.load(key)
    storage.delete(key)
    items = storage.list_keys()
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO


class StorageBackend(ABC):
    """Abstract base for file storage."""

    @abstractmethod
    def save(self, key: str, data: bytes | BinaryIO) -> str:
        """Persist *data* under *key*.  Returns the key."""
        ...

    @abstractmethod
    def load(self, key: str) -> bytes:
        """Return the raw bytes stored under *key*."""
        ...

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete *key*.  Returns True if something was removed."""
        ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def list_keys(self) -> list[str]:
        """Return all keys currently stored (excluding placeholders like .gitkeep)."""
        ...

    @abstractmethod
    def size(self, key: str) -> int:
        """Return the size in bytes of the object at *key*."""
        ...

    def stats(self) -> dict:
        """Return aggregate stats (count, total size)."""
        keys = self.list_keys()
        total_bytes = 0
        for k in keys:
            try:
                total_bytes += self.size(k)
            except Exception:
                pass
        return {
            "uploads_count": len(keys),
            "uploads_size_mb": round(total_bytes / (1024**2), 2),
        }


# ---------------------------------------------------------------------------
# Local filesystem implementation
# ---------------------------------------------------------------------------


class LocalStorage(StorageBackend):
    """Store files on the local filesystem under a directory."""

    def __init__(self, base_dir: str) -> None:
        self._base = Path(base_dir)

    def _path(self, key: str) -> Path:
        # Prevent path traversal: only use the basename of the key
        safe = Path(key).name
        return self._base / safe

    def save(self, key: str, data: bytes | BinaryIO) -> str:
        self._base.mkdir(parents=True, exist_ok=True)
        dest = self._path(key)
        if isinstance(data, (bytes, bytearray)):
            dest.write_bytes(data)
        else:
            with open(dest, "wb") as f:
                # Stream from file-like object
                while chunk := data.read(64 * 1024):
                    f.write(chunk)
        return key

    def load(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> bool:
        p = self._path(key)
        if p.is_file():
            p.unlink()
            return True
        return False

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def list_keys(self) -> list[str]:
        if not self._base.is_dir():
            return []
        return [
            entry.name
            for entry in self._base.iterdir()
            if entry.is_file() and entry.name != ".gitkeep"
        ]

    def size(self, key: str) -> int:
        return self._path(key).stat().st_size

    @property
    def base_dir(self) -> Path:
        """Expose the base directory for callers that need the resolved path
        (e.g. ``load_workbook(filename=...)`` which needs a filesystem path)."""
        return self._base

    def full_path(self, key: str) -> str:
        """Return the absolute filesystem path for *key*.

        This is specific to ``LocalStorage`` — callers that need a real path
        (such as ``openpyxl.load_workbook``) should use this.  On S3 the
        equivalent would be a temporary download.
        """
        return str(self._path(key))


# ---------------------------------------------------------------------------
# S3 implementation (lazy import — boto3 only needed when selected)
# ---------------------------------------------------------------------------


class S3Storage(StorageBackend):
    """Store files in an Amazon S3 bucket."""

    def __init__(self, bucket: str, region: str | None = None) -> None:
        import boto3

        self._bucket_name = bucket
        self._s3 = boto3.client("s3", region_name=region)

    def save(self, key: str, data: bytes | BinaryIO) -> str:
        if isinstance(data, (bytes, bytearray)):
            self._s3.put_object(Bucket=self._bucket_name, Key=key, Body=data)
        else:
            self._s3.upload_fileobj(data, self._bucket_name, key)
        return key

    def load(self, key: str) -> bytes:
        resp = self._s3.get_object(Bucket=self._bucket_name, Key=key)
        return resp["Body"].read()

    def delete(self, key: str) -> bool:
        if not self.exists(key):
            return False
        self._s3.delete_object(Bucket=self._bucket_name, Key=key)
        return True

    def exists(self, key: str) -> bool:
        try:
            self._s3.head_object(Bucket=self._bucket_name, Key=key)
            return True
        except self._s3.exceptions.ClientError:
            return False

    def list_keys(self) -> list[str]:
        keys: list[str] = []
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket_name):
            for obj in page.get("Contents", []):
                if obj["Key"] != ".gitkeep":
                    keys.append(obj["Key"])
        return keys

    def size(self, key: str) -> int:
        resp = self._s3.head_object(Bucket=self._bucket_name, Key=key)
        return resp["ContentLength"]

    def full_path(self, key: str) -> str:
        """Download to a temp file and return its path.

        openpyxl needs a real filesystem path, so we download on demand.
        The caller is responsible for cleanup if desired, though the temp
        directory is typically cleaned automatically.
        """
        import tempfile
        import time
        import glob

        # Download the object into a uniquely-named temp file so callers
        # that need a real filesystem path (eg. openpyxl) can use it.
        data = self.load(key)
        tmp = tempfile.NamedTemporaryFile(
            delete=False, prefix="catalogue_s3_", suffix=".xlsx"
        )
        try:
            tmp.write(data)
            tmp.flush()
            tmp_path = tmp.name
        finally:
            try:
                tmp.close()
            except Exception:
                pass

        # Opportunistic cleanup: remove any old temp files we previously
        # created with the same prefix to avoid accumulating stale files on
        # local disks. This is conservative and only removes files older
        # than an hour.
        try:
            tmpdir = tempfile.gettempdir()
            pattern = f"{tmpdir}/catalogue_s3_*.xlsx"
            max_age = 60 * 60  # 1 hour
            now = time.time()
            for path in glob.glob(pattern):
                try:
                    if now - os.path.getmtime(path) > max_age:
                        os.remove(path)
                except FileNotFoundError:
                    pass
                except Exception:
                    # Ignore failures; cleanup is best-effort
                    pass
        except Exception:
            pass

        return tmp_path


# ---------------------------------------------------------------------------
# Factory — initialised once at import time from env vars
# ---------------------------------------------------------------------------


def _build_storage() -> StorageBackend:
    from backend.app.config import UPLOAD_DIR

    backend = os.getenv("STORAGE_BACKEND", "local").lower()

    if backend == "s3":
        bucket = os.getenv("S3_BUCKET", "")
        if not bucket:
            raise RuntimeError("STORAGE_BACKEND=s3 requires S3_BUCKET env var")
        region = os.getenv("AWS_REGION")
        return S3Storage(bucket=bucket, region=region)

    if backend == "local":
        return LocalStorage(base_dir=UPLOAD_DIR)

    raise RuntimeError(
        f"Unknown STORAGE_BACKEND: {backend!r}  (expected 'local' or 's3')"
    )


storage: StorageBackend = _build_storage()
