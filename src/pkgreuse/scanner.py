from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import sysconfig
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from pkgreuse.infrastructure.index_repository import JsonIndexRepository
from pkgreuse.inventory import build_package_index

# Directories that are unlikely to contain useful project virtual environments.
# Do not add ".venv", "venv", or "env" here.
IGNORED_DIRECTORY_NAMES = {
    ".git",
    ".hg",
    ".pytest_cache",
    ".svn",
    "__pycache__",
    "node_modules",
    "$recycle.bin",
    "system volume information",
    "windows",
    "program files",
    "program files (x86)",
}

# System trees cannot contain ordinary user-created virtual environments and
# are prohibitively expensive or unsafe to traverse from a filesystem root.
# User-bearing roots such as /home, /root, /opt, /srv, /tmp, /mnt, /media and
# C:\\Users remain searchable.
POSIX_ROOT_IGNORED_DIRECTORY_NAMES = {
    "bin",
    "boot",
    "dev",
    "etc",
    "lib",
    "lib32",
    "lib64",
    "libx32",
    "lost+found",
    "proc",
    "run",
    "sbin",
    "sys",
    "usr",
    "var",
}

WINDOWS_ROOT_IGNORED_DIRECTORY_NAMES = {
    "$recycle.bin",
    "config.msi",
    "documents and settings",
    "msocache",
    "perflogs",
    "program files",
    "program files (x86)",
    "programdata",
    "recovery",
    "system volume information",
    "windows",
}


IDENTITY_SCRIPT = """
import json
import os
import struct
import sys
import sysconfig

print(json.dumps({
    "implementation": sys.implementation.name,
    "version": ".".join(map(str, sys.version_info[:3])),
    "cache_tag": sys.implementation.cache_tag,
    "architecture": f"{struct.calcsize('P') * 8}bit",
    "platform": sys.platform,
    "base_prefix": os.path.normcase(os.path.realpath(sys.base_prefix)),
    "soabi": sysconfig.get_config_var("SOABI"),
}))
"""


def current_python_identity() -> dict[str, Any]:
    """Return the Python identity of the environment running pkgreuse."""
    return {
        "implementation": sys.implementation.name,
        "version": ".".join(map(str, sys.version_info[:3])),
        "cache_tag": sys.implementation.cache_tag,
        "architecture": f"{struct.calcsize('P') * 8}bit",
        "platform": sys.platform,
        "base_prefix": os.path.normcase(os.path.realpath(sys.base_prefix)),
        "soabi": sysconfig.get_config_var("SOABI"),
    }


def environment_python(
    environment: Path,
    platform_name: str | None = None,
) -> Path:
    """Return the expected Python executable inside an environment."""
    if (platform_name or os.name) == "nt":
        return environment / "Scripts" / "python.exe"

    return environment / "bin" / "python"


def environment_site_packages(
    environment: Path,
    platform_name: str | None = None,
) -> Path | None:
    """Return the environment's site-packages directory when identifiable."""
    if (platform_name or os.name) == "nt":
        candidate = environment / "Lib" / "site-packages"
        return candidate if candidate.is_dir() else None

    for directory_name in ("lib", "lib64"):
        library_directory = environment / directory_name
        if not library_directory.is_dir():
            continue
        for candidate in sorted(library_directory.glob("*/site-packages")):
            if candidate.is_dir():
                return candidate

    return None


def is_virtual_environment_directory(
    path: Path,
    platform_name: str | None = None,
) -> bool:
    """Check whether a directory has the expected virtual-environment files."""
    return (
        (path / "pyvenv.cfg").is_file()
        and environment_python(path, platform_name).is_file()
        and environment_site_packages(path, platform_name) is not None
    )


def _current_filesystem_root() -> Path:
    anchor = Path.home().anchor
    return Path(anchor) if anchor else Path(os.path.abspath(os.sep))


def windows_fixed_drive_roots() -> tuple[Path, ...]:
    """Return mounted local fixed-drive roots without including network drives."""
    try:
        import ctypes

        win_dll = vars(ctypes).get("WinDLL")
        if win_dll is None:
            raise AttributeError("ctypes.WinDLL is unavailable")
        kernel32 = win_dll("kernel32", use_last_error=True)
        get_logical_drives = kernel32.GetLogicalDrives
        get_logical_drives.restype = ctypes.c_uint32
        get_drive_type = kernel32.GetDriveTypeW
        get_drive_type.argtypes = [ctypes.c_wchar_p]
        get_drive_type.restype = ctypes.c_uint32
        drive_mask = int(get_logical_drives())
        drive_fixed = 3
        roots = tuple(
            Path(f"{chr(ord('A') + index)}:\\")
            for index in range(26)
            if drive_mask & (1 << index)
            and int(get_drive_type(f"{chr(ord('A') + index)}:\\")) == drive_fixed
        )
    except (AttributeError, OSError, TypeError, ValueError):
        roots = ()
    return roots or (_current_filesystem_root(),)


def filesystem_roots(platform_name: str | None = None) -> tuple[Path, ...]:
    """Return safe local roots for automatic system-wide discovery."""
    if (platform_name or os.name) == "nt":
        return windows_fixed_drive_roots()
    return (Path("/"),)


def is_filesystem_root(path: Path) -> bool:
    """Return True when a path is the root of its filesystem namespace."""
    return path.parent == path


def should_skip_directory(parent: Path, name: str) -> bool:
    """Apply global and root-only pruning without hiding user project trees."""
    normalized_name = name.casefold()
    if normalized_name in IGNORED_DIRECTORY_NAMES:
        return True
    if os.name == "nt":
        parent_parts = tuple(part.casefold() for part in parent.parts)
        if parent_parts[-2:] == ("appdata", "local") and normalized_name == "temp":
            return True
    if not is_filesystem_root(parent):
        return False
    root_ignored = (
        WINDOWS_ROOT_IGNORED_DIRECTORY_NAMES
        if os.name == "nt"
        else POSIX_ROOT_IGNORED_DIRECTORY_NAMES
    )
    return normalized_name in root_ignored


def probe_python_identity(environment: Path) -> dict[str, Any]:
    """Execute an environment's Python and return its identity."""
    python_executable = environment_python(environment)

    creation_flags = 0

    if os.name == "nt":
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        completed = subprocess.run(
            [str(python_executable), "-c", IDENTITY_SCRIPT],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            creationflags=creation_flags,
        )
    except OSError as exc:
        raise RuntimeError(
            f"Could not start environment Python {python_executable}: {exc}"
        ) from exc

    if completed.returncode != 0:
        error = completed.stderr.strip() or "Python identity command failed."
        raise RuntimeError(error)

    try:
        return cast(dict[str, Any], json.loads(completed.stdout))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Environment returned invalid identity data: {completed.stdout!r}"
        ) from exc


def identities_match(
    target: dict[str, Any],
    donor: dict[str, Any],
) -> bool:
    """Return True only when the two environments use the same Python."""
    compared_fields = (
        "implementation",
        "version",
        "cache_tag",
        "architecture",
        "platform",
        "base_prefix",
        "soabi",
    )

    return all(target.get(field) == donor.get(field) for field in compared_fields)


def discover_environments(
    roots: list[Path],
    progress_callback: Callable[[int, int, Path], None] | None = None,
) -> tuple[list[Path], int]:
    """
    Search roots for virtual environments.

    Once an environment is found, its contents are not traversed.
    """
    environments: list[Path] = []
    seen_environments: set[str] = set()
    directories_checked = 0

    stack = list(reversed(roots))

    while stack:
        current_directory = stack.pop()
        directories_checked += 1

        try:
            if is_virtual_environment_directory(current_directory):
                normalized = os.path.normcase(os.path.realpath(current_directory))

                if normalized not in seen_environments:
                    seen_environments.add(normalized)
                    environments.append(current_directory.resolve())

                if progress_callback is not None:
                    progress_callback(
                        directories_checked,
                        len(environments),
                        current_directory,
                    )

                # Never traverse site-packages inside a discovered environment.
                continue

            with os.scandir(current_directory) as entries:
                child_directories: list[Path] = []

                for entry in entries:
                    try:
                        if not entry.is_dir(follow_symlinks=False):
                            continue
                    except OSError:
                        continue

                    if should_skip_directory(current_directory, entry.name):
                        continue

                    child_directories.append(Path(entry.path))

                # Reverse so traversal order remains natural with the stack.
                stack.extend(reversed(child_directories))

        except (PermissionError, FileNotFoundError, NotADirectoryError, OSError):
            # Inaccessible and transient directories are skipped.
            pass

        if progress_callback is not None:
            progress_callback(
                directories_checked,
                len(environments),
                current_directory,
            )

    return environments, directories_checked


class FileSystemEnvironmentScanner:
    """EnvironmentScanner adapter for standard Windows and POSIX venvs."""

    def discover(
        self,
        roots: list[Path],
        progress: Callable[[int, int, Path], None] | None = None,
    ) -> tuple[list[Path], int]:
        """Discover environments without descending into found venvs."""
        return discover_environments(roots, progress_callback=progress)


# Retain the original import name for callers using the 0.1 pre-release API.
WindowsEnvironmentScanner = FileSystemEnvironmentScanner


class ScanProgress:
    """Rate-limited terminal progress display."""

    def __init__(self) -> None:
        self._last_update = 0.0

    def update(
        self,
        directories_checked: int,
        environments_found: int,
        current_directory: Path,
    ) -> None:
        now = time.perf_counter()

        # Avoid slowing the scan by printing for every directory.
        if now - self._last_update < 0.08:
            return

        self._last_update = now

        current_text = str(current_directory)

        if len(current_text) > 55:
            current_text = "..." + current_text[-52:]

        message = (
            f"\rScanning... "
            f"{directories_checked:,} directories checked | "
            f"{environments_found} environments found | "
            f"{current_text:<55}"
        )

        print(message, end="", flush=True)

    @staticmethod
    def finish(
        directories_checked: int,
        environments_found: int,
    ) -> None:
        print(
            f"\rScanning complete: "
            f"{directories_checked:,} directories checked | "
            f"{environments_found} environments found" + (" " * 40)
        )


def save_index(index_path: Path, data: dict[str, Any]) -> None:
    """Write the JSON index using an atomic file replacement."""
    JsonIndexRepository(index_path).save(data)


def create_environment_index(
    roots: list[Path],
    target_environment: Path,
) -> tuple[Path, dict[str, Any]]:
    """Discover environments, filter by Python identity, and save the index."""
    started_at = time.perf_counter()
    target_identity = current_python_identity()

    progress = ScanProgress()

    discovered, directories_checked = FileSystemEnvironmentScanner().discover(
        roots,
        progress=progress.update,
    )

    progress.finish(
        directories_checked=directories_checked,
        environments_found=len(discovered),
    )

    compatible_environments: list[dict[str, Any]] = []
    skipped_environments: list[dict[str, str]] = []

    total = len(discovered)

    for position, environment in enumerate(discovered, start=1):
        print(
            f"\rChecking Python identity: {position}/{total} {str(environment):<70}",
            end="",
            flush=True,
        )

        try:
            identity = probe_python_identity(environment)
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            skipped_environments.append(
                {
                    "path": str(environment),
                    "reason": f"Could not inspect Python: {exc}",
                }
            )
            continue

        if not identities_match(target_identity, identity):
            skipped_environments.append(
                {
                    "path": str(environment),
                    "reason": (
                        f"Python mismatch: {identity.get('version', 'unknown')} "
                        f"{identity.get('soabi', 'unknown')}"
                    ),
                }
            )
            continue

        site_packages = environment_site_packages(environment)

        if site_packages is None:
            skipped_environments.append(
                {
                    "path": str(environment),
                    "reason": "site-packages was not found.",
                }
            )
            continue

        compatible_environments.append(
            {
                "path": str(environment),
                "python": identity,
                "site_packages": str(site_packages.resolve()),
            }
        )

    if total:
        print("\r" + (" " * 120) + "\r", end="")

    print("Indexing installed package metadata...")

    package_index_started_at = time.perf_counter()

    packages, distributions_indexed, package_failures = build_package_index(
        compatible_environments
    )

    package_index_seconds = time.perf_counter() - package_index_started_at

    elapsed_seconds = time.perf_counter() - started_at

    index_path = target_environment / ".pkgreuse" / "index.json"

    index_data: dict[str, Any] = {
        "schema_version": 1,
        "created_at": datetime.now().astimezone().isoformat(),
        "target": {
            "environment": str(target_environment),
            "python": target_identity,
        },
        "scan_roots": [str(root) for root in roots],
        "scan": {
            "elapsed_seconds": round(elapsed_seconds, 4),
            "package_index_seconds": round(package_index_seconds, 4),
            "directories_checked": directories_checked,
            "environments_found": len(discovered),
            "compatible_environments": len(compatible_environments),
            "skipped_environments": len(skipped_environments),
            "distributions_indexed": distributions_indexed,
            "unique_package_names": len(packages),
            "package_metadata_failures": len(package_failures),
        },
        "environments": compatible_environments,
        "packages": packages,
        "skipped": skipped_environments,
        "package_metadata_failures": package_failures,
    }

    save_index(index_path, index_data)

    return index_path, index_data
