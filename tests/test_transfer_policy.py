from __future__ import annotations

import csv
import os
from pathlib import Path

import pytest

from pkgreuse import transfer
from pkgreuse.domain.models import TransferKind


def _configure_target(monkeypatch: pytest.MonkeyPatch, target: Path) -> Path:
    site_packages = target / "Lib" / "site-packages"
    site_packages.mkdir(parents=True)
    monkeypatch.setattr(transfer.sys, "prefix", str(target))
    monkeypatch.setattr(transfer, "target_site_packages", lambda: site_packages)
    return site_packages


def test_metadata_is_copied_while_package_content_can_be_linked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    distribution_factory,
) -> None:
    candidate = distribution_factory(
        "donor",
        "demo",
        "1.0",
        {"demo/__init__.py": "VALUE = 1\n"},
    )
    target_site = _configure_target(monkeypatch, tmp_path / "target")
    plan = transfer.create_transfer_plan("demo", "1.0", [candidate])

    by_kind = {entry["category"]: entry for entry in plan["planned_files"]}
    assert by_kind[TransferKind.PACKAGE_CONTENT.value]["link_eligible"] is True
    assert by_kind[TransferKind.DISTRIBUTION_METADATA.value]["link_eligible"] is False

    result = transfer.execute_transfer_plan(plan)
    assert result["files_transferred"] == 3

    source_package = Path(candidate["site_packages"]) / "demo" / "__init__.py"
    target_package = target_site / "demo" / "__init__.py"
    source_metadata = Path(candidate["metadata"])
    target_metadata = target_site / source_metadata.relative_to(
        candidate["site_packages"]
    )

    if plan["same_drive"]:
        assert os.stat(source_package).st_ino == os.stat(target_package).st_ino
    assert os.stat(source_metadata).st_ino != os.stat(target_metadata).st_ino


def test_launchers_are_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    distribution_factory,
) -> None:
    candidate = distribution_factory("donor", "demo", "1.0", {})
    record = Path(candidate["record"])
    with record.open("a", encoding="utf-8", newline="") as stream:
        csv.writer(stream).writerow(["../../Scripts/demo.exe", "", ""])
    launcher = Path(candidate["environment"]) / "Scripts" / "demo.exe"
    launcher.parent.mkdir(parents=True)
    launcher.write_bytes(b"launcher")
    _configure_target(monkeypatch, tmp_path / "target")

    plan = transfer.create_transfer_plan("demo", "1.0", [candidate])
    assert plan["skipped_launcher_files"] == ["../../Scripts/demo.exe"]
    assert all("demo.exe" not in item["destination"] for item in plan["planned_files"])


def test_unsafe_pth_blocks_reuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    distribution_factory,
) -> None:
    candidate = distribution_factory(
        "donor",
        "demo",
        "1.0",
        {"demo.pth": "import os\n"},
    )
    _configure_target(monkeypatch, tmp_path / "target")
    plan = transfer.create_transfer_plan("demo", "1.0", [candidate])
    assert plan["invalid_pth_files"] == ["demo.pth"]
    with pytest.raises(RuntimeError, match="unsafe .pth"):
        transfer.execute_transfer_plan(plan)


def test_absolute_donor_pth_blocks_reuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    distribution_factory,
) -> None:
    candidate = distribution_factory(
        "donor",
        "demo",
        "1.0",
        {"demo.pth": "placeholder\n"},
    )
    donor_path = Path(candidate["environment"]) / "shared"
    pth_path = Path(candidate["site_packages"]) / "demo.pth"
    pth_path.write_text(f"{donor_path}\n", encoding="utf-8")
    _configure_target(monkeypatch, tmp_path / "target")

    plan = transfer.create_transfer_plan("demo", "1.0", [candidate])

    assert plan["invalid_pth_files"] == ["demo.pth"]


def test_record_path_traversal_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    distribution_factory,
) -> None:
    candidate = distribution_factory("donor", "demo", "1.0", {})
    record = Path(candidate["record"])
    with record.open("a", encoding="utf-8", newline="") as stream:
        csv.writer(stream).writerow(["../../../outside.txt", "", ""])
    _configure_target(monkeypatch, tmp_path / "target")

    plan = transfer.create_transfer_plan("demo", "1.0", [candidate])
    assert "../../../outside.txt" in plan["unsafe_files"]


def test_stale_donor_is_not_selected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    distribution_factory,
) -> None:
    candidate = distribution_factory("donor", "demo", "1.0", {})
    Path(candidate["record"]).unlink()
    _configure_target(monkeypatch, tmp_path / "target")
    with pytest.raises(RuntimeError, match="No reusable donor"):
        transfer.create_transfer_plan("demo", "1.0", [candidate])


def test_mid_transfer_failure_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    distribution_factory,
) -> None:
    candidate = distribution_factory(
        "donor",
        "demo",
        "1.0",
        {"demo/a.py": "a", "demo/b.py": "b"},
    )
    target_site = _configure_target(monkeypatch, tmp_path / "target")
    plan = transfer.create_transfer_plan("demo", "1.0", [candidate])
    original_link = transfer.os.link
    calls = 0

    def failing_link(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise FileNotFoundError("donor changed")
        original_link(source, destination)

    monkeypatch.setattr(transfer.os, "link", failing_link)
    monkeypatch.setattr(
        transfer.shutil,
        "copyfile",
        lambda *_args: (_ for _ in ()).throw(FileNotFoundError("donor changed")),
    )

    with pytest.raises(FileNotFoundError):
        transfer.execute_transfer_plan(plan)
    assert not (target_site / "demo" / "a.py").exists()
    assert not (target_site / "demo" / "b.py").exists()


def test_source_disappearing_after_planning_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    distribution_factory,
) -> None:
    candidate = distribution_factory(
        "donor",
        "demo",
        "1.0",
        {"demo/a.py": "a", "demo/b.py": "b"},
    )
    target_site = _configure_target(monkeypatch, tmp_path / "target")
    plan = transfer.create_transfer_plan("demo", "1.0", [candidate])
    missing_source = Path(candidate["site_packages"]) / "demo" / "b.py"
    missing_source.unlink()

    with pytest.raises(FileNotFoundError):
        transfer.execute_transfer_plan(plan)

    assert not (target_site / "demo" / "a.py").exists()
    assert not (target_site / "demo" / "b.py").exists()


def test_validation_failure_rolls_back_complete_installation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    distribution_factory,
) -> None:
    candidate = distribution_factory(
        "donor",
        "demo",
        "1.0",
        {"demo/__init__.py": "VALUE = 1\n"},
    )
    target_site = _configure_target(monkeypatch, tmp_path / "target")
    package_plan = transfer.create_transfer_plan("demo", "1.0", [candidate])
    installation_plan = {
        "packages": [{"name": "demo", "version": "1.0", "transfer": package_plan}],
        "missing": [],
        "conflicts": [],
        "overlapping_files": [],
    }
    monkeypatch.setattr(
        transfer,
        "validate_complete_installation",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("validation failed")),
    )

    with pytest.raises(RuntimeError, match="validation failed"):
        transfer.execute_installation_plan(installation_plan)

    assert not (target_site / "demo" / "__init__.py").exists()
    assert not (target_site / "demo-1.0.dist-info").exists()


def test_cross_volume_plan_uses_copy_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    distribution_factory,
) -> None:
    candidate = distribution_factory(
        "donor",
        "demo",
        "1.0",
        {"demo/__init__.py": "VALUE = 1\n"},
    )
    target_site = _configure_target(monkeypatch, tmp_path / "target")
    plan = transfer.create_transfer_plan("demo", "1.0", [candidate])
    plan["same_drive"] = False

    result = transfer.execute_transfer_plan(plan)

    assert result["hardlinked_files"] == 0
    assert result["copied_files"] == result["files_transferred"]
    assert (target_site / "demo" / "__init__.py").read_text() == "VALUE = 1\n"
