# from __future__ import annotations

# import json
# import os
# import re
# from email import policy
# from email.parser import BytesParser
# from pathlib import Path
# from typing import Any


# def normalize_package_name(name: str) -> str:
#     """
#     Normalize a Python distribution name.

#     Examples:
#         typing_extensions -> typing-extensions
#         Typing.Extensions -> typing-extensions
#     """
#     return re.sub(r"[-_.]+", "-", name).lower()


# def read_optional_text(path: Path) -> str | None:
#     """Read a small optional text file."""
#     if not path.is_file():
#         return None

#     try:
#         value = path.read_text(
#             encoding="utf-8",
#             errors="replace",
#         ).strip()
#     except OSError:
#         return None

#     return value or None


# def is_editable_distribution(dist_info: Path) -> bool:
#     """Detect editable installations using direct_url.json."""
#     direct_url_path = dist_info / "direct_url.json"

#     if not direct_url_path.is_file():
#         return False

#     try:
#         data = json.loads(
#             direct_url_path.read_text(
#                 encoding="utf-8",
#                 errors="replace",
#             )
#         )
#     except (OSError, json.JSONDecodeError):
#         return False

#     directory_information = data.get("dir_info", {})

#     return bool(directory_information.get("editable", False))


# def read_top_level_modules(dist_info: Path) -> list[str]:
#     """Read top-level import names when top_level.txt is available."""
#     top_level_path = dist_info / "top_level.txt"

#     if not top_level_path.is_file():
#         return []

#     try:
#         lines = top_level_path.read_text(
#             encoding="utf-8",
#             errors="replace",
#         ).splitlines()
#     except OSError:
#         return []

#     return sorted(
#         {
#             line.strip()
#             for line in lines
#             if line.strip()
#         }
#     )


# def inspect_distribution(
#     dist_info: Path,
#     environment_path: Path,
#     site_packages: Path,
# ) -> dict[str, Any]:
#     """Read one installed distribution's lightweight metadata."""
#     metadata_path = dist_info / "METADATA"

#     if not metadata_path.is_file():
#         raise RuntimeError("METADATA file is missing.")

#     try:
#         with metadata_path.open("rb") as metadata_file:
#             metadata = BytesParser(
#                 policy=policy.default
#             ).parse(metadata_file)
#     except OSError as exc:
#         raise RuntimeError(f"Could not read METADATA: {exc}") from exc

#     package_name = metadata.get("Name")
#     package_version = metadata.get("Version")

#     if not package_name:
#         raise RuntimeError("Package name is missing from METADATA.")

#     if not package_version:
#         raise RuntimeError("Package version is missing from METADATA.")

#     package_name = str(package_name).strip()
#     package_version = str(package_version).strip()

#     requires_dist = [
#         str(requirement).strip()
#         for requirement in metadata.get_all("Requires-Dist", [])
#         if str(requirement).strip()
#     ]

#     record_path = dist_info / "RECORD"
#     installer = read_optional_text(dist_info / "INSTALLER")

#     return {
#         "name": package_name,
#         "normalized_name": normalize_package_name(package_name),
#         "version": package_version,
#         "environment": str(environment_path),
#         "site_packages": str(site_packages),
#         "dist_info": str(dist_info),
#         "metadata": str(metadata_path),
#         "record": str(record_path) if record_path.is_file() else None,
#         "installer": installer,
#         "editable": is_editable_distribution(dist_info),
#         "requires_dist": requires_dist,
#         "top_level_modules": read_top_level_modules(dist_info),
#     }


# def scan_environment_packages(
#     environment_path: Path,
#     site_packages: Path,
# ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
#     """Scan immediate .dist-info directories in one environment."""
#     distributions: list[dict[str, Any]] = []
#     failures: list[dict[str, str]] = []

#     try:
#         with os.scandir(site_packages) as entries:
#             dist_info_directories = sorted(
#                 (
#                     Path(entry.path)
#                     for entry in entries
#                     if entry.name.casefold().endswith(".dist-info")
#                     and entry.is_dir(follow_symlinks=False)
#                 ),
#                 key=lambda path: path.name.casefold(),
#             )
#     except OSError as exc:
#         return [], [
#             {
#                 "environment": str(environment_path),
#                 "path": str(site_packages),
#                 "reason": f"Could not scan site-packages: {exc}",
#             }
#         ]

#     for dist_info in dist_info_directories:
#         try:
#             distribution = inspect_distribution(
#                 dist_info=dist_info,
#                 environment_path=environment_path,
#                 site_packages=site_packages,
#             )
#         except RuntimeError as exc:
#             failures.append(
#                 {
#                     "environment": str(environment_path),
#                     "path": str(dist_info),
#                     "reason": str(exc),
#                 }
#             )
#             continue

#         distributions.append(distribution)

#     return distributions, failures


# def build_package_index(
#     environments: list[dict[str, Any]],
# ) -> tuple[
#     dict[str, dict[str, list[dict[str, Any]]]],
#     int,
#     list[dict[str, str]],
# ]:
#     """
#     Build a package-first lookup index.

#     Structure:
#         package name
#             -> version
#                 -> donor candidates
#     """
#     packages: dict[
#         str,
#         dict[str, list[dict[str, Any]]],
#     ] = {}

#     failures: list[dict[str, str]] = []
#     distributions_indexed = 0
#     total_environments = len(environments)

#     for position, environment in enumerate(environments, start=1):
#         environment_path = Path(environment["path"])
#         site_packages = Path(environment["site_packages"])

#         distributions, environment_failures = scan_environment_packages(
#             environment_path=environment_path,
#             site_packages=site_packages,
#         )

#         environment["package_count"] = len(distributions)
#         failures.extend(environment_failures)

#         for distribution in distributions:
#             normalized_name = distribution.pop("normalized_name")
#             version = distribution["version"]

#             version_index = packages.setdefault(
#                 normalized_name,
#                 {},
#             )

#             candidates = version_index.setdefault(
#                 version,
#                 [],
#             )

#             candidates.append(distribution)
#             distributions_indexed += 1

#         current_path = str(environment_path)

#         if len(current_path) > 58:
#             current_path = "..." + current_path[-55:]

#         print(
#             f"\rIndexing packages: "
#             f"{position}/{total_environments} environments | "
#             f"{distributions_indexed:,} distributions | "
#             f"{current_path:<58}",
#             end="",
#             flush=True,
#         )

#     if total_environments:
#         print("\r" + (" " * 130) + "\r", end="")

#     return packages, distributions_indexed, failures

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pkgreuse.domain.names import normalize_package_name


def read_name_and_version(metadata_path: Path) -> tuple[str, str]:
    """
    Read only Name and Version from a distribution METADATA file.

    This avoids the significantly slower full email-message parser.
    """
    package_name: str | None = None
    package_version: str | None = None

    try:
        with metadata_path.open(
            "r",
            encoding="utf-8",
            errors="replace",
        ) as metadata_file:
            for line in metadata_file:
                # Package metadata headers end at the first blank line.
                if not line.strip():
                    break

                if package_name is None and line.startswith("Name:"):
                    package_name = line[5:].strip()

                elif package_version is None and line.startswith("Version:"):
                    package_version = line[8:].strip()

                if package_name and package_version:
                    break

    except OSError as exc:
        raise RuntimeError(f"Could not read METADATA: {exc}") from exc

    if not package_name:
        raise RuntimeError("Package name is missing from METADATA.")

    if not package_version:
        raise RuntimeError("Package version is missing from METADATA.")

    return package_name, package_version


def is_editable_distribution(dist_info: Path) -> bool:
    """
    Detect editable installations.

    direct_url.json is only opened when it exists.
    """
    direct_url_path = dist_info / "direct_url.json"

    if not direct_url_path.is_file():
        return False

    try:
        with direct_url_path.open(
            "r",
            encoding="utf-8",
        ) as direct_url_file:
            data = json.load(direct_url_file)
    except (OSError, json.JSONDecodeError):
        return False

    return bool(data.get("dir_info", {}).get("editable", False))


def inspect_distribution(
    dist_info: Path,
    environment_path: Path,
    site_packages: Path,
) -> dict[str, Any]:
    """Read the minimum information needed for package lookup."""
    metadata_path = dist_info / "METADATA"

    if not metadata_path.is_file():
        raise RuntimeError("METADATA file is missing.")

    package_name, package_version = read_name_and_version(metadata_path)

    record_path = dist_info / "RECORD"

    return {
        "name": package_name,
        "normalized_name": normalize_package_name(package_name),
        "version": package_version,
        "environment": str(environment_path),
        "site_packages": str(site_packages),
        "dist_info": str(dist_info),
        "metadata": str(metadata_path),
        "record": (str(record_path) if record_path.is_file() else None),
        "editable": is_editable_distribution(dist_info),
    }


def scan_environment_packages(
    environment_path: Path,
    site_packages: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Scan immediate .dist-info directories in one environment."""
    distributions: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    try:
        with os.scandir(site_packages) as entries:
            for entry in entries:
                try:
                    is_dist_info = entry.name.casefold().endswith(
                        ".dist-info"
                    ) and entry.is_dir(follow_symlinks=False)
                except OSError:
                    continue

                if not is_dist_info:
                    continue

                dist_info = Path(entry.path)

                try:
                    distribution = inspect_distribution(
                        dist_info=dist_info,
                        environment_path=environment_path,
                        site_packages=site_packages,
                    )
                except RuntimeError as exc:
                    failures.append(
                        {
                            "environment": str(environment_path),
                            "path": str(dist_info),
                            "reason": str(exc),
                        }
                    )
                    continue

                distributions.append(distribution)

    except OSError as exc:
        failures.append(
            {
                "environment": str(environment_path),
                "path": str(site_packages),
                "reason": f"Could not scan site-packages: {exc}",
            }
        )

    return distributions, failures


def build_package_index(
    environments: list[dict[str, Any]],
) -> tuple[
    dict[str, dict[str, list[dict[str, Any]]]],
    int,
    list[dict[str, str]],
]:
    """
    Build a package-first lookup index.

    Structure:
        normalized package name
            -> version
                -> donor candidates
    """
    packages: dict[
        str,
        dict[str, list[dict[str, Any]]],
    ] = {}

    failures: list[dict[str, str]] = []
    distributions_indexed = 0
    total_environments = len(environments)

    for position, environment in enumerate(
        environments,
        start=1,
    ):
        environment_path = Path(environment["path"])
        site_packages = Path(environment["site_packages"])

        distributions, environment_failures = scan_environment_packages(
            environment_path=environment_path,
            site_packages=site_packages,
        )

        environment["package_count"] = len(distributions)
        failures.extend(environment_failures)

        for distribution in distributions:
            normalized_name = distribution.pop("normalized_name")
            version = distribution["version"]

            versions = packages.setdefault(
                normalized_name,
                {},
            )

            candidates = versions.setdefault(
                version,
                [],
            )

            candidates.append(distribution)
            distributions_indexed += 1

        current_path = str(environment_path)

        if len(current_path) > 58:
            current_path = "..." + current_path[-55:]

        print(
            f"\rIndexing packages: "
            f"{position}/{total_environments} environments | "
            f"{distributions_indexed:,} distributions | "
            f"{current_path:<58}",
            end="",
            flush=True,
        )

    if total_environments:
        print("\r" + (" " * 130) + "\r", end="")

    return packages, distributions_indexed, failures
