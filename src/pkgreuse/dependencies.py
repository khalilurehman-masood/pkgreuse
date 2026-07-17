from __future__ import annotations

import re
from email import policy
from email.parser import BytesParser
from importlib import metadata
from pathlib import Path
from typing import Any

from pkgreuse.domain.names import normalize_package_name

_REQUIREMENT_NAME_PATTERN = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def read_distribution_requirements(
    metadata_path: str | Path,
) -> list[str]:
    """Read Requires-Dist entries from one distribution METADATA file."""
    path = Path(metadata_path)

    if not path.is_file():
        raise RuntimeError(f"Distribution METADATA file does not exist: {path}")

    try:
        with path.open("rb") as metadata_file:
            parsed_metadata = BytesParser(policy=policy.default).parse(metadata_file)
    except OSError as exc:
        raise RuntimeError(f"Could not read distribution METADATA: {exc}") from exc

    return [
        str(requirement).strip()
        for requirement in parsed_metadata.get_all(
            "Requires-Dist",
            [],
        )
        if str(requirement).strip()
    ]


def requirement_name(requirement: str) -> str | None:
    """Extract and normalize the distribution name from a requirement."""
    match = _REQUIREMENT_NAME_PATTERN.match(requirement)

    if match is None:
        return None

    return normalize_package_name(match.group(1))


def is_optional_extra(requirement: str) -> bool:
    """
    Detect dependencies enabled only through package extras.

    Examples:
        PySocks !=1.5.7,>=1.5.6 ; extra == "socks"
        chardet<6,>=3.0.2 ; extra == "use-chardet-on-py3"
    """
    marker = requirement.partition(";")[2].casefold()

    return "extra ==" in marker or "extra !=" in marker


def installed_target_version(
    package_name: str,
) -> str | None:
    """Return the target environment's installed version."""
    try:
        return metadata.version(package_name)
    except metadata.PackageNotFoundError:
        return None


def analyze_dependencies(
    candidate: dict[str, Any],
    index_data: dict[str, Any],
) -> list[dict[str, Any]]:
    """Classify the dependencies of an indexed distribution."""
    requirements = read_distribution_requirements(candidate["metadata"])

    results: list[dict[str, Any]] = []

    for raw_requirement in requirements:
        normalized_name = requirement_name(raw_requirement)

        if normalized_name is None:
            results.append(
                {
                    "requirement": raw_requirement,
                    "name": None,
                    "optional": False,
                    "target_version": None,
                    "available_versions": [],
                    "status": "unparsed",
                }
            )
            continue

        optional = is_optional_extra(raw_requirement)
        target_version = installed_target_version(normalized_name)

        available_versions = sorted(
            index_data["packages"]
            .get(
                normalized_name,
                {},
            )
            .keys()
        )

        if optional:
            status = "optional"
        elif target_version is not None:
            status = "installed"
        elif available_versions:
            status = "reusable"
        else:
            status = "missing"

        results.append(
            {
                "requirement": raw_requirement,
                "name": normalized_name,
                "optional": optional,
                "target_version": target_version,
                "available_versions": available_versions,
                "status": status,
            }
        )

    return results
