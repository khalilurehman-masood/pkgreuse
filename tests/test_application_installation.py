from __future__ import annotations

from pathlib import Path

from pkgreuse.application.indexing import IndexInitializationService
from pkgreuse.application.installation import (
    InstallPreparationStatus,
    LocalInstallationService,
    installation_plan_blockers,
)
from pkgreuse.infrastructure.index_repository import JsonIndexRepository
from pkgreuse.resolver import version_satisfies


def _service(tmp_path: Path, installed: str | None = None):
    target = tmp_path / "target"
    repository = JsonIndexRepository(target / ".pkgreuse" / "index.json")
    candidate = {"environment": str(tmp_path / "donor"), "version": "1.0"}
    index = {
        "schema_version": 1,
        "packages": {"demo": {"1.0": [candidate]}},
    }
    builds: list[int] = []

    def build(roots: list[Path], target_environment: Path):
        builds.append(1)
        repository.save(index)
        return repository.path, index

    plan = {
        "packages": [
            {
                "name": "demo",
                "version": "1.0",
                "transfer": {
                    "conflicts": [],
                    "missing_files": [],
                    "unsafe_files": [],
                    "environment_files": 0,
                    "invalid_pth_files": [],
                },
            }
        ],
        "missing": [],
        "conflicts": [],
        "overlapping_files": [],
    }
    initialization = IndexInitializationService(repository, build, target)
    service = LocalInstallationService(
        initialization,
        lambda _name: installed,
        version_satisfies,
        lambda data, requirement, _preferred: (
            candidate
            if requirement.specifier.contains(candidate["version"], prereleases=True)
            else None
        ),
        lambda *_args: plan,
        lambda **_kwargs: {"packages_installed": 1},
    )
    return service, builds


def test_first_install_auto_initializes_before_planning(tmp_path: Path) -> None:
    service, builds = _service(tmp_path)
    notices: list[str] = []

    preparation = service.prepare("demo==1.0", lambda: notices.append("scan"))

    assert preparation.status is InstallPreparationStatus.PLAN_READY
    assert preparation.auto_initialized is True
    assert builds == [1]
    assert notices == ["scan"]


def test_initialized_install_does_not_rescan(tmp_path: Path) -> None:
    service, builds = _service(tmp_path)
    service.prepare("demo==1.0")

    preparation = service.prepare("demo==1.0")

    assert preparation.status is InstallPreparationStatus.PLAN_READY
    assert preparation.auto_initialized is False
    assert builds == [1]


def test_first_already_satisfied_install_still_initializes(tmp_path: Path) -> None:
    service, builds = _service(tmp_path, installed="1.0")

    preparation = service.prepare("demo==1.0")

    assert preparation.status is InstallPreparationStatus.ALREADY_SATISFIED
    assert preparation.auto_initialized is True
    assert builds == [1]


def test_unsafe_plan_is_returned_for_fallback(tmp_path: Path) -> None:
    service, _builds = _service(tmp_path)
    original_builder = service.plan_builder

    def unsafe_builder(*args):
        plan = original_builder(*args)
        plan["packages"][0]["transfer"]["invalid_pth_files"] = ["demo.pth"]
        return plan

    service.plan_builder = unsafe_builder
    preparation = service.prepare("demo==1.0")

    assert preparation.status is InstallPreparationStatus.FALLBACK_REQUIRED
    assert "unsafe .pth" in (preparation.reason or "")


def test_plan_blockers_include_closure_failures() -> None:
    plan = {
        "packages": [],
        "missing": [{"package": "dependency"}],
        "conflicts": [{"package": "other"}],
        "overlapping_files": [{"destination": "shared.py"}],
    }
    blockers = installation_plan_blockers(plan)
    assert blockers == (
        "1 missing dependencies",
        "1 dependency conflicts",
        "1 overlapping files",
    )


def test_empty_local_subset_requires_fallback(tmp_path: Path) -> None:
    service, _builds = _service(tmp_path)
    preparation = service.prepare("demo>=2")
    assert preparation.status is InstallPreparationStatus.FALLBACK_REQUIRED
    assert "no reusable local version satisfies" in (preparation.reason or "")
