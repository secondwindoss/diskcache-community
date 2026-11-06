"""
DiskCache API Reference
=======================

The :doc:`tutorial` provides a helpful walkthrough of most methods.
"""

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
    SafeJSONDisk,
    Timeout,
    UnknownFileWarning,
    configure,
    default_disk,
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
    'SafeJSONDisk',
    'Timeout',
    'UNKNOWN',
    'UnknownFileWarning',
    'barrier',
    'configure',
    'default_disk',
    'memoize_stampede',
    'throttle',
]

try:
    from .djangocache import DjangoCache  # noqa

    __all__.append('DjangoCache')
except Exception:  # pylint: disable=broad-except  # pragma: no cover
    # Django not installed or not setup so ignore.
    pass


__title__ = 'diskcache-community'
__version__ = '5.8.3'
__build__ = 0x050803
__author__ = 'August V.'
__license__ = 'Apache 2.0'
__copyright__ = 'Copyright 2026 August V.'
