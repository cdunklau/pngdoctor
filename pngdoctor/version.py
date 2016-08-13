"""The version for pngdoctor"""
# This file is exec'ed in setup.py, don't import anything!
# Base implementation borrowed from Ned Bachelder's coverage.py

# Same semantics as sys.version_info.
version_info = (0, 0, 0, 'alpha', 0)


def _make_version(major, minor, micro, releaselevel, serial):
    """Create a readable version string from version_info tuple components."""
    assert releaselevel in {'alpha', 'beta', 'candidate', 'final'}
    version = "{:d}.{:d}.{:d}".format(major, minor, micro)
    if releaselevel != 'final':
        short = {'alpha': 'a', 'beta': 'b', 'candidate': 'rc'}[releaselevel]
        version += "{}{:d}".format(short, serial)
    return version


__version__ = _make_version(*version_info)
