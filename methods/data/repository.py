"""Repository pattern for data access.

Abstracts storage operations (read, write, list, delete) behind a
consistent interface so that callers are decoupled from the concrete
storage backend (local filesystem, S3, database, etc.).
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod


class Repository(ABC):
    """Abstract storage interface.

    All keys are opaque strings (e.g. ``"datasets/abc123.h5ad"``).
    Data is always raw ``bytes``.
    """

    @abstractmethod
    def read(self, key: str) -> bytes:
        """Read data associated with *key*.

        Raises:
            KeyError: If *key* does not exist in the store.
        """

    @abstractmethod
    def write(self, key: str, data: bytes) -> None:
        """Write *data* under *key*, overwriting any previous value."""

    @abstractmethod
    def list(self, prefix: str = "") -> list[str]:
        """Return all keys that start with *prefix*."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove *key* from the store.

        Raises:
            KeyError: If *key* does not exist.
        """


class InMemoryRepository(Repository):
    """Simple in-memory implementation for testing and lightweight use."""

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    def read(self, key: str) -> bytes:
        try:
            return self._store[key]
        except KeyError:
            raise KeyError(f"Key not found: {key}")

    def write(self, key: str, data: bytes) -> None:
        self._store[key] = data

    def list(self, prefix: str = "") -> list[str]:
        return sorted(k for k in self._store if k.startswith(prefix))

    def delete(self, key: str) -> None:
        try:
            del self._store[key]
        except KeyError:
            raise KeyError(f"Key not found: {key}")


class FilesystemRepository(Repository):
    """Repository backed by the local filesystem.

    Keys are mapped to paths relative to *root_dir*.
    """

    def __init__(self, root_dir: str) -> None:
        self._root = root_dir

    def _path(self, key: str) -> str:
        return os.path.join(self._root, key)

    def read(self, key: str) -> bytes:
        path = self._path(key)
        if not os.path.isfile(path):
            raise KeyError(f"Key not found: {key}")
        with open(path, "rb") as f:
            return f.read()

    def write(self, key: str, data: bytes) -> None:
        path = self._path(key)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)

    def list(self, prefix: str = "") -> list[str]:
        results: list[str] = []
        for dirpath, _, filenames in os.walk(self._root):
            for fname in filenames:
                full = os.path.join(dirpath, fname)
                key = os.path.relpath(full, self._root)
                if key.startswith(prefix):
                    results.append(key)
        return sorted(results)

    def delete(self, key: str) -> None:
        path = self._path(key)
        if not os.path.isfile(path):
            raise KeyError(f"Key not found: {key}")
        os.remove(path)
