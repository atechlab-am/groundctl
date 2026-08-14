import shutil

import pytest

from app.version_compare import dpkg_compare

# dpkg_compare shells out to the real `dpkg` binary (Debian/Ubuntu-only) to
# get correct Debian version ordering (epochs, tildes, etc — see CLAUDE.md's
# "Version comparison" section: never use string/</> comparison here). This
# test machine is macOS and has no dpkg installed, so these tests are
# skipped in that environment rather than faked with a reimplemented
# comparator (which would defeat the point of testing the real dpkg
# integration). They will run for real on any Debian/Ubuntu CI runner or
# dev machine where dpkg is present — do not delete or weaken this file to
# "fix" the local skip.
pytestmark = pytest.mark.skipif(
    shutil.which("dpkg") is None,
    reason="dpkg binary not available on this host (macOS) — dpkg_compare shells out to real dpkg",
)


@pytest.mark.parametrize(
    "v1,v2,expected",
    [
        ("1.0", "1.0", 0),
        ("1.0", "2.0", -1),
        ("2.0", "1.0", 1),
        # Tildes sort before the release they modify — the classic case
        # plain string/</> comparison gets wrong ("1.0~rc1" > "1.0" lexically
        # since '~' > '' is false in ASCII... but the point is dpkg treats
        # ~ as "earlier than nothing", i.e. earlier than the base version).
        ("1.0~rc1", "1.0", -1),
        ("1.0", "1.0~rc1", 1),
        ("1.0~rc1", "1.0~rc2", -1),
        ("1.0~~", "1.0~", -1),
        # Epochs dominate everything else in the version string.
        ("1:1.0", "2.0", 1),
        ("1:1.0", "1:2.0", -1),
        ("0:1.0", "1.0", 0),
        # Debian revision suffix (-N) ordering.
        ("1.0-1", "1.0-2", -1),
        ("1.0-2", "1.0-1", 1),
        ("1.0-1", "1.0-1", 0),
        # Trailing ~ prerelease markers vs a plain numeric bump.
        ("2.4.7-1ubuntu1", "2.4.7-1ubuntu2", -1),
        ("2.4.7-1ubuntu2", "2.4.7-1ubuntu1", 1),
        # Alphanumeric upstream versions compare component-wise, not lexically.
        ("1.0.9", "1.0.10", -1),
        ("1.0.10", "1.0.9", 1),
    ],
)
def test_dpkg_compare_ordering(v1, v2, expected):
    assert dpkg_compare(v1, v2) == expected


def test_dpkg_compare_is_antisymmetric():
    assert dpkg_compare("1.2.3-1", "1.2.4-1") == -dpkg_compare("1.2.4-1", "1.2.3-1")


def test_dpkg_compare_equal_versions_both_directions():
    assert dpkg_compare("3.14.0-2", "3.14.0-2") == 0
