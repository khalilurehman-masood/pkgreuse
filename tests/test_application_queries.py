from __future__ import annotations

from pathlib import Path

import pytest

from pkgreuse.application.queries import LocalQueryService
from pkgreuse.infrastructure.index_repository import JsonIndexRepository


def _query_service(tmp_path: Path) -> LocalQueryService:
    repository = JsonIndexRepository(tmp_path / "index.json")
    candidate = {"environment": "donor", "version": "1.0"}
    newest = {"environment": "new-donor", "version": "3.0"}
    repository.save(
        {
            "schema_version": 1,
            "packages": {"demo": {"1.0": [candidate], "3.0": [newest]}},
        }
    )

    def select(data, requirement, _preferred):
        versions = data["packages"].get("demo", {})
        matching = [
            candidate
            for version, candidates in versions.items()
            if requirement.specifier.contains(version, prereleases=True)
            for candidate in candidates
        ]
        return matching[-1] if matching else None

    return LocalQueryService(
        repository,
        lambda data, name, version: (
            {version: data["packages"][name][version]}
            if version and version in data["packages"].get(name, {})
            else data["packages"].get(name, {})
        ),
        lambda candidates: candidates[0],
        select,
        lambda name, version, candidates: {
            "package": name,
            "version": version,
            "donor": candidates[0]["environment"],
        },
        lambda candidate, index: [
            {"status": "reusable", "candidate": candidate, "index": index}
        ],
        lambda name, version, donor, index: {
            "root": {"name": name, "version": version},
            "donor": donor,
            "index": index,
        },
    )


def test_lookup_and_transfer_planning_are_index_backed(tmp_path: Path) -> None:
    service = _query_service(tmp_path)
    lookup = service.lookup("Demo==1.0")
    planning = service.transfer_plan("demo==1.0")
    assert lookup.package_name == "demo"
    assert list(lookup.versions) == ["1.0"]
    assert planning.plan["donor"] == "donor"


def test_reuse_can_require_an_exact_version(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="requires an exact"):
        _query_service(tmp_path).transfer_plan("demo", require_exact=True)


def test_bounded_transfer_plan_selects_highest_local_version(tmp_path: Path) -> None:
    planning = _query_service(tmp_path).transfer_plan("demo>=1,<4")
    assert planning.version == "3.0"
    assert planning.plan["donor"] == "new-donor"


def test_dependency_and_resolution_services(tmp_path: Path) -> None:
    service = _query_service(tmp_path)
    dependencies = service.dependencies("demo==1.0")
    resolution = service.resolution_plan("demo==1.0")
    assert dependencies.donor["environment"] == "donor"
    assert dependencies.dependencies[0]["status"] == "reusable"
    assert resolution.plan["root"] == {"name": "demo", "version": "1.0"}


def test_missing_package_is_controlled(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Package not found"):
        _query_service(tmp_path).transfer_plan("missing==1.0")
