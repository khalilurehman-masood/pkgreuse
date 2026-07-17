"""Install the built wheel in a temporary venv and probe its public CLI."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import venv
from pathlib import Path


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    pyproject = (project_root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', pyproject, re.MULTILINE)
    if match is None:
        raise RuntimeError("Could not determine the project version.")
    expected_version = match.group(1)
    wheels = sorted((project_root / "dist").glob("pkgreuse-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"Expected exactly one wheel in dist, found {len(wheels)}.")

    with tempfile.TemporaryDirectory(prefix="pkgreuse-release-") as temporary:
        environment = Path(temporary) / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        scripts = environment / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        executable = scripts / ("pkgreuse.exe" if os.name == "nt" else "pkgreuse")

        subprocess.run(
            [str(python), "-m", "pip", "install", str(wheels[0])],
            check=True,
        )
        version = subprocess.run(
            [str(executable), "--version"],
            check=True,
            capture_output=True,
            text=True,
        )
        if version.stdout.strip() != f"pkgreuse {expected_version}":
            raise RuntimeError(f"Unexpected version output: {version.stdout!r}")

        subprocess.run([str(executable), "status"], check=True)


if __name__ == "__main__":
    main()
