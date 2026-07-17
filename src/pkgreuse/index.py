from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, cast

from pkgreuse.domain.errors import IndexError
from pkgreuse.domain.names import normalize_package_name
from pkgreuse.domain.requirements import parse_package_query
from pkgreuse.infrastructure.index_repository import JsonIndexRepository

__all__ = ["normalize_package_name", "parse_package_query"]


def local_index_path() -> Path:
    """Return the local index belonging to the active environment."""
    return Path(sys.prefix).resolve() / ".pkgreuse" / "index.json"


def load_local_index() -> dict[str, Any]:
    """Load and validate the local JSON index."""
    try:
        return JsonIndexRepository(local_index_path()).load()
    except IndexError as exc:
        # Compatibility boundary for the characterized CLI.
        raise RuntimeError(str(exc)) from exc


def find_package_candidates(
    index_data: dict[str, Any],
    package_name: str,
    requested_version: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Find indexed donor candidates for a package."""
    package_versions = index_data["packages"].get(
        package_name,
        {},
    )

    if requested_version is not None:
        candidates = package_versions.get(
            requested_version,
            [],
        )

        if not candidates:
            return {}

        return {
            requested_version: candidates,
        }

    return cast(dict[str, list[dict[str, Any]]], package_versions)


def is_target_environment(environment_path: str) -> bool:
    """Return True when a candidate is the active target environment."""
    candidate = os.path.normcase(os.path.realpath(environment_path))
    target = os.path.normcase(os.path.realpath(sys.prefix))

    return candidate == target
