"""Install the built wheel in a temporary venv and probe its public CLI."""

from __future__ import annotations

import subprocess
import tempfile
import venv
from pathlib import Path


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    wheels = sorted((project_root / "dist").glob("pkgreuse-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"Expected exactly one wheel in dist, found {len(wheels)}.")

    with tempfile.TemporaryDirectory(prefix="pkgreuse-release-") as temporary:
        environment = Path(temporary) / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / "Scripts" / "python.exe"
        executable = environment / "Scripts" / "pkgreuse.exe"

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
        if version.stdout.strip() != "pkgreuse 0.1.0":
            raise RuntimeError(f"Unexpected version output: {version.stdout!r}")

        subprocess.run([str(executable), "status"], check=True)


if __name__ == "__main__":
    main()
