Golden Compatibility Fixtures
=============================

``diskcache-5.6.3.tar.gz`` holds caches written by the last upstream release,
diskcache 5.6.3 from PyPI, so that every later change to the on-disk format,
the serialization, the schema object names or the memoize key format shows up
as a failing test. ``tests/test_golden.py`` opens each cache with the current
code and ``tests/golden/verify.py`` asserts what it must contain.

Contents, all described by ``recipe.py``:

- ``cache-default``: a ``Cache`` with default settings holding the standard
  dataset (raw and pickled keys, raw, pickled and file-backed values, tags,
  future and already expired rows, counters and memoized results).
- ``cache-tag-index``: the same dataset with ``tag_index=True``.
- ``cache-policy-<policy>``: the same dataset under each eviction policy.
- ``cache-statistics``: three hits and two misses recorded with
  ``statistics=True``.
- ``cache-settings``: the same dataset with non-default ``size_limit``,
  ``cull_limit``, ``disk_min_file_size`` and ``disk_pickle_protocol``.
- ``cache-jsondisk``: JSON keys and values stored through ``JSONDisk``.
- ``fanout``: a four-shard ``FanoutCache`` with the dataset plus a sub-cache,
  a deque and an index.
- ``deque`` and ``index``: a standalone ``Deque`` and ``Index``.
- ``PROVENANCE.txt``: the wheel, Python and SQLite versions that wrote them.

Regenerating
------------

Only regenerate when the recipe changes. Install the upstream wheel in its own
environment and run the writer from outside the repository with ``-I``, so the
source tree cannot shadow the wheel::

    $ uv venv --python 3.12 /tmp/venv-563
    $ uv pip install --python /tmp/venv-563/bin/python diskcache==5.6.3
    $ cd /tmp
    $ /tmp/venv-563/bin/python -I /path/to/repo/tests/golden/make_fixtures.py

The writer refuses any other diskcache version, verifies its own output with
the 5.6.3 wheel before packing, and writes the archive with fixed timestamps.

Reverse direction
-----------------

``test_current_code_writes_what_563_reads`` writes the same dataset with the
current code and reads it back with the 5.6.3 wheel. It runs only when the
environment variable ``DISKCACHE_GOLDEN_563_PYTHON`` points at an interpreter
that has the 5.6.3 wheel installed::

    $ DISKCACHE_GOLDEN_563_PYTHON=/tmp/venv-563/bin/python pytest tests/test_golden.py
