import subprocess


def dpkg_compare(v1: str, v2: str) -> int:
    """Return -1, 0, 1 for v1 <, ==, > v2, using dpkg's own version ordering
    (epochs, tildes, etc.) — never Python string/</> comparisons. Shared by
    app/routers/compliance.py and app/routers/errata.py.
    """
    for op, result in (("lt", -1), ("eq", 0), ("gt", 1)):
        proc = subprocess.run(
            ["dpkg", "--compare-versions", v1, op, v2],
            capture_output=True,
            check=False,
        )
        if proc.returncode == 0:
            return result
    # Should be unreachable: one of lt/eq/gt must hold for any two versions.
    raise RuntimeError(f"could not compare versions {v1!r} and {v2!r}")
