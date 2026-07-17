from __future__ import annotations

import os
from pathlib import Path

import pytest

from pkgreuse import scanner


def _create_environment(root: Path, platform_name: str) -> Path:
    environment = root / "project" / ".venv"
    (environment / "pyvenv.cfg").parent.mkdir(parents=True, exist_ok=True)
    (environment / "pyvenv.cfg").write_text("home = test\n", encoding="utf-8")
    python = scanner.environment_python(environment, platform_name)
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_bytes(b"python")
    if platform_name == "nt":
        site_packages = environment / "Lib" / "site-packages"
    else:
        site_packages = environment / "lib" / "python3.12" / "site-packages"
    site_packages.mkdir(parents=True)
    return environment


def test_windows_environment_layout_is_detected(tmp_path: Path) -> None:
    environment = _create_environment(tmp_path, "nt")

    assert scanner.environment_python(environment, "nt").name == "python.exe"
    assert scanner.environment_site_packages(environment, "nt") == (
        environment / "Lib" / "site-packages"
    )
    assert scanner.is_virtual_environment_directory(environment, "nt")


def test_linux_environment_layout_is_detected(tmp_path: Path) -> None:
    environment = _create_environment(tmp_path, "posix")

    assert scanner.environment_python(environment, "posix") == (
        environment / "bin" / "python"
    )
    assert scanner.environment_site_packages(environment, "posix") == (
        environment / "lib" / "python3.12" / "site-packages"
    )
    assert scanner.is_virtual_environment_directory(environment, "posix")


def test_platform_roots_include_all_fixed_windows_drives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = (Path("C:/"), Path("D:/"))
    monkeypatch.setattr(scanner, "windows_fixed_drive_roots", lambda: expected)

    assert scanner.filesystem_roots("nt") == expected
    assert scanner.filesystem_roots("posix") == (Path("/"),)


def test_root_pruning_keeps_user_bearing_directories() -> None:
    root = Path(Path.cwd().anchor or os.path.abspath(os.sep))
    system_name = "Windows" if os.name == "nt" else "usr"

    assert scanner.should_skip_directory(root, system_name)
    assert not scanner.should_skip_directory(root, "Users")
    assert not scanner.should_skip_directory(root, "home")
    assert not scanner.should_skip_directory(root, "opt")


def test_discovery_skips_inaccessible_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    platform_name = "nt" if os.name == "nt" else "posix"
    environment = _create_environment(tmp_path, platform_name)
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    original_scandir = scanner.os.scandir

    def guarded_scandir(path: str | bytes | os.PathLike[str]):
        if Path(path) == blocked:
            raise PermissionError("blocked")
        return original_scandir(path)

    monkeypatch.setattr(scanner.os, "scandir", guarded_scandir)

    environments, directories_checked = scanner.discover_environments([tmp_path])

    assert environments == [environment.resolve()]
    assert directories_checked >= 3
