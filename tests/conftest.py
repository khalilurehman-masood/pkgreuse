from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path

import pytest


@pytest.fixture
def distribution_factory(tmp_path: Path):
    """Create small installed-distribution fixtures without invoking pip."""

    def create(
        environment_name: str,
        package_name: str,
        version: str,
        files: dict[str, str],
        requirements: Iterable[str] = (),
    ) -> dict[str, object]:
        environment = tmp_path / environment_name
        site_packages = environment / "Lib" / "site-packages"
        dist_info = site_packages / f"{package_name}-{version}.dist-info"
        dist_info.mkdir(parents=True)

        metadata = [
            "Metadata-Version: 2.1",
            f"Name: {package_name}",
            f"Version: {version}",
        ]
        metadata.extend(f"Requires-Dist: {item}" for item in requirements)
        metadata_path = dist_info / "METADATA"
        metadata_path.write_text("\n".join(metadata) + "\n\n", encoding="utf-8")

        record_rows: list[list[str]] = []
        for relative_path, content in files.items():
            path = site_packages / Path(*relative_path.split("/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            record_rows.append([relative_path, "", ""])

        metadata_relative = metadata_path.relative_to(site_packages).as_posix()
        record_relative = (dist_info / "RECORD").relative_to(site_packages).as_posix()
        record_rows.extend(
            [
                [metadata_relative, "", ""],
                [record_relative, "", ""],
            ]
        )
        record_path = dist_info / "RECORD"
        with record_path.open("w", encoding="utf-8", newline="") as stream:
            csv.writer(stream).writerows(record_rows)

        return {
            "name": package_name,
            "version": version,
            "environment": str(environment),
            "site_packages": str(site_packages),
            "dist_info": str(dist_info),
            "metadata": str(metadata_path),
            "record": str(record_path),
            "editable": False,
        }

    return create
