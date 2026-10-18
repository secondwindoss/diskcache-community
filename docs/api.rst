DiskCache API Reference
=======================

.. py:module:: diskcache

The :doc:`tutorial` provides a helpful walkthrough of most methods.

.. contents::
   :local:

Cache
-----

Read the :ref:`Cache tutorial <tutorial-cache>` for example usage.

.. autoclass:: diskcache_community.Cache
   :members:
   :special-members:
   :exclude-members: __weakref__

FanoutCache
-----------

Read the :ref:`FanoutCache tutorial <tutorial-fanoutcache>` for example usage.

.. autoclass:: diskcache_community.FanoutCache
   :members:
   :special-members:
   :exclude-members: __weakref__

DjangoCache
-----------

Read the :ref:`DjangoCache tutorial <tutorial-djangocache>` for example usage.

.. autoclass:: diskcache_community.DjangoCache
   :members:
   :special-members:

Deque
-----

.. autoclass:: diskcache_community.Deque
   :members:
   :special-members:
   :exclude-members: __weakref__

Index
-----

.. autoclass:: diskcache_community.Index
   :members:
   :special-members:
   :exclude-members: __weakref__

Recipes
-------

.. autoclass:: diskcache_community.Averager
   :members:

.. autoclass:: diskcache_community.Lock
   :members:

.. autoclass:: diskcache_community.RLock
   :members:

.. autoclass:: diskcache_community.BoundedSemaphore
   :members:

.. autodecorator:: diskcache_community.throttle

.. autodecorator:: diskcache_community.barrier

.. autodecorator:: diskcache_community.memoize_stampede

.. _constants:

Constants
---------

Read the :ref:`Settings tutorial <tutorial-settings>` for details.

.. data:: diskcache_community.DEFAULT_SETTINGS

   * `statistics` (int) default 0 - disabled when 0, enabled when 1.
   * `tag_index` (int) default 0 - disabled when 0, enabled when 1.
   * `eviction_policy` (str) default "least-recently-stored" - any of the keys
     in `EVICTION_POLICY` as described below.
   * `size_limit` (int, in bytes) default one gigabyte - approximate size limit
     of cache.
   * `cull_limit` (int) default ten - maximum number of items culled during
     `set` or `add` operations.
   * `sqlite_auto_vacuum` (int) default 1, "FULL" - SQLite auto vacuum pragma.
   * `sqlite_cache_size` (int, in pages) default 8,192 - SQLite cache size
     pragma.
   * `sqlite_journal_mode` (str) default "wal" - SQLite journal mode pragma.
   * `sqlite_mmap_size` (int, in bytes) default 64 megabytes - SQLite mmap size
     pragma.
   * `sqlite_synchronous` (int) default 1, "NORMAL" - SQLite synchronous
     pragma.
   * `disk_min_file_size` (int, in bytes) default 32 kilobytes - values with
     greater size are stored in files.
   * `disk_pickle_protocol` (int) default highest Pickle protocol - the Pickle
     protocol to use for data types that are not natively supported.

.. data:: diskcache_community.EVICTION_POLICY

   * `least-recently-stored` (default) - evict least recently stored keys first.
   * `least-recently-used` - evict least recently used keys first.
   * `least-frequently-used` - evict least frequently used keys first.
   * `none` - never evict keys.

Disk
----

Read the :ref:`Disk tutorial <tutorial-disk>` for details.

.. autoclass:: diskcache_community.Disk
   :members:
   :special-members:
   :exclude-members: __weakref__

JSONDisk
--------

Read the :ref:`Disk tutorial <tutorial-disk>` for details.

.. autoclass:: diskcache_community.JSONDisk
   :members:
   :special-members:
   :exclude-members: __weakref__

SafeDisk
--------

Read the :ref:`SafeDisk tutorial <tutorial-safedisk>` for details.

.. autoclass:: diskcache_community.SafeDisk
   :members:
   :special-members:
   :exclude-members: __weakref__

.. data:: diskcache_community.core.SAFE_PICKLE_NAMES

   Mapping of module name to the names that :class:`SafeDisk
   <diskcache_community.SafeDisk>` lets pickle resolve while reading.

.. data:: diskcache_community.core.SAFE_TYPES

   The Python types that :class:`SafeDisk <diskcache_community.SafeDisk>` accepts
   for writing; exactly the types the names above read back.

.. data:: diskcache_community.core.UNSAFE_MODULES

   Packages whose classes :meth:`SafeDisk.with_types
   <diskcache_community.SafeDisk.with_types>` refuses to allow, because
   unpickling them is not memory-safe.

Default disk
------------

Read the :ref:`default disk tutorial <tutorial-default-disk>` for details.

.. autofunction:: diskcache_community.configure

.. autofunction:: diskcache_community.default_disk

Timeout
-------

.. autoexception:: diskcache_community.Timeout

ReadOnlyError
-------------

Read the :ref:`read-only tutorial <tutorial-read-only>` for details.

.. autoexception:: diskcache_community.ReadOnlyError
