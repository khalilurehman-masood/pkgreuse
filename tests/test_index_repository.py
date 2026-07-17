from __future__ import annotations

import json
from pathlib import Path

import pytest

from pkgreuse.domain.errors import IndexCorruptError, IndexNotFoundError
from pkgreuse.infrastructure.index_repository import JsonIndexRepository


def test_json_repository_round_trip_is_atomic(tmp_path: Path) -> None:
    path = tmp_path / ".pkgreuse" / "index.json"
    repository = JsonIndexRepository(path)
    data = {"schema_version": 1, "packages": {"demo": {}}}

    repository.save(data)

    assert repository.load() == data
    assert not path.with_suffix(".json.tmp").exists()
    assert not path.with_suffix(".lock").exists()


def test_json_repository_reports_missing_index(tmp_path: Path) -> None:
    with pytest.raises(IndexNotFoundError):
        JsonIndexRepository(tmp_path / "index.json").load()


def test_json_repository_reports_corrupt_index(tmp_path: Path) -> None:
    path = tmp_path / "index.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(IndexCorruptError):
        JsonIndexRepository(path).load()


def test_json_repository_rejects_missing_inventory(tmp_path: Path) -> None:
    path = tmp_path / "index.json"
    path.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    with pytest.raises(IndexCorruptError):
        JsonIndexRepository(path).load()


def test_json_repository_update_uses_latest_data(tmp_path: Path) -> None:
    path = tmp_path / "index.json"
    repository = JsonIndexRepository(path)
    repository.save({"schema_version": 1, "packages": {"first": {}}})

    updated = repository.update(
        lambda data: {
            **data,
            "packages": {**data["packages"], "second": {}},
        }
    )

    assert set(updated["packages"]) == {"first", "second"}
    assert repository.load() == updated
