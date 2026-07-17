"""Documented extended check for the verified NumPy native scenario.

Run manually in prepared donor/target environments:

    pytest -m extended tests/extended/test_numpy_manual.py

The environment variable must contain an exact indexed NumPy requirement.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest


@pytest.mark.extended
def test_numpy_native_reuse_manual() -> None:
    requirement = os.environ.get("PKGREUSE_NUMPY_REQUIREMENT")
    if not requirement:
        pytest.skip("Set PKGREUSE_NUMPY_REQUIREMENT, for example numpy==2.3.3")

    install = subprocess.run(
        [sys.executable, "-m", "pkgreuse.cli", "install", requirement],
        check=False,
    )
    assert install.returncode == 0
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import numpy as np; "
            "a=np.array([[1.,2.],[3.,4.]]); "
            "assert np.linalg.det(a) != 0",
        ],
        check=False,
    )
    assert probe.returncode == 0
