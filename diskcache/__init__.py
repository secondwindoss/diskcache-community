"""
DiskCache API Reference
=======================

The :doc:`tutorial` provides a helpful walkthrough of most methods.
"""

import os
import warnings

from .core import (
    DEFAULT_SETTINGS,
    ENOVAL,
    EVICTION_POLICY,
    UNKNOWN,
    Cache,
    Disk,
    EmptyDirWarning,
    JSONDisk,
    ReadOnlyError,
    SafeDisk,
    Timeout,
    UnknownFileWarning,
)
from .fanout import FanoutCache
from .persistent import Deque, Index
from .recipes import (
    Averager,
    BoundedSemaphore,
    Lock,
    RLock,
    barrier,
    memoize_stampede,
    throttle,
)

__all__ = [
    'Averager',
    'BoundedSemaphore',
    'Cache',
    'DEFAULT_SETTINGS',
    'Deque',
    'Disk',
    'ENOVAL',
    'EVICTION_POLICY',
    'EmptyDirWarning',
    'FanoutCache',
    'Index',
    'JSONDisk',
    'Lock',
    'RLock',
    'ReadOnlyError',
    'SafeDisk',
    'Timeout',
    'UNKNOWN',
    'UnknownFileWarning',
    'barrier',
    'memoize_stampede',
    'throttle',
]

try:
    from .djangocache import DjangoCache  # noqa

    __all__.append('DjangoCache')
except Exception:  # pylint: disable=broad-except  # pragma: no cover
    # Django not installed or not setup so ignore.
    pass


def _warn_if_upstream_installed(site_dir=None):
    """Warn when the upstream ``diskcache`` distribution is installed too.

    Both distributions install into the same ``diskcache`` package directory,
    so the files on disk belong to whichever was installed last and
    uninstalling either one removes them for both. Return True when the
    warning was issued.

    """
    if site_dir is None:
        site_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    try:
        names = os.listdir(site_dir)
    except OSError:
        return False

    for name in names:
        if name.startswith('diskcache-') and name.endswith(
            ('.dist-info', '.egg-info')
        ):
            warnings.warn(
                'the diskcache distribution is installed next to'
                ' diskcache-community; both provide the diskcache package'
                ' directory, so uninstall diskcache (pip uninstall diskcache)'
                ' and then reinstall diskcache-community',
                RuntimeWarning,
                stacklevel=2,
            )
            return True

    return False


_warn_if_upstream_installed()


__title__ = 'diskcache-community'
__version__ = '5.6.3'
__build__ = 0x050603
__author__ = 'Grant Jenks'
__license__ = 'Apache 2.0'
__copyright__ = 'Copyright 2016-2023 Grant Jenks'
