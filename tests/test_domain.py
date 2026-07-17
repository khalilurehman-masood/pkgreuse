from pathlib import Path

import pytest

from pkgreuse.domain.models import PythonIdentity
from pkgreuse.domain.names import normalize_package_name
from pkgreuse.domain.requirements import parse_requirement


def test_name_normalization_is_centralized() -> None:
    assert normalize_package_name("Typing_Extensions") == "typing-extensions"
    assert normalize_package_name("typing.extensions") == "typing-extensions"


def test_python_identity_fingerprint_is_stable() -> None:
    identity = PythonIdentity(
        implementation="cpython",
        version="3.13.7",
        cache_tag="cpython-313",
        architecture="64bit",
        platform="win32",
        base_prefix=Path("C:/Python313"),
        soabi="cp313-win_amd64",
    )
    assert identity.fingerprint() == identity.fingerprint()
    assert len(identity.fingerprint()) == 64


@pytest.mark.parametrize(
    "query",
    ["demo=>1", "demo @ https://example.invalid/demo.whl", "demo[extra]"],
)
def test_unsupported_requirements_are_rejected_locally(query: str) -> None:
    with pytest.raises(ValueError):
        parse_requirement(query)
