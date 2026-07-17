from __future__ import annotations

from pathlib import Path

import pytest
from packaging.requirements import Requirement

from pkgreuse import resolver, transfer
from pkgreuse.application.indexing import IndexInitializationService
from pkgreuse.application.installation import (
    InstallPreparationStatus,
    LocalInstallationService,
)
from pkgreuse.infrastructure.index_repository import JsonIndexRepository


def _candidate(tmp_path: Path, environment: str, version: str) -> dict[str, object]:
    record = tmp_path / environment / f"demo-{version}.dist-info" / "RECORD"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text("", encoding="utf-8")
    return {
        "environment": str(tmp_path / environment),
        "version": version,
        "record": str(record),
        "editable": False,
    }


def test_select_candidate_uses_global_local_maximum_not_donor_affinity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(resolver.sys, "prefix", str(tmp_path / "target"))
    lower_preferred = _candidate(tmp_path, "preferred", "1.5")
    highest_elsewhere = _candidate(tmp_path, "elsewhere", "3.0")
    excluded_too_low = _candidate(tmp_path, "old", "1.0")
    index = {
        "packages": {
            "demo": {
                "1.0": [excluded_too_low],
                "1.5": [lower_preferred],
                "3.0": [highest_elsewhere],
            }
        }
    }

    selected = resolver.select_candidate(
        index,
        Requirement("demo>=1.1,<4"),
        str(tmp_path / "preferred"),
    )

    assert selected is highest_elsewhere
    assert selected["version"] == "3.0"


def test_select_candidate_returns_none_when_local_subset_is_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(resolver.sys, "prefix", str(tmp_path / "target"))
    index = {"packages": {"demo": {"1.0": [_candidate(tmp_path, "old", "1.0")]}}}
    assert resolver.select_candidate(index, Requirement("demo>=2"), None) is None


def test_root_installation_preparation_uses_highest_satisfying_local_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "target"
    monkeypatch.setattr(resolver.sys, "prefix", str(target))
    repository = JsonIndexRepository(target / ".pkgreuse" / "index.json")
    lower = _candidate(tmp_path, "lower", "1.5")
    highest = _candidate(tmp_path, "highest", "3.0")
    index = {
        "schema_version": 1,
        "packages": {"demo": {"1.5": [lower], "3.0": [highest]}},
    }
    repository.save(index)
    initialization = IndexInitializationService(
        repository,
        lambda _roots, _target: (repository.path, index),
        target,
    )
    selected: list[str] = []

    def plan_builder(name, version, candidate, index_data):
        selected.append(version)
        return {
            "packages": [],
            "missing": [],
            "conflicts": [],
            "overlapping_files": [],
        }

    service = LocalInstallationService(
        initialization,
        lambda _name: None,
        resolver.version_satisfies,
        resolver.select_candidate,
        plan_builder,
        lambda **_kwargs: {},
    )

    preparation = service.prepare("demo>=1,<4")

    assert preparation.status is InstallPreparationStatus.PLAN_READY
    assert preparation.requested_version == "3.0"
    assert selected == ["3.0"]


def test_transitive_dependency_uses_highest_satisfying_local_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    distribution_factory,
) -> None:
    root = distribution_factory(
        "preferred",
        "rootpkg",
        "1.0",
        {"rootpkg/__init__.py": "ROOT = True\n"},
        requirements=["dependency>=1,<4"],
    )
    lower = distribution_factory(
        "preferred",
        "dependency",
        "1.5",
        {"dependency/__init__.py": "VERSION = '1.5'\n"},
    )
    highest = distribution_factory(
        "elsewhere",
        "dependency",
        "3.0",
        {"dependency/__init__.py": "VERSION = '3.0'\n"},
    )
    target = tmp_path / "target"
    target_site = target / "Lib" / "site-packages"
    target_site.mkdir(parents=True)
    monkeypatch.setattr(resolver.sys, "prefix", str(target))
    monkeypatch.setattr(transfer.sys, "prefix", str(target))
    monkeypatch.setattr(transfer, "target_site_packages", lambda: target_site)
    monkeypatch.setattr(resolver, "target_installed_version", lambda _name: None)
    index = {
        "packages": {
            "rootpkg": {"1.0": [root]},
            "dependency": {"1.5": [lower], "3.0": [highest]},
        }
    }

    plan = resolver.build_installation_plan("rootpkg", "1.0", root, index)

    selected = {package["name"]: package["version"] for package in plan["packages"]}
    assert selected == {"rootpkg": "1.0", "dependency": "3.0"}


def test_transitive_selection_maximizes_intersection_of_parent_constraints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    distribution_factory,
) -> None:
    root = distribution_factory(
        "root-donor",
        "rootpkg",
        "1.0",
        {"rootpkg/__init__.py": ""},
        requirements=["parent-a==1", "parent-b==1"],
    )
    parent_a = distribution_factory(
        "a-donor",
        "parent-a",
        "1",
        {"parent_a/__init__.py": ""},
        requirements=["shared>=1"],
    )
    parent_b = distribution_factory(
        "b-donor",
        "parent-b",
        "1",
        {"parent_b/__init__.py": ""},
        requirements=["shared<3"],
    )
    shared_two = distribution_factory(
        "shared-two",
        "shared",
        "2",
        {"shared/__init__.py": "VERSION = 2"},
    )
    shared_four = distribution_factory(
        "shared-four",
        "shared",
        "4",
        {"shared/__init__.py": "VERSION = 4"},
    )
    target = tmp_path / "target"
    target_site = target / "Lib" / "site-packages"
    target_site.mkdir(parents=True)
    monkeypatch.setattr(resolver.sys, "prefix", str(target))
    monkeypatch.setattr(transfer.sys, "prefix", str(target))
    monkeypatch.setattr(transfer, "target_site_packages", lambda: target_site)
    monkeypatch.setattr(resolver, "target_installed_version", lambda _name: None)
    index = {
        "packages": {
            "rootpkg": {"1.0": [root]},
            "parent-a": {"1": [parent_a]},
            "parent-b": {"1": [parent_b]},
            "shared": {"2": [shared_two], "4": [shared_four]},
        }
    }

    plan = resolver.build_installation_plan("rootpkg", "1.0", root, index)

    selected = {package["name"]: package["version"] for package in plan["packages"]}
    assert selected["shared"] == "2"
    assert plan["conflicts"] == []
