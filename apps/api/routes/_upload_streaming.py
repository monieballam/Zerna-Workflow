"""Helpers for streaming uploaded files to disk without buffering them in RAM."""

from pathlib import Path

from fastapi import UploadFile

DEFAULT_UPLOAD_CHUNK_SIZE = 8 * 1024 * 1024


async def stream_upload_to_path(
    upload_file: UploadFile,
    destination: str | Path,
    *,
    chunk_size: int = DEFAULT_UPLOAD_CHUNK_SIZE,
) -> int:
    """Persist an ``UploadFile`` to disk in chunks and return bytes written."""

    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)

    total_bytes = 0
    with target.open("wb") as handle:
        while True:
            chunk = await upload_file.read(chunk_size)
            if not chunk:
                break
            handle.write(chunk)
            total_bytes += len(chunk)

    return total_bytes
