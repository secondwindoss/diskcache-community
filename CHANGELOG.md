# Changelog

diskcache-community forked from DiskCache at upstream commit ebfa37c (3 March 2024), two commits after the 5.6.3 release. Each entry names the pull request in this repository. Imported upstream pull requests are referenced by number, and their commits keep their original authors in the git history.

## Unreleased

### Docs

- The README is rewritten in Markdown around install, usage and the fork story; the comparison tables move to a new `comparisons` page in the documentation, which gets its own landing page, and the 2016 testimonials are dropped (PR #19).
- The documentation is published on Read the Docs at https://diskcache-community.readthedocs.io/, built from `master` on every push; the README links point there instead of at the `.rst` sources (PR #18).

## 5.7.0 (2026-10-11)

First release under the `diskcache-community` name: upstream commit ebfa37c plus the changes below. The import name stays `diskcache`; the `cache.db` schema, the file layout, the serialization modes, the memoize key format and the persisted settings are unchanged, so a 5.6.3 process opens a directory written by 5.7.0 and the reverse.

### Security

- Add `SafeDisk`, an opt-in `Disk` for CVE-2025-69872: it unpickles only an allowlist of standard-library types, raises `TypeError` at write time for anything the allowlist could not read back, and confines the paths read from the `filename` column to the cache directory. `Deque` and `Index` take a `disk` argument, `FanoutCache.cache()`, `deque()` and `index()` honour theirs, and the Django backend gains a `DISK` option. The default `Disk` is unchanged, so every 5.6.3 cache keeps opening (#11).
- Create every directory the cache makes with mode `0700`, including missing parents and the value subdirectories, and leave existing directories alone; includes upstream pull request 359 (#7).
- Warn at import time when the upstream `diskcache` distribution is installed next to `diskcache-community`, since both own the same package directory (#9).

### Features

- Read-only caches (upstream issue 113): opening an existing cache writes nothing unless a setting differs from the stored one, so a `cache.db` snapshot stays byte-identical across runs; a cache whose database or directory is not writable opens read-only, as does `Cache(directory, read_only=True)`, with reads, iteration, `check()` and memoize hits working and every write raising `ReadOnlyError`, a subclass of `sqlite3.OperationalError` (#17).
- `store_time=True` on `Cache.get`, `FanoutCache.get` and `DjangoCache.get` appends the store time to the returned tuple after any other requested metadata (upstream issue 330) (#16).
- `Cache.iterkeys(tag=...)` iterates the keys with a given tag, using the tag index when enabled; includes upstream pull request 372 (upstream issue 341) (#16).

### Fixes

- Support SQLite builds compiled with `SQLITE_DQS=0`, such as conda-forge's sqlite builds of early 2025: single-quoted literals in the `Settings` triggers and statistics counters (upstream pull request 311), and caches written by earlier versions get their triggers rewritten on first open when the stored text differs (#3).
- `FanoutCache.__getattr__` raises `AttributeError`, so `hasattr()` works (upstream pull request 366), and `FanoutCache.get` and `pop` return the documented tuple when a shard times out (upstream pull request 367) (#3).
- Write bytes values without the `io.BytesIO` copy (upstream pull request 333) and fix a README typo (upstream pull request 365) (#3).
- Accept either path separator in stored filenames, so a cache written on Windows opens on other systems and `check()` stays clean across platforms (#6).
- A parameter name in the `ignore` set of `memoize` matches the argument whether it is passed positionally or by keyword; keys of calls that do not pass an ignored parameter positionally are unchanged (#8).
- Close the SQLite connections of threads that have exited, from `close()` and when a `Cache` is garbage collected; keep connections inherited across `fork()` unused in the child, as SQLite requires, and let `fork()` wait for transactions in flight in other threads (upstream issues 295, 325 and 336; upstream pull request 299 was not taken because it serializes every transaction) (#13).

### Packaging

- Move packaging from `setup.py` to `pyproject.toml` under the distribution name `diskcache-community`; the import name stays `diskcache`. Includes upstream pull request 326, which removes the `setup.py test` command (#2).

### Docs

- Add the fork notice and migration steps to the README, plus `NOTICE`, `SECURITY.md`, `CONTRIBUTING.md` and this changelog; point the documentation and repository links at this fork and remove the upstream analytics, logo and funding links from the docs (#4).
- Record the changes in this changelog and extend the README fork notice (#12).

### Tests and CI

- Replace the upstream CI with one `ci.yml` workflow: lint checks, tests on Python 3.10 to 3.14 on Linux, macOS and Windows, Django 4.2 and 6.0 jobs, and an import check without Django (#1).
- Add golden compatibility fixtures written by diskcache 5.6.3 for every container, eviction policy, tag index, statistics, `JSONDisk`, memoized calls and file-backed values, with tests that read them with the current code and a reverse-direction test that reads a fork-written cache with 5.6.3 (#5).
- Run the test suite in CI against a SQLite built from source with `SQLITE_DQS=0` (#10).
- Rework the release workflow: tag-version check, build and twine check, TestPyPI dry run by dispatch, PyPI publish through trusted publishing behind the `pypi` environment, and a GitHub release with this changelog section (#14).
- Make the `incr` and `decr` expiry tests and the Django tests deterministic under pytest-xdist, so slow runners no longer fail them (#15).
