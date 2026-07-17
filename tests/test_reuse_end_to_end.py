from __future__ import annotations

from pathlib import Path

import pytest

from pkgreuse import resolver, transfer


def _index(*candidates: dict[str, object]) -> dict[str, object]:
    packages: dict[str, dict[str, list[dict[str, object]]]] = {}
    for candidate in candidates:
        packages.setdefault(str(candidate["name"]), {}).setdefault(
            str(candidate["version"]), []
        ).append(candidate)
    return {"schema_version": 1, "packages": packages}


def _target(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    target = tmp_path / "target"
    site_packages = target / "Lib" / "site-packages"
    site_packages.mkdir(parents=True)
    monkeypatch.setattr(transfer.sys, "prefix", str(target))
    monkeypatch.setattr(transfer, "target_site_packages", lambda: site_packages)
    monkeypatch.setattr(resolver, "target_installed_version", lambda _name: None)
    monkeypatch.setattr(transfer, "validate_complete_installation", lambda **_kw: None)
    return site_packages


def test_pure_python_reuse_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    distribution_factory,
) -> None:
    demo = distribution_factory(
        "donor",
        "demo",
        "1.0",
        {"demo/__init__.py": "VALUE = 42\n"},
    )
    target_site = _target(monkeypatch, tmp_path)
    plan = resolver.build_installation_plan("demo", "1.0", demo, _index(demo))

    result = transfer.execute_installation_plan(plan)

    assert result["package_versions"] == {"demo": "1.0"}
    assert (target_site / "demo" / "__init__.py").read_text() == "VALUE = 42\n"


def test_dependency_closure_reuse_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    distribution_factory,
) -> None:
    dependency = distribution_factory(
        "donor",
        "dependency",
        "2.0",
        {"dependency/__init__.py": "VERSION = 2\n"},
    )
    root = distribution_factory(
        "donor",
        "rootpkg",
        "1.0",
        {"rootpkg/__init__.py": "ROOT = True\n"},
        requirements=["dependency>=2"],
    )
    target_site = _target(monkeypatch, tmp_path)
    plan = resolver.build_installation_plan(
        "rootpkg",
        "1.0",
        root,
        _index(root, dependency),
    )

    assert {item["name"] for item in plan["packages"]} == {"rootpkg", "dependency"}
    result = transfer.execute_installation_plan(plan)
    assert result["packages_installed"] == 2
    assert (target_site / "rootpkg" / "__init__.py").exists()
    assert (target_site / "dependency" / "__init__.py").exists()
