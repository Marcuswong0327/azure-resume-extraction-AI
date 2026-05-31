from __future__ import annotations

import hashlib
import mimetypes
import os
from datetime import datetime, timezone
from typing import Optional, Tuple

try:
    from azure.storage.blob import (
        BlobServiceClient,
        ContentSettings,
    )
    from azure.core.exceptions import ResourceExistsError

    _AZURE_AVAILABLE = True
except ImportError: 
    _AZURE_AVAILABLE = False


def _parse_connection_string(connection_string: str) -> dict:
    parts = {}
    for segment in connection_string.split(";"):
        segment = segment.strip()
        if not segment or "=" not in segment:
            continue
        key, value = segment.split("=", 1)
        parts[key.strip()] = value.strip()
    return parts


class BlobUploader:
    #Uploads resumes to Azure container and mints read SAS URLs.

    def __init__(self, connection_string: str, container_name: str):
        if not _AZURE_AVAILABLE:
            raise RuntimeError(
                "azure-storage-blob is not installed; cannot create BlobUploader."
            )

        conn_parts = _parse_connection_string(connection_string)
        self._account_name = conn_parts.get("AccountName")
        self._account_key = conn_parts.get("AccountKey")
        if not self._account_name or not self._account_key:
            raise ValueError("Connection string must contain AccountName and AccountKey ")

        self._container_name = container_name
        self._service_client = BlobServiceClient.from_connection_string(
            connection_string
        )
        self._container_client = self._service_client.get_container_client(
            container_name
        )
        # self._ensure_container()

    @classmethod
    def from_secrets(cls, secrets) -> Optional["BlobUploader"]:

        if not _AZURE_AVAILABLE:
            return None

        try:
            connection_string = secrets.get("AZURE_STORAGE_CONNECTION_STRING")
            container_name = secrets.get("AZURE_BLOB_CONTAINER", "resume-archive")
        except Exception:
            connection_string = None
            container_name = "resume-archive"

        if not connection_string:
            return None

        try:
            return cls(connection_string, container_name)
        except Exception:
            return None

    # def _ensure_container(self) -> None:
       
    #     try:
    #         self._container_client.create_container()
    #     except Exception:
    #         pass

    def _blob_path(self, data: bytes, filename: str, country: str) -> str:
        ext = os.path.splitext(filename)[1].lower()
        digest = hashlib.sha256(data).hexdigest() # generate unique hash 
        return f"{country}/{digest}{ext}"

    def upsert(
        self, data: bytes, filename: str, country: str
    ) -> Tuple[str, str]:
    
        blob_path = self._blob_path(data, filename, country)
        blob_client = self._container_client.get_blob_client(blob_path)

        try:
            if blob_client.exists():
                return blob_client.url, blob_path
        except Exception:
            pass

        content_type = (
            mimetypes.guess_type(filename)[0] or "application/octet-stream"
        )
        metadata = {
            "original_filename": filename,
            "upload_timestamp": datetime.now(timezone.utc).isoformat(),
        }

        try:
            blob_client.upload_blob(
                data,
                overwrite=False,
                content_settings=ContentSettings(content_type=content_type),
                metadata=metadata,
            )
        except ResourceExistsError:
            pass

        return blob_client.url, blob_path
