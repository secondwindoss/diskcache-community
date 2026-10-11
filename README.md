# DiskCache

**Disk and file backed persistent cache for Python, built on SQLite. Pure Python, thread-safe, process-safe, with a Django backend.**

[![PyPI](https://img.shields.io/pypi/v/diskcache-community.svg)](https://pypi.org/project/diskcache-community/)
[![Python versions](https://img.shields.io/pypi/pyversions/diskcache-community.svg)](https://pypi.org/project/diskcache-community/)
[![CI](https://github.com/secondwindoss/diskcache-community/actions/workflows/ci.yml/badge.svg)](https://github.com/secondwindoss/diskcache-community/actions/workflows/ci.yml)
[![Documentation](https://app.readthedocs.org/projects/diskcache-community/badge/?version=latest)](https://diskcache-community.readthedocs.io/en/latest/)
[![License](https://img.shields.io/pypi/l/diskcache-community.svg)](https://github.com/secondwindoss/diskcache-community/blob/master/LICENSE)

> [!IMPORTANT]
> This is a community fork of [python-diskcache](https://github.com/grantjenks/python-diskcache),
> whose last release was 5.6.3 in August 2023. It is published on PyPI as
> `diskcache-community` and still imported as `diskcache`. It carries the
> fix path for [CVE-2025-69872](https://github.com/advisories/GHSA-w8v5-vhqr-4h9v)
> and stays compatible with existing 5.6.3 cache directories.
> See [Why this fork](#why-this-fork) and [Migrating from diskcache](#migrating-from-diskcache).

## Install

```sh
pip install diskcache-community
```

If the upstream `diskcache` package is already installed, remove it first.
Both distributions write to the same `diskcache/` package directory and
cannot coexist; see [Migrating from diskcache](#migrating-from-diskcache).

## Usage

```python
from diskcache import Cache

cache = Cache('cache')                 # the directory is created with mode 0700
cache.set('answer', 42, expire=3600, tag='math')
cache['config'] = {'debug': False}
cache.get('answer')                    # 42
cache.get('missing', default=None)
cache.evict('math')                    # delete every key tagged 'math'
```

Memoize function results across processes and restarts:

```python
@cache.memoize(expire=600, ignore={'session'})
def fetch(url, session):
    return session.get(url).text
```

Shard across several SQLite files for higher write throughput, and plug the
same cache into Django:

```python
from diskcache import FanoutCache

cache = FanoutCache('cache', shards=8, timeout=1)
```

```python
# settings.py
CACHES = {
    'default': {
        'BACKEND': 'diskcache.DjangoCache',
        'LOCATION': '/var/tmp/django_cache',
        'SHARDS': 8,
        'DISK': 'diskcache.SafeDisk',  # restricted unpickling, see below
    }
}
```

Caches shared with untrusted writers should use `SafeDisk`, which unpickles
only a fixed set of built-in types and keeps file reads inside the cache
directory:

```python
from diskcache import Cache, SafeDisk

cache = Cache('cache', disk=SafeDisk)
```

## Features

- `Cache`, `FanoutCache` and `DjangoCache` for key-value caching with
  expiry, tags, size limits and LRU, LFU and other eviction policies
- `Deque` and `Index`: persistent, cross-process `collections.deque` and `dict`
- Recipes for memoization with stampede prevention, cross-process locks,
  semaphores and throttling
- Thread-safe and process-safe, with fork-safe connection handling
- Read-only mode, automatic when the directory is not writable
- Opt-in `SafeDisk` for caches whose directory other users can write to
- Pure Python on top of the standard library `sqlite3`; no server, no compiler
- Tested on CPython 3.10 to 3.14 on Linux, macOS and Windows, with
  [benchmarks](https://diskcache-community.readthedocs.io/en/latest/cache-benchmarks.html)
  against the alternatives

## Why this fork

The upstream project stopped releasing after 5.6.3 (August 2023) and its last
commit landed in March 2024. In 2025, CVE-2025-69872 was published against
every released version: the cache reads pickled values with `pickle.load`, so
anyone who can write into the cache directory can run code in the process
that reads from it. The package still works, but scanners flag it and there
is no fixed upstream version.

This fork publishes the same library as `diskcache-community` and fixes it in
two steps. Version 5.7.0 keeps the `cache.db` schema, the file layout, the
serialization modes and the memoize key format unchanged, so a 5.6.3 process
opens a directory written by this fork and the reverse. It adds the opt-in
`SafeDisk`, creates cache directories with mode `0700`, opens read-only
directories read-only, closes the per-thread SQLite connections it used to
leak, and survives `fork`. Version 6.0.0 will make safe reading the default.
The [changelog](CHANGELOG.md) lists every change and
[SECURITY.md](SECURITY.md) describes what is and is not fixed.

DiskCache was written and maintained by Grant Jenks from 2016 to 2023. This
fork keeps his license, copyright and author credit; see [NOTICE](NOTICE).

## Migrating from diskcache

The import name and the public API are unchanged, so no code changes are
needed. Only the distribution changes:

```sh
pip uninstall diskcache
pip install diskcache-community
```

Never keep both installed. Uninstalling either one deletes the shared
package directory, and the fork warns at import time when both are present.
If `diskcache` arrives through a dependency, exclude it. With uv:

```toml
[tool.uv]
exclude-dependencies = ["diskcache"]
```

With pip, install the dependent with `--no-deps` or exclude `diskcache` in a
constraints file.

## Documentation

The documentation is at
[diskcache-community.readthedocs.io](https://diskcache-community.readthedocs.io/en/latest/):

- [Tutorial](https://diskcache-community.readthedocs.io/en/latest/tutorial.html)
- [API reference](https://diskcache-community.readthedocs.io/en/latest/api.html)
- [Cache benchmarks](https://diskcache-community.readthedocs.io/en/latest/cache-benchmarks.html)
  and [DjangoCache benchmarks](https://diskcache-community.readthedocs.io/en/latest/djangocache-benchmarks.html)
- [Comparisons](https://diskcache-community.readthedocs.io/en/latest/comparisons.html)
  with other key-value stores and caching libraries
- Case studies:
  [web crawler](https://diskcache-community.readthedocs.io/en/latest/case-study-web-crawler.html),
  [landing page caching](https://diskcache-community.readthedocs.io/en/latest/case-study-landing-page-caching.html)
- [Development](https://diskcache-community.readthedocs.io/en/latest/development.html)

## Comparison

| | diskcache | dbm | shelve | sqlitedict | pickleDB |
|---|---|---|---|---|---|
| Atomic | Always | Maybe | Maybe | Maybe | No |
| Thread-safe | Yes | No | No | Yes | No |
| Process-safe | Yes | No | No | Maybe | No |
| Eviction | LRU, LFU, more | None | None | None | None |
| Serialization | Customizable | None | Pickle | Customizable | JSON |
| Data types | Mapping, deque | Mapping | Mapping | Mapping | Mapping |

The full [comparisons page](https://diskcache-community.readthedocs.io/en/latest/comparisons.html)
covers features, quality and timings in detail.

## Contributing and security

Bug reports and pull requests are welcome on
[GitHub](https://github.com/secondwindoss/diskcache-community/issues).
[CONTRIBUTING.md](CONTRIBUTING.md) explains the compatibility contract and
how to run the tests. Report vulnerabilities privately as described in
[SECURITY.md](SECURITY.md).

## License

Copyright 2016-2023 Grant Jenks. Modifications in this fork are copyright
2026 diskcache-community contributors. Licensed under the
[Apache License, Version 2.0](LICENSE).
