from __future__ import annotations

import os
import sys
from importlib import metadata
from pathlib import Path
from typing import Any, cast

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import InvalidVersion, Version

from pkgreuse.domain.names import normalize_package_name
from pkgreuse.transfer import create_transfer_plan


def same_environment(
    first: str | Path,
    second: str | Path,
) -> bool:
    """Return True when two environment paths identify the same folder."""
    return os.path.normcase(os.path.realpath(first)) == os.path.normcase(
        os.path.realpath(second)
    )


def target_installed_version(
    package_name: str,
) -> str | None:
    """Return the version installed in the active target environment."""
    try:
        return metadata.version(package_name)
    except metadata.PackageNotFoundError:
        return None


def requirement_applies(requirement: Requirement) -> bool:
    """
    Evaluate an environment marker for the current machine and Python.

    Package extras are not requested in the first version, so `extra`
    is evaluated as an empty string.
    """
    if requirement.marker is None:
        return True

    environment = cast(dict[str, str], default_environment())
    environment["extra"] = ""

    return requirement.marker.evaluate(environment)


def version_satisfies(
    version: str,
    requirement: Requirement,
) -> bool:
    """Check whether an installed version satisfies a requirement."""
    try:
        parsed_version = Version(version)
    except InvalidVersion:
        return False

    return requirement.specifier.contains(
        parsed_version,
        prereleases=True,
    )


def reusable_candidate(
    candidate: dict[str, Any],
) -> bool:
    """Return True when a candidate can potentially be transferred."""
    if candidate.get("editable"):
        return False

    record_path = candidate.get("record")

    if not record_path:
        return False

    return os.path.isfile(record_path)


def select_candidate(
    index_data: dict[str, Any],
    requirement: Requirement,
    preferred_environment: str | None,
) -> dict[str, Any] | None:
    """
    Select a locally indexed candidate.

    Select the maximum satisfying version across the complete local index.
    Donor affinity is only a tie-breaker for that same maximum version.
    """
    return select_candidate_for_requirements(
        index_data,
        [requirement],
        preferred_environment,
    )


def select_candidate_for_requirements(
    index_data: dict[str, Any],
    requirements: list[Requirement],
    preferred_environment: str | None,
) -> dict[str, Any] | None:
    """Select the local maximum satisfying every accumulated constraint."""
    if not requirements:
        return None
    normalized_name = normalize_package_name(requirements[0].name)

    indexed_versions = index_data["packages"].get(
        normalized_name,
        {},
    )

    matching_candidates: list[tuple[Version, dict[str, Any]]] = []

    for version_text, candidates in indexed_versions.items():
        if not all(
            version_satisfies(version_text, requirement) for requirement in requirements
        ):
            continue

        try:
            parsed_version = Version(version_text)
        except InvalidVersion:
            continue

        for candidate in candidates:
            if not reusable_candidate(candidate):
                continue

            if same_environment(candidate["environment"], sys.prefix):
                continue

            item = (parsed_version, candidate)
            matching_candidates.append(item)

    if not matching_candidates:
        return None

    maximum_version = max(version for version, _candidate in matching_candidates)
    maximum_candidates = [
        candidate
        for version, candidate in matching_candidates
        if version == maximum_version
    ]
    if preferred_environment is not None:
        for candidate in maximum_candidates:
            if same_environment(candidate["environment"], preferred_environment):
                return candidate
    target_drive = os.path.splitdrive(os.path.realpath(sys.prefix))[0].casefold()
    maximum_candidates.sort(
        key=lambda candidate: (
            0
            if os.path.splitdrive(candidate["environment"])[0].casefold()
            == target_drive
            else 1,
            len(candidate["environment"]),
            candidate["environment"],
        )
    )
    return maximum_candidates[0]


def read_requirements(
    metadata_path: str | Path,
) -> list[Requirement]:
    """Read applicable Requires-Dist entries from METADATA."""
    requirements: list[Requirement] = []

    try:
        distribution_metadata = metadata.PathDistribution(
            Path(metadata_path).parent
        ).metadata
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            f"Could not read package metadata: {metadata_path}: {exc}"
        ) from exc

    for raw_requirement in distribution_metadata.get_all(
        "Requires-Dist",
        [],
    ):
        try:
            requirement = Requirement(raw_requirement)
        except InvalidRequirement as exc:
            raise RuntimeError(
                f"Invalid dependency declaration: {raw_requirement}: {exc}"
            ) from exc

        if requirement_applies(requirement):
            requirements.append(requirement)

    return requirements


def build_installation_plan(
    root_name: str,
    root_version: str,
    root_candidate: dict[str, Any],
    index_data: dict[str, Any],
) -> dict[str, Any]:
    """
    Resolve the locally reusable dependency closure for one package.

    This is a local-only resolver. It does not contact PyPI.
    """
    root_name = normalize_package_name(root_name)

    selected: dict[str, dict[str, Any]] = {
        root_name: {
            "name": root_name,
            "version": root_version,
            "candidate": root_candidate,
            "required_by": None,
            "requirement": f"{root_name}=={root_version}",
        }
    }
    already_installed: dict[str, dict[str, str]] = {}
    missing: list[dict[str, str]] = []
    conflicts: list[dict[str, str]] = []
    constraints: dict[str, list[Requirement]] = {}
    constraint_edges: set[tuple[str, str, str]] = set()
    processed: dict[str, tuple[str, str]] = {}
    queue: list[str] = [root_name]

    while queue:
        package_name = queue.pop(0)
        item = selected.get(package_name)
        if item is None:
            continue
        candidate = item["candidate"]
        signature = (item["version"], candidate["environment"])
        if processed.get(package_name) == signature:
            continue
        processed[package_name] = signature

        requirements = read_requirements(candidate["metadata"])

        for requirement in requirements:
            dependency_name = normalize_package_name(requirement.name)
            edge = (dependency_name, str(requirement), package_name)
            if edge not in constraint_edges:
                constraint_edges.add(edge)
                constraints.setdefault(dependency_name, []).append(requirement)
            dependency_constraints = constraints[dependency_name]

            installed_version = target_installed_version(dependency_name)

            if installed_version is not None and all(
                version_satisfies(installed_version, constraint)
                for constraint in dependency_constraints
            ):
                already_installed[dependency_name] = {
                    "version": installed_version,
                    "requirement": ",".join(
                        str(constraint.specifier)
                        for constraint in dependency_constraints
                    ),
                    "required_by": package_name,
                }
                if dependency_name in selected:
                    del selected[dependency_name]
                    processed.pop(dependency_name, None)
                continue

            dependency_candidate = select_candidate_for_requirements(
                index_data,
                dependency_constraints,
                preferred_environment=candidate["environment"],
            )

            if dependency_candidate is None:
                selected.pop(dependency_name, None)
                processed.pop(dependency_name, None)
                failure = {
                    "package": dependency_name,
                    "requirement": ",".join(
                        str(constraint.specifier)
                        for constraint in dependency_constraints
                    ),
                    "required_by": package_name,
                }
                indexed_versions = index_data["packages"].get(dependency_name, {})
                if indexed_versions:
                    conflicts.append(
                        {
                            "package": dependency_name,
                            "selected": "none",
                            "requested": failure["requirement"],
                            "required_by": package_name,
                        }
                    )
                else:
                    missing.append(failure)
                continue

            existing_dependency = selected.get(dependency_name)
            if (
                existing_dependency is not None
                and existing_dependency["version"] == dependency_candidate["version"]
                and same_environment(
                    existing_dependency["candidate"]["environment"],
                    dependency_candidate["environment"],
                )
            ):
                continue
            selected[dependency_name] = {
                "name": dependency_name,
                "version": dependency_candidate["version"],
                "candidate": dependency_candidate,
                "required_by": package_name,
                "requirement": ",".join(
                    str(constraint) for constraint in dependency_constraints
                ),
            }
            queue.append(dependency_name)

    package_plans: list[dict[str, Any]] = []
    destination_owners: dict[str, str] = {}
    overlapping_files: list[dict[str, str]] = []

    total_files = 0
    total_size_bytes = 0

    for package_name, selection in selected.items():
        candidate = selection["candidate"]

        transfer_plan = create_transfer_plan(
            package_name=package_name,
            version=selection["version"],
            candidates=[candidate],
        )

        for file_entry in transfer_plan["planned_files"]:
            destination = os.path.normcase(file_entry["destination"])

            existing_owner = destination_owners.get(destination)

            if existing_owner is not None and existing_owner != package_name:
                overlapping_files.append(
                    {
                        "destination": destination,
                        "first_package": existing_owner,
                        "second_package": package_name,
                    }
                )
            else:
                destination_owners[destination] = package_name

        package_plans.append(
            {
                "name": package_name,
                "version": selection["version"],
                "required_by": selection["required_by"],
                "requirement": selection["requirement"],
                "donor": candidate["environment"],
                "transfer": transfer_plan,
            }
        )

        total_files += transfer_plan["file_count"]
        total_size_bytes += transfer_plan["total_size_bytes"]

    return {
        "root": {
            "name": root_name,
            "version": root_version,
        },
        "packages": package_plans,
        "already_installed": list(already_installed.values()),
        "missing": missing,
        "conflicts": conflicts,
        "overlapping_files": overlapping_files,
        "total_files": total_files,
        "total_size_bytes": total_size_bytes,
    }
