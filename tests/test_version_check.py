import pytest

from app.version_check import is_newer


@pytest.mark.parametrize(
    "candidate,current,expected",
    [
        ("0.21.0", "0.20.0", True),
        ("1.0.0", "0.20.0", True),
        ("0.20.1", "0.20.0", True),
        ("0.20.0", "0.20.0", False),
        ("0.19.0", "0.20.0", False),
        ("0.20.0", "0.21.0", False),
    ],
)
def test_is_newer_semver_ordering(candidate, current, expected):
    assert is_newer(candidate, current) is expected


@pytest.mark.parametrize(
    "candidate,current",
    [
        ("not-a-version", "0.20.0"),
        ("0.20.0", "not-a-version"),
        ("1.2", "0.20.0"),
        ("1.2.3.4", "0.20.0"),
        ("", "0.20.0"),
    ],
)
def test_is_newer_malformed_input_never_true(candidate, current):
    # A malformed tag from GitHub (or a malformed VERSION file) must never
    # surface a false "update available" — see is_newer's docstring.
    assert is_newer(candidate, current) is False
