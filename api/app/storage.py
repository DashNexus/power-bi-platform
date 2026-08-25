"""Object-storage abstraction over `STORAGE_URI` (fsspec).

All file I/O goes through `get_filesystem()`. This module and `secrets.py` are the
only places permitted to import a cloud SDK; everything else uses the interface, so
switching between S3, Azure, GCS, and local disk is a config change.
"""

from __future__ import annotations

# Architecture rule: NEVER import boto3, azure-storage-blob, or
# google-cloud-storage outside this file. All file I/O must go through
# get_filesystem() so the storage backend remains swappable.
import fsspec

from app.config import settings


def get_filesystem() -> fsspec.AbstractFileSystem:
    """Return the configured fsspec filesystem based on STORAGE_URI scheme.

    Inspects settings.storage_uri to select the appropriate backend:
    - s3:// → S3FileSystem (s3fs) — also works with MinIO via S3_ENDPOINT_URL
    - az:// → AzureBlobFileSystem (adlfs)
    - gcs:// → GCSFileSystem (gcsfs)
    - file:// → local filesystem

    Returns:
        An fsspec AbstractFileSystem instance for the configured backend.
    """
    uri = settings.storage_uri

    if uri.startswith("s3://"):
        import s3fs  # noqa: PLC0415
        return s3fs.S3FileSystem(
            key=settings.aws_access_key_id or None,
            secret=settings.aws_secret_access_key or None,
            endpoint_url=settings.s3_endpoint_url or None,
        )
    elif uri.startswith("az://"):
        import adlfs  # noqa: PLC0415
        return adlfs.AzureBlobFileSystem()
    elif uri.startswith("gcs://"):
        import gcsfs  # noqa: PLC0415
        return gcsfs.GCSFileSystem(project=settings.google_project_id)
    else:
        return fsspec.filesystem("file")


def get_storage_path(path: str) -> str:
    """Prepend the configured storage URI prefix to a relative path.

    Args:
        path: Relative path within the storage backend.

    Returns:
        Fully qualified storage path.
    """
    base = settings.storage_uri.rstrip("/")
    return f"{base}/{path.lstrip('/')}"
