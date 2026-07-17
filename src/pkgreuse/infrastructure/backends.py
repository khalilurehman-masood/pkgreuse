"""pip and uv installer backend adapters."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from pkgreuse.domain.errors import BackendError


class PipBackend:
    """Invoke pip through the target interpreter."""

    name = "pip"

    def command(
        self,
        target_python: Path,
        arguments: Sequence[str],
    ) -> list[str]:
        """Build a pip subprocess argument array."""
        return [str(target_python), "-m", "pip", *arguments]

    def install(
        self,
        target_python: Path,
        arguments: Sequence[str],
    ) -> int:
        """Run pip without shell interpretation."""
        return subprocess.run(
            self.command(target_python, arguments),
            check=False,
        ).returncode


class UvBackend:
    """Invoke uv while explicitly targeting the active interpreter."""

    name = "uv"

    def __init__(self, executable: str | None = None) -> None:
        self.executable = executable

    def _executable(self) -> str:
        executable = self.executable or shutil.which("uv")
        if executable is None:
            raise BackendError("uv was not found on PATH.")
        return executable

    def command(
        self,
        target_python: Path,
        arguments: Sequence[str],
    ) -> list[str]:
        """Build a uv subprocess argument array."""
        return [
            self._executable(),
            "pip",
            *arguments,
            "--python",
            str(target_python),
        ]

    def install(
        self,
        target_python: Path,
        arguments: Sequence[str],
    ) -> int:
        """Run uv without shell interpretation."""
        return subprocess.run(
            self.command(target_python, arguments),
            check=False,
        ).returncode


def backend_for(name: str) -> PipBackend | UvBackend:
    """Return the requested installer adapter."""
    if name == "pip":
        return PipBackend()
    if name == "uv":
        return UvBackend()
    raise BackendError(f"Unsupported backend: {name}")
