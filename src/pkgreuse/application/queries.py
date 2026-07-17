"""Read-only package lookup and planning application services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from packaging.requirements import Requirement
from packaging.version import InvalidVersion, Version

from pkgreuse.domain.names import normalize_package_name
from pkgreuse.domain.requirements import parse_package_query, parse_requirement
from pkgreuse.ports import IndexData, IndexRepository

Candidate = dict[str, Any]


@dataclass(frozen=True, slots=True)
class PackageLookup:
    """Indexed versions matching a package query."""

    package_name: str
    requested_version: str | None
    versions: dict[str, list[Candidate]]


@dataclass(frozen=True, slots=True)
class TransferPlanningResult:
    """Selected exact version and its filesystem transfer plan."""

    package_name: str
    version: str
    plan: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DependencyAnalysisResult:
    """Static dependency analysis for an indexed distribution."""

    package_name: str
    version: str
    donor: Candidate
    dependencies: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class ResolutionPlanningResult:
    """Complete local dependency-closure plan."""

    package_name: str
    version: str
    plan: dict[str, Any]


class LocalQueryService:
    """Coordinate index-backed read-only use cases."""

    def __init__(
        self,
        repository: IndexRepository,
        candidate_finder: Callable[
            [IndexData, str, str | None],
            dict[str, list[Candidate]],
        ],
        donor_selector: Callable[[list[Candidate]], Candidate],
        candidate_selector: Callable[
            [IndexData, Requirement, str | None],
            Candidate | None,
        ],
        transfer_planner: Callable[[str, str, list[Candidate]], dict[str, Any]],
        dependency_analyzer: Callable[
            [Candidate, IndexData],
            list[dict[str, Any]],
        ],
        resolution_planner: Callable[
            [str, str, Candidate, IndexData],
            dict[str, Any],
        ],
    ) -> None:
        self.repository = repository
        self.candidate_finder = candidate_finder
        self.donor_selector = donor_selector
        self.candidate_selector = candidate_selector
        self.transfer_planner = transfer_planner
        self.dependency_analyzer = dependency_analyzer
        self.resolution_planner = resolution_planner

    def lookup(self, package_query: str) -> PackageLookup:
        """Return matching indexed package candidates."""
        requirement = parse_requirement(package_query)
        package_name, requested_version = parse_package_query(package_query)
        index = self.repository.load()
        versions = self.candidate_finder(index, package_name, requested_version)
        if requested_version is None and requirement.specifier:
            filtered: dict[str, list[Candidate]] = {}
            for version, candidates in versions.items():
                try:
                    parsed = Version(version)
                except InvalidVersion:
                    continue
                if requirement.specifier.contains(parsed, prereleases=True):
                    filtered[version] = candidates
            versions = filtered
        return PackageLookup(package_name, requested_version, versions)

    def transfer_plan(
        self,
        package_query: str,
        require_exact: bool = False,
    ) -> TransferPlanningResult:
        """Select an unambiguous version and build its transfer plan."""
        requirement = parse_requirement(package_query)
        lookup = self.lookup(package_query)
        if not lookup.versions:
            raise ValueError(f"Package not found in the local index: {package_query}")
        if lookup.requested_version is None:
            if require_exact:
                raise ValueError(
                    "The first reuse implementation requires an exact package version."
                )
            candidate = self.candidate_selector(
                self.repository.load(), requirement, None
            )
            if candidate is None:
                raise ValueError(
                    f"No reusable local version satisfies {package_query}."
                )
            version = candidate["version"]
            candidates = [candidate]
        else:
            version = lookup.requested_version
            candidates = lookup.versions[version]
        plan = self.transfer_planner(
            lookup.package_name,
            version,
            candidates,
        )
        return TransferPlanningResult(lookup.package_name, version, plan)

    def dependencies(self, package_query: str) -> DependencyAnalysisResult:
        """Analyze declared dependencies for one exact indexed package."""
        requirement = parse_requirement(package_query)
        package_name = normalize_package_name(requirement.name)
        index = self.repository.load()
        donor = self.candidate_selector(index, requirement, None)
        if donor is None:
            raise ValueError(f"No reusable local version satisfies {package_query}.")
        version = donor["version"]
        dependencies = self.dependency_analyzer(donor, index)
        return DependencyAnalysisResult(package_name, version, donor, dependencies)

    def resolution_plan(self, package_query: str) -> ResolutionPlanningResult:
        """Build a complete local dependency-closure plan."""
        requirement = parse_requirement(package_query)
        package_name = normalize_package_name(requirement.name)
        index = self.repository.load()
        donor = self.candidate_selector(index, requirement, None)
        if donor is None:
            raise ValueError(f"No reusable local version satisfies {package_query}.")
        version = donor["version"]
        plan = self.resolution_planner(package_name, version, donor, index)
        return ResolutionPlanningResult(package_name, version, plan)
