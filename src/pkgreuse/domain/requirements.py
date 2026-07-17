"""Direct-requirement parsing policy for the MVP."""

from __future__ import annotations

from packaging.requirements import InvalidRequirement, Requirement

from pkgreuse.domain.names import normalize_package_name


def parse_requirement(query: str) -> Requirement:
    """Parse one registry-backed requirement without contacting a registry."""
    query = query.strip()
    if not query:
        raise ValueError("Package requirement cannot be empty.")
    try:
        requirement = Requirement(query)
    except InvalidRequirement as exc:
        raise ValueError(f"Invalid package requirement: {query}: {exc}") from exc
    if requirement.url is not None:
        raise ValueError("Direct URL requirements are not supported for local reuse.")
    if requirement.extras:
        raise ValueError("Extras are not supported by the local resolver yet.")
    if requirement.marker is not None:
        raise ValueError("Markers are not supported on direct requirements yet.")
    return requirement


def parse_package_query(query: str) -> tuple[str, str | None]:
    """Parse a name and return its exact pin when one was requested."""
    requirement = parse_requirement(query)
    exact_version: str | None = None
    specifiers = list(requirement.specifier)
    if (
        len(specifiers) == 1
        and specifiers[0].operator == "=="
        and not specifiers[0].version.endswith(".*")
    ):
        exact_version = specifiers[0].version
    return normalize_package_name(requirement.name), exact_version
