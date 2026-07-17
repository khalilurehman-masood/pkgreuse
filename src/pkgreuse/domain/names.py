"""Distribution-name normalization policy."""

from __future__ import annotations

import re

_SEPARATOR_RUN = re.compile(r"[-_.]+")


def normalize_package_name(name: str) -> str:
    """Return the canonical normalized form of a distribution name."""
    return _SEPARATOR_RUN.sub("-", name).lower()
