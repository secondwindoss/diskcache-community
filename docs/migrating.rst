Migrating from diskcache 5.6.3
==============================

Replace the dependency and the imports. Cache directories need no changes:

.. code-block:: shell

    $ pip install diskcache-community

.. code-block:: python

    import diskcache_community as diskcache       # was: import diskcache
    from diskcache_community import Cache          # was: from diskcache import Cache

diskcache-community keeps the public API of diskcache 5.6.3, the ``cache.db``
schema, the file layout, the serialization modes, the persisted settings and
the memoize key format. A directory written by 5.6.3 opens with the fork, and
a directory written by the fork opens with 5.6.3. The fork needs Python 3.10
or later and has no runtime dependencies.

Steps
-----

1. **Change the dependency.** Replace ``diskcache`` with
   ``diskcache-community`` in ``pyproject.toml``, ``requirements.txt`` or
   wherever the project declares it:

   .. code-block:: toml

       dependencies = [
           "diskcache-community>=5.8",
       ]

2. **Change every import.** The package is imported as
   ``diskcache_community``. Find the imports with:

   .. code-block:: shell

       $ grep -rn "diskcache" --include="*.py" .

   Change the imports of exceptions and warnings as well as the containers.
   When the upstream package stays installed, ``except diskcache.Timeout``
   does not catch the :exc:`Timeout <diskcache_community.Timeout>` that a
   ``diskcache_community`` cache raises, because the two packages define
   separate classes. The same goes for :class:`Disk
   <diskcache_community.Disk>` subclasses: base them on
   ``diskcache_community.Disk`` or ``diskcache_community.JSONDisk``.

3. **Change the Django settings.** Name the backend
   ``'diskcache_community.DjangoCache'``. A ``DISK`` option names
   ``'diskcache_community.SafeDisk'`` or the import path of your own disk
   class:

   .. code-block:: python

       CACHES = {
           'default': {
               'BACKEND': 'diskcache_community.DjangoCache',
               'LOCATION': '/var/tmp/django_cache',
               'SHARDS': 8,
           }
       }

4. **Run the tests.** Existing cache directories open as they are, so a test
   suite or a staging environment that uses a cache written by 5.6.3 is a
   good check.

When another dependency still needs diskcache
---------------------------------------------

The fork never touches the upstream ``diskcache`` package, so both can be
installed in the same environment. Each library uses the package it imports,
and the objects of one are not instances of the other's classes: pass
``diskcache_community`` caches only to code that imports
``diskcache_community``, and catch the exceptions of the package that created
the cache.

A library that wants to work with either package can import whichever is
installed:

.. code-block:: python

    try:
        import diskcache_community as diskcache
    except ImportError:
        import diskcache

Scanners keep reporting CVE-2025-69872 while the upstream package is
installed. Run ``pip show diskcache`` to see whether it is, and, with
pipdeptree installed, ``pipdeptree -r -p diskcache`` to see which dependency
requires it.

What behaves differently
------------------------

These changes from 5.6.3 can be noticed by an application. The
``CHANGELOG.md`` in the repository lists every change.

* **New directories are created with mode 0700.** That includes missing
  parent directories and the value subdirectories. Existing directories keep
  their permissions. If several users share a cache directory, create it with
  the permissions you want before the first cache opens it.
* **Read-only caches.** A cache whose database or directory is not writable
  opens read-only instead of failing, as does ``Cache(directory,
  read_only=True)``. Reads work and every write raises :exc:`ReadOnlyError
  <diskcache_community.ReadOnlyError>`, a subclass of
  :exc:`sqlite3.OperationalError`. Opening an existing cache writes nothing
  unless a setting differs from the stored one.
* **SQLite builds compiled with SQLITE_DQS=0 work.** On the first open with
  write access, the fork rewrites the ``Settings`` triggers of an older cache
  to use single-quoted literals. 5.6.3 reads the rewritten triggers as well.
* **Memoize and ignored parameters.** A parameter named in ``ignore`` is now
  ignored whether it is passed by keyword or by position. Calls that passed
  an ignored parameter by position get a new key, so their first call after
  the upgrade is a miss. All other keys are unchanged.
* **Connections and fork.** The SQLite connections of threads that have
  exited are closed by :meth:`close <diskcache_community.Cache.close>` and
  when the cache is garbage collected. A child process created with
  ``fork()`` opens new connections instead of using the parent's.
* **FanoutCache.** ``hasattr`` works on a :class:`FanoutCache
  <diskcache_community.FanoutCache>`, and ``get`` and ``pop`` return the
  documented tuple when a shard times out.
* **Default disk.** The ``disk`` arguments default to ``None``, which means
  the type :func:`default_disk <diskcache_community.default_disk>` returns.
  That is :class:`Disk <diskcache_community.Disk>`, as before, unless the
  process sets ``DISKCACHE_DISK`` or calls :func:`configure
  <diskcache_community.configure>`.

The fork also adds features that change nothing until you use them:
:class:`SafeDisk <diskcache_community.SafeDisk>` for caches that untrusted
users can write to, ``store_time=True`` on ``get``, ``iterkeys(tag=...)`` and
:meth:`Disk.with_options <diskcache_community.Disk.with_options>` for entries
that cannot be read. To close CVE-2025-69872 after migrating, see
:doc:`fix-cve-2025-69872`.

Going back
----------

Install ``diskcache==5.6.3`` and change the imports back. Cache directories
written by the fork open with 5.6.3, including entries written through
:class:`SafeDisk <diskcache_community.SafeDisk>`, which are ordinary pickles.
A disk class of your own needs an equivalent subclass of ``diskcache.Disk``.
