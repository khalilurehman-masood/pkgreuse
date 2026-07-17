"""Atomic, lock-protected JSON index repository."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pkgreuse.domain.errors import (
    IndexCorruptError,
    IndexLockTimeoutError,
    IndexNotFoundError,
    UnsupportedIndexVersionError,
)


class JsonIndexRepository:
    """Store schema-v1 index data as target-local JSON."""

    def __init__(self, path: Path, lock_timeout_seconds: float = 10.0) -> None:
        self.path = path
        self.lock_timeout_seconds = lock_timeout_seconds

    def load(self) -> dict[str, Any]:
        """Load and validate index JSON."""
        return self._load_unlocked()

    def _load_unlocked(self) -> dict[str, Any]:
        """Load index JSON when the caller already owns any needed lock."""
        if not self.path.is_file():
            raise IndexNotFoundError(
                "Local index does not exist. Run 'pkgreuse init' first."
            )
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise IndexCorruptError(
                f"Local index contains invalid JSON: {self.path}"
            ) from exc
        except OSError as exc:
            raise IndexCorruptError(f"Could not read local index: {exc}") from exc

        if not isinstance(data, dict):
            raise IndexCorruptError("Local index root must be a JSON object.")
        if data.get("schema_version") != 1:
            raise UnsupportedIndexVersionError(
                "Unsupported index format. Run 'pkgreuse init' again."
            )
        if not isinstance(data.get("packages"), dict):
            raise IndexCorruptError(
                "Local index has no package inventory. Run 'pkgreuse init' again."
            )
        return data

    @contextmanager
    def _lock(self) -> Iterator[None]:
        lock_path = self.path.with_suffix(".lock")
        deadline = time.monotonic() + self.lock_timeout_seconds
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor: int | None = None
        while descriptor is None:
            try:
                descriptor = os.open(
                    lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
            except FileExistsError as exc:
                if time.monotonic() >= deadline:
                    raise IndexLockTimeoutError(
                        f"Timed out waiting for index lock: {lock_path}"
                    ) from exc
                time.sleep(0.05)
        try:
            yield
        finally:
            os.close(descriptor)
            lock_path.unlink(missing_ok=True)

    def _save_unlocked(self, index: dict[str, Any]) -> None:
        """Atomically replace index JSON while the caller holds the lock."""
        temporary_path = self.path.with_suffix(".json.tmp")
        try:
            with temporary_path.open("w", encoding="utf-8") as stream:
                json.dump(index, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.path)
        finally:
            temporary_path.unlink(missing_ok=True)

    def save(self, index: dict[str, Any]) -> None:
        """Atomically replace the index while holding a local write lock."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock():
            self._save_unlocked(index)

    def update(
        self,
        mutator: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        """Reload and mutate the latest index under one write lock."""
        with self._lock():
            latest = self._load_unlocked()
            updated = mutator(latest)
            self._save_unlocked(updated)
            return updated
