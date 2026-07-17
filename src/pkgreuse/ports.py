"""Application ports implemented by infrastructure adapters."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

from pkgreuse.domain.models import (
    DistributionCandidate,
    TransferPlan,
    ValidationResult,
)

IndexData = dict[str, Any]
ScanProgressCallback = Callable[[int, int, Path], None]
TransferProgressCallback = Callable[[int, int], None]


class IndexRepository(Protocol):
    """Persistence for the target-local package index."""

    path: Path

    def load(self) -> IndexData: ...

    def save(self, index: IndexData) -> None: ...

    def update(
        self,
        mutator: Callable[[IndexData], IndexData],
    ) -> IndexData: ...


class EnvironmentScanner(Protocol):
    """Discovery of compatible virtual environments."""

    def discover(
        self,
        roots: Sequence[Path],
        progress: ScanProgressCallback | None = None,
    ) -> tuple[list[Path], int]: ...


class MetadataReader(Protocol):
    """Static installed-distribution metadata reader."""

    def read(self, dist_info: Path) -> DistributionCandidate: ...


class LocalResolver(Protocol):
    """Local dependency resolver."""

    def resolve(self, requirement: str, index: IndexData) -> Any: ...


class TransferStrategy(Protocol):
    """Executor for a validated transfer plan."""

    def execute(
        self,
        plan: TransferPlan,
        progress: TransferProgressCallback | None = None,
    ) -> Any: ...


class TransactionManager(Protocol):
    """Transaction lifecycle for target filesystem changes."""

    def rollback(self) -> None: ...

    def commit(self) -> None: ...


class Validator(Protocol):
    """Post-transfer installation validator."""

    def validate(self, expected: dict[str, str]) -> ValidationResult: ...


class InstallerBackend(Protocol):
    """A real installer used when local reuse is unavailable."""

    name: str

    def command(
        self,
        target_python: Path,
        arguments: Sequence[str],
    ) -> list[str]: ...

    def install(
        self,
        target_python: Path,
        arguments: Sequence[str],
    ) -> int: ...


class ProgressReporter(Protocol):
    """Renderer-independent progress sink."""

    def update(self, completed: int, total: int, message: str = "") -> None: ...
