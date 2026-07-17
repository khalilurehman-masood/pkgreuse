"""Typed domain values used across PKGReuse layers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class TransferMode(str, Enum):
    """Supported transfer strategies."""

    AUTO = "auto"
    COPY = "copy"


class TransferKind(str, Enum):
    """Safety classification for an installed file."""

    PACKAGE_CONTENT = "package-content"
    DISTRIBUTION_METADATA = "distribution-metadata"
    PTH = "pth"
    LAUNCHER = "launcher"
    ENVIRONMENT = "environment"


class ValidationMode(str, Enum):
    """Supported validation levels."""

    FAST = "fast"
    STANDARD = "standard"
    STRICT = "strict"


@dataclass(frozen=True, slots=True)
class PythonIdentity:
    """Strict interpreter compatibility identity."""

    implementation: str
    version: str
    cache_tag: str | None
    architecture: str
    platform: str
    base_prefix: Path
    soabi: str | None

    def fingerprint(self) -> str:
        """Return a stable, non-secret identity fingerprint."""
        value = "\0".join(
            (
                self.implementation,
                self.version,
                self.cache_tag or "",
                self.architecture,
                self.platform,
                str(self.base_prefix),
                self.soabi or "",
            )
        )
        return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class EnvironmentRecord:
    """An inspected Python virtual environment."""

    path: Path
    python: Path
    site_packages: Path
    identity: PythonIdentity
    package_count: int = 0


@dataclass(frozen=True, slots=True)
class DistributionRecord:
    """Static installed-distribution metadata."""

    name: str
    normalized_name: str
    version: str
    environment: Path
    site_packages: Path
    dist_info: Path
    metadata: Path
    record: Path | None
    editable: bool = False


@dataclass(frozen=True, slots=True)
class DistributionCandidate:
    """A distribution considered for local reuse."""

    distribution: DistributionRecord
    stale: bool = False


@dataclass(frozen=True, slots=True)
class RequirementRequest:
    """A normalized direct requirement."""

    name: str
    version: str


@dataclass(frozen=True, slots=True)
class DependencyEdge:
    """A dependency relationship in a local resolution."""

    requirement: str
    required_by: str


@dataclass(frozen=True, slots=True)
class TransferEntry:
    """One validated source-to-target file operation."""

    record_path: str
    source: Path
    destination: Path
    size_bytes: int
    kind: TransferKind
    link_eligible: bool


@dataclass(frozen=True, slots=True)
class TransferPlan:
    """An immutable per-distribution transfer plan."""

    package: str
    version: str
    donor: Path
    target_environment: Path
    entries: tuple[TransferEntry, ...]


@dataclass(frozen=True, slots=True)
class PackageInstallPlan:
    """A selected distribution and its transfer plan."""

    name: str
    version: str
    required_by: str | None
    transfer: TransferPlan


@dataclass(frozen=True, slots=True)
class InstallationPlan:
    """A complete local dependency-closure installation."""

    root: RequirementRequest
    packages: tuple[PackageInstallPlan, ...]


@dataclass(frozen=True, slots=True)
class TransactionManifest:
    """Filesystem objects created by a transaction."""

    created_files: tuple[Path, ...]
    created_directories: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Result of post-transfer validation."""

    successful: bool
    messages: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BackendInvocation:
    """A concrete installer command."""

    backend: str
    arguments: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IndexSummary:
    """High-level index statistics."""

    environments: int
    distributions: int
    unique_packages: int
