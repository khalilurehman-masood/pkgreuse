"""Index initialization and target-refresh application services."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pkgreuse.domain.errors import ConfigurationError, IndexNotFoundError
from pkgreuse.ports import IndexData, IndexRepository

IndexBuilder = Callable[
    [list[Path], Path],
    tuple[Path, IndexData],
]
SitePackagesLocator = Callable[[Path], Path | None]
InventoryReader = Callable[
    [Path, Path],
    tuple[list[dict[str, Any]], list[dict[str, str]]],
]


def default_scan_roots() -> tuple[Path, ...]:
    """Return bounded project-neighbourhood roots for first-use discovery."""
    from pkgreuse.scanner import nearby_scan_roots

    return nearby_scan_roots(Path(sys.prefix).resolve())


def default_scan_root() -> Path:
    """Return the first discovery root for backward compatibility."""
    return default_scan_roots()[0]


@dataclass(frozen=True, slots=True)
class IndexInitializationResult:
    """Index data and whether it was created by this operation."""

    path: Path
    data: IndexData
    initialized: bool


class IndexInitializationService:
    """Load an index or initialize it exactly once when it is absent."""

    def __init__(
        self,
        repository: IndexRepository,
        builder: IndexBuilder,
        target_environment: Path,
        automatic_builder: IndexBuilder | None = None,
    ) -> None:
        self.repository = repository
        self.builder = builder
        self.target_environment = target_environment
        self.automatic_builder = automatic_builder

    def initialize(self, roots: Sequence[Path]) -> IndexInitializationResult:
        """Validate scan roots and build a fresh target-local index."""
        return self._initialize_with_builder(roots, self.builder)

    def initialize_default(self) -> IndexInitializationResult:
        """Build the bounded first-use index from default discovery roots."""
        return self._initialize_with_builder(
            default_scan_roots(),
            self.automatic_builder or self.builder,
        )

    def _initialize_with_builder(
        self,
        roots: Sequence[Path],
        builder: IndexBuilder,
    ) -> IndexInitializationResult:
        """Validate roots and invoke the selected index builder."""
        resolved_roots = [root.expanduser().resolve() for root in roots]
        invalid_roots = [root for root in resolved_roots if not root.is_dir()]
        if invalid_roots:
            invalid = ", ".join(str(root) for root in invalid_roots)
            raise ConfigurationError(
                f"Scan root does not exist or is not a directory: {invalid}"
            )
        path, data = builder(resolved_roots, self.target_environment)
        return IndexInitializationResult(path=path, data=data, initialized=True)

    def ensure(
        self,
        roots: Sequence[Path] | None = None,
        on_missing: Callable[[], None] | None = None,
    ) -> IndexInitializationResult:
        """Load the index, automatically creating only a missing index."""
        try:
            data = self.repository.load()
        except IndexNotFoundError:
            if on_missing is not None:
                on_missing()
            if roots is None:
                return self.initialize_default()
            return self.initialize(roots)
        return IndexInitializationResult(
            path=self.repository.path,
            data=data,
            initialized=False,
        )


def _same_path(first: str | Path, second: str | Path) -> bool:
    return os.path.normcase(os.path.realpath(first)) == os.path.normcase(
        os.path.realpath(second)
    )


class TargetIndexRefreshService:
    """Refresh only the active target environment in an existing index."""

    def __init__(
        self,
        repository: IndexRepository,
        target_environment: Path,
        site_packages_locator: SitePackagesLocator,
        inventory_reader: InventoryReader,
    ) -> None:
        self.repository = repository
        self.target_environment = target_environment.resolve()
        self.site_packages_locator = site_packages_locator
        self.inventory_reader = inventory_reader

    def refresh(self) -> IndexData:
        """Rescan target metadata and merge it into the latest index."""
        site_packages = self.site_packages_locator(self.target_environment)
        if site_packages is None:
            raise ConfigurationError(
                f"Target site-packages was not found: {self.target_environment}"
            )
        distributions, failures = self.inventory_reader(
            self.target_environment,
            site_packages,
        )

        def merge(index: IndexData) -> IndexData:
            packages = index["packages"]
            for versions in packages.values():
                for version, candidates in list(versions.items()):
                    versions[version] = [
                        candidate
                        for candidate in candidates
                        if not _same_path(
                            candidate["environment"],
                            self.target_environment,
                        )
                    ]
                    if not versions[version]:
                        del versions[version]

            for distribution in distributions:
                normalized_name = distribution.pop("normalized_name")
                version = distribution["version"]
                packages.setdefault(normalized_name, {}).setdefault(
                    version,
                    [],
                ).append(distribution)

            environments = index.setdefault("environments", [])
            target_record: dict[str, Any] | None = None
            for environment in environments:
                if _same_path(environment["path"], self.target_environment):
                    target_record = environment
                    break
            if target_record is None:
                target_record = {
                    "path": str(self.target_environment),
                    "site_packages": str(site_packages.resolve()),
                    "python": index.get("target", {}).get("python", {}),
                }
                environments.append(target_record)
            target_record["package_count"] = len(distributions)
            index["updated_at"] = datetime.now().astimezone().isoformat()
            index["target_metadata_failures"] = failures
            return index

        return self.repository.update(merge)
