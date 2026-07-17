from __future__ import annotations

import sys
from pathlib import Path

import pytest

from pkgreuse import cli
from pkgreuse.application.installation import (
    InstallPreparation,
    InstallPreparationStatus,
)


@pytest.mark.parametrize(
    ("arguments", "handler", "expected"),
    [
        (["status"], "show_status", ()),
        (["init", "C:/work"], "initialize_index", (["C:/work"],)),
        (["find", "demo"], "find_package", ("demo",)),
        (["plan", "demo==1"], "plan_package_transfer", ("demo==1",)),
        (["reuse", "demo==1"], "reuse_package", ("demo==1",)),
        (["deps", "demo==1"], "show_package_dependencies", ("demo==1",)),
        (["resolve", "demo==1"], "plan_complete_installation", ("demo==1",)),
        (["install", "demo==1"], "install_complete_local_package", ("demo==1",)),
    ],
)
def test_command_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
    handler: str,
    expected: tuple[object, ...],
) -> None:
    called: list[tuple[object, ...]] = []
    monkeypatch.setattr(cli, handler, lambda *args: called.append(args) or 17)
    monkeypatch.setattr(sys, "argv", ["pkgreuse", *arguments])

    assert cli.main() == 17
    assert called == [expected]


@pytest.mark.parametrize(
    ("arguments", "backend", "installer_arguments"),
    [
        (["pip", "install", "demo==1"], "pip", ["install", "demo==1"]),
        (
            ["uv", "pip", "install", "demo==1"],
            "uv",
            ["pip", "install", "demo==1"],
        ),
    ],
)
def test_wrapper_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
    backend: str,
    installer_arguments: list[str],
) -> None:
    calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        cli,
        "handle_prefixed_installer",
        lambda backend, installer_arguments: (
            calls.append((backend, installer_arguments)) or 23
        ),
    )
    monkeypatch.setattr(sys, "argv", ["pkgreuse", *arguments])

    assert cli.main() == 23
    assert calls == [(backend, installer_arguments)]


def test_status_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "is_virtual_environment", lambda: True)

    assert cli.show_status() == 0
    output = capsys.readouterr().out
    assert "Active virtual environment detected" in output
    assert "Implementation:" in output
    assert "Local index:" in output


def test_wrapper_rejects_non_install_syntax(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.handle_prefixed_installer("pip", ["list"]) == 1
    assert "currently supported syntax" in capsys.readouterr().out


def test_already_satisfied_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "require_virtual_environment", lambda: True)
    monkeypatch.setattr(cli, "target_installed_version", lambda _name: "1.0")

    assert cli.install_complete_local_package("demo==1.0") == 0
    assert "No files were changed." in capsys.readouterr().out


def test_backend_adapter_is_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeBackend:
        def command(self, target_python: Path, arguments: list[str]) -> list[str]:
            return ["fake", *arguments]

        def install(self, target_python: Path, arguments: list[str]) -> int:
            return 7

    monkeypatch.setattr(cli, "backend_for", lambda _name: FakeBackend())
    assert cli.run_backend_install("pip", "demo==1") == 7


def test_backend_failure_exit_code_is_propagated_without_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingBackend:
        def command(self, target_python: Path, arguments: list[str]) -> list[str]:
            return ["fake", *arguments]

        def install(self, target_python: Path, arguments: list[str]) -> int:
            return 19

    refreshed: list[bool] = []
    monkeypatch.setattr(cli, "backend_for", lambda _name: FailingBackend())
    monkeypatch.setattr(cli, "refresh_target_index", lambda: refreshed.append(True))

    assert cli.run_backend_install("pip", "demo==1") == 19
    assert refreshed == []


def test_first_install_reports_automatic_initialization(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeService:
        def prepare(self, query: str, on_index_missing):
            on_index_missing()
            return InstallPreparation(
                status=InstallPreparationStatus.ALREADY_SATISFIED,
                package_name="demo",
                requested_version="1.0",
                installed_version="1.0",
                auto_initialized=True,
            )

    monkeypatch.setattr(cli, "require_virtual_environment", lambda: True)
    monkeypatch.setattr(cli, "local_installation_service", lambda: FakeService())

    assert cli.install_complete_local_package("demo==1.0") == 0
    output = capsys.readouterr().out
    assert "No local PKGReuse index was found." in output
    assert "Scanning for compatible virtual environments..." in output


def test_successful_backend_install_refreshes_target_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeBackend:
        def command(self, target_python: Path, arguments: list[str]) -> list[str]:
            return ["fake", *arguments]

        def install(self, target_python: Path, arguments: list[str]) -> int:
            return 0

    refreshed: list[bool] = []
    monkeypatch.setattr(cli, "backend_for", lambda _name: FakeBackend())
    monkeypatch.setattr(cli, "refresh_target_index", lambda: refreshed.append(True))

    assert cli.run_backend_install("pip", "demo==1") == 0
    assert refreshed == [True]


def test_refresh_failure_is_a_warning_after_install(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class BrokenRefresh:
        def refresh(self) -> None:
            raise OSError("locked")

    monkeypatch.setattr(cli, "target_refresh_service", lambda: BrokenRefresh())
    cli.refresh_target_index()
    assert (
        "package installed, but target index refresh failed" in capsys.readouterr().out
    )


def test_fallback_preserves_original_bounded_requirement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeService:
        def prepare(self, query: str, on_index_missing):
            return InstallPreparation(
                status=InstallPreparationStatus.FALLBACK_REQUIRED,
                package_name="demo",
                requested_version=">=2",
                reason="no reusable local version satisfies demo>=2.",
            )

    delegated: list[tuple[str, str]] = []
    monkeypatch.setattr(cli, "require_virtual_environment", lambda: True)
    monkeypatch.setattr(cli, "local_installation_service", lambda: FakeService())
    monkeypatch.setattr(
        cli,
        "run_backend_install",
        lambda backend, package_query: delegated.append((backend, package_query)) or 0,
    )

    assert cli.install_complete_local_package("demo>=2", "uv") == 0
    assert delegated == [("uv", "demo>=2")]


def test_invalid_requirement_is_not_delegated(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class RejectingService:
        def prepare(self, query: str, on_index_missing):
            raise ValueError(f"Invalid package requirement: {query}")

    delegated: list[tuple[str, str]] = []
    monkeypatch.setattr(cli, "require_virtual_environment", lambda: True)
    monkeypatch.setattr(cli, "local_installation_service", lambda: RejectingService())
    monkeypatch.setattr(
        cli,
        "run_backend_install",
        lambda backend, query: delegated.append((backend, query)) or 0,
    )

    assert cli.install_complete_local_package("demo=>1", "pip") == 1
    assert delegated == []
    assert "Invalid package requirement" in capsys.readouterr().out


def test_unsafe_preparation_is_not_executed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeService:
        def prepare(self, query: str, on_index_missing):
            return InstallPreparation(
                status=InstallPreparationStatus.FALLBACK_REQUIRED,
                package_name="demo",
                requested_version="1.0",
                plan={"unsafe": True},
                reason="demo==1.0: 1 unsafe .pth files",
            )

        def execute(self, *args, **kwargs):
            raise AssertionError("unsafe plan must not execute")

    monkeypatch.setattr(cli, "require_virtual_environment", lambda: True)
    monkeypatch.setattr(cli, "local_installation_service", lambda: FakeService())

    assert cli.install_complete_local_package("demo==1.0") == 1
    output = capsys.readouterr().out
    assert "1 unsafe .pth files" in output
    assert "ready installation plan" not in output
