"""Installer fallback application service."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pkgreuse.ports import InstallerBackend


@dataclass(frozen=True, slots=True)
class BackendExecution:
    """Result of a real-installer invocation."""

    command: tuple[str, ...]
    return_code: int


class InstallerService:
    """Execute fallback installation through an InstallerBackend port."""

    def __init__(self, backend: InstallerBackend) -> None:
        self.backend = backend

    def install(
        self,
        target_python: Path,
        arguments: Sequence[str],
    ) -> BackendExecution:
        """Build and execute the backend command."""
        command = tuple(self.backend.command(target_python, arguments))
        return BackendExecution(
            command=command,
            return_code=self.backend.install(target_python, arguments),
        )
