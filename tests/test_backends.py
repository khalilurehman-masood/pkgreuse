from pathlib import Path

import pytest

from pkgreuse.domain.errors import BackendError
from pkgreuse.infrastructure import backends
from pkgreuse.infrastructure.backends import PipBackend, UvBackend


def test_pip_backend_targets_interpreter() -> None:
    command = PipBackend().command(
        Path("C:/target/Scripts/python.exe"),
        ["install", "demo==1"],
    )
    assert command == [
        "C:\\target\\Scripts\\python.exe",
        "-m",
        "pip",
        "install",
        "demo==1",
    ]


def test_uv_backend_targets_interpreter() -> None:
    command = UvBackend("C:/tools/uv.exe").command(
        Path("C:/target/Scripts/python.exe"),
        ["install", "demo==1"],
    )
    assert command[0:3] == ["C:/tools/uv.exe", "pip", "install"]
    assert "--python" in command
    assert "C:\\target\\Scripts\\python.exe" in command


def test_uv_backend_reports_missing_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(backends.shutil, "which", lambda _name: None)

    with pytest.raises(BackendError, match="uv was not found"):
        UvBackend().command(Path("C:/target/Scripts/python.exe"), ["install", "demo"])
