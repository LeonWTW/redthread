"""Local-volume MediaStore (v1 default).

Files live under a private root inside the Docker volume and are served ONLY
through authenticated Flask routes — never a public static directory. All
lookups resolve strictly inside the root; path traversal raises ValueError.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .base import MediaStore

_ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


class LocalMediaStore(MediaStore):
    def __init__(self, root: str) -> None:
        self._root = Path(root).resolve()

    def save(self, file_bytes: bytes, suggested_name: str) -> str:
        extension = Path(suggested_name).suffix.lstrip(".").lower()
        if extension not in _ALLOWED_EXTENSIONS:
            raise ValueError(f"file extension not allowed: {extension!r}")
        now = datetime.now(timezone.utc)
        relative = Path(f"{now:%Y}") / f"{now:%m}" / f"{uuid4().hex}.{extension}"
        destination = self._root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(file_bytes)
        return str(relative)

    def _resolve(self, relative_path: str) -> Path:
        candidate = (self._root / relative_path).resolve()
        if candidate != self._root and self._root not in candidate.parents:
            raise ValueError(f"path escapes media root: {relative_path!r}")
        return candidate

    def open(self, relative_path: str) -> bytes:
        return self._resolve(relative_path).read_bytes()

    def exists(self, relative_path: str) -> bool:
        return self._resolve(relative_path).is_file()

    def delete(self, relative_path: str) -> None:
        self._resolve(relative_path).unlink(missing_ok=True)
