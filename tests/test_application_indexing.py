from __future__ import annotations

from pathlib import Path

import pytest

from pkgreuse.application.indexing import (
    IndexInitializationService,
    TargetIndexRefreshService,
)
from pkgreuse.domain.errors import IndexCorruptError
from pkgreuse.infrastructure.index_repository import JsonIndexRepository


def test_missing_index_is_initialized_once(tmp_path: Path) -> None:
    index_path = tmp_path / "target" / ".pkgreuse" / "index.json"
    repository = JsonIndexRepository(index_path)
    calls: list[list[Path]] = []

    def build(roots: list[Path], target: Path):
        calls.append(roots)
        data = {"schema_version": 1, "packages": {}, "environments": []}
        repository.save(data)
        return index_path, data

    service = IndexInitializationService(repository, build, tmp_path / "target")
    notifications: list[str] = []

    first = service.ensure([tmp_path], lambda: notifications.append("missing"))
    second = service.ensure([tmp_path], lambda: notifications.append("unexpected"))

    assert first.initialized is True
    assert second.initialized is False
    assert calls == [[tmp_path.resolve()]]
    assert notifications == ["missing"]


def test_corrupt_index_is_not_overwritten(tmp_path: Path) -> None:
    index_path = tmp_path / "index.json"
    index_path.write_text("{", encoding="utf-8")
    repository = JsonIndexRepository(index_path)
    built = False

    def build(roots: list[Path], target: Path):
        nonlocal built
        built = True
        return index_path, {}

    service = IndexInitializationService(repository, build, tmp_path)
    with pytest.raises(IndexCorruptError):
        service.ensure([tmp_path])
    assert built is False
    assert index_path.read_text(encoding="utf-8") == "{"


def test_target_refresh_merges_latest_index(tmp_path: Path) -> None:
    target = tmp_path / "target"
    site_packages = target / "Lib" / "site-packages"
    site_packages.mkdir(parents=True)
    donor = tmp_path / "donor"
    index_path = target / ".pkgreuse" / "index.json"
    repository = JsonIndexRepository(index_path)
    repository.save(
        {
            "schema_version": 1,
            "target": {"python": {"version": "3.13.7"}},
            "environments": [],
            "packages": {
                "demo": {
                    "1.0": [
                        {"environment": str(target)},
                        {"environment": str(donor)},
                    ]
                }
            },
        }
    )
    refreshed_distribution = {
        "name": "fresh",
        "normalized_name": "fresh",
        "version": "2.0",
        "environment": str(target),
        "site_packages": str(site_packages),
        "dist_info": str(site_packages / "fresh-2.0.dist-info"),
        "metadata": str(site_packages / "fresh-2.0.dist-info" / "METADATA"),
        "record": None,
        "editable": False,
    }
    service = TargetIndexRefreshService(
        repository,
        target,
        lambda _target: site_packages,
        lambda _target, _site: ([refreshed_distribution.copy()], []),
    )

    updated = service.refresh()

    assert updated["packages"]["demo"]["1.0"] == [{"environment": str(donor)}]
    assert updated["packages"]["fresh"]["2.0"][0]["environment"] == str(target)
    assert updated["environments"][0]["package_count"] == 1
    assert "updated_at" in updated
