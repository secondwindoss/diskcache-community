# Changelog

diskcache-community forked from DiskCache at upstream commit ebfa37c (3 March 2024), two commits after the 5.6.3 release. Each entry names the pull request in this repository. Imported upstream pull requests are referenced by number, and their commits keep their original authors in the git history.

## Unreleased

### Packaging

- The package ships type information: `py.typed` and `.pyi` stubs covering the API, including `SafeDisk`, `SafeDisk.with_types`, `Disk.with_options`, `configure`, `default_disk`, `ReadOnlyError`, `read_only`, `store_time`, `iterkeys(tag=...)` and the `disk` arguments of `Deque`, `Index` and `FanoutCache.deque` and `index`, so mypy and pyright check code that uses the fork without a separate stubs package. `mypy.stubtest` reports no differences from the runtime (PR #29).
- `requires-python` is `>=3.9`, so the fork installs on Python 3.9; the test suite passes there unchanged (PR #29).

## 5.8.0 (2026-10-18)

The package is now imported as `diskcache_community`, so it installs next to the upstream `diskcache` package instead of replacing it. The `cache.db` schema, the file layout, the serialization modes, the memoize key format and the persisted settings are unchanged, so a 5.6.3 process opens a directory written by 5.8.0 and the reverse. `SafeDisk` stays opt-in and gains an allowlist for your own classes, a process-wide default disk selects it for caches that libraries create, and caches can treat unreadable entries as missing.

### Security

- `SafeDisk.with_types(*types, modules=())` returns a `SafeDisk` subclass whose allowlist adds the given classes, matched by identity, and every class defined in the named modules or below them. A module name may only reach a class defined in that module: a dotted name such as `os.system`, reached through a module that imports `os`, a class the module merely imports, a module and a dunder attribute are refused, and reading never imports a module, so a pickle cannot run a module's top-level code. numpy classes are refused (`UNSAFE_MODULES`), because numpy restores a dtype's flags from the pickle without checking them and a crafted array pickle can corrupt memory. Writes stay exact: a value outside the standard-library types is pickled and the names its pickle looks up are checked against the same allowlist, so a value the reader would refuse raises `TypeError` naming the class before anything is written. Calling `with_types` again adds to the allowlist, and a `Cache`, `FanoutCache`, `Deque`, `Index` or `DjangoCache` using the returned class pickles as before. The plain `SafeDisk` is unchanged (PR #23).

### Docs

- `SECURITY.md` describes what 5.8.0 adds for CVE-2025-69872 and links the steps (PR #28).
- Two new pages: "Fix CVE-2025-69872 in diskcache" gives the steps to read caches with `SafeDisk`, including caches that libraries create, your own classes and entries already in the cache, and lists what any restricted disk has to cover; "Migrating from diskcache 5.6.3" covers the dependency, imports, Django settings, running next to upstream `diskcache`, the behaviour changes since 5.6.3 and going back. Both open the documentation and are linked from the README (PR #27).
- A new benchmarks page, measured on 2026-10-12, compares diskcache-community with diskcache 5.6.3, memcached, Redis, lmdb, sqlitedict, shelve and the Django cache backends, with four charts. The scripts that produce it are in `tests/benchmarks` (`driver.py` runs the stores, `report.py` writes the page and charts from the JSON results). The 2019 pages from upstream stay as the old benchmarks, labelled as such and linked from the new page, and the README header, features and documentation list link to the new page (PR #26).
- Shared links show a project card: a social preview image in `.github/`, and Open Graph tags on the documentation through `sphinxext-opengraph` (PR #21).
- A logo: the README opens with a centered header (logo, name, tagline, links, badges) in the style of the other community forks, and the documentation shows the logo and a favicon (PR #20).
- The README is rewritten in Markdown around install, usage and the fork story; the comparison tables move to a new `comparisons` page in the documentation, which gets its own landing page, and the 2016 testimonials are dropped (PR #19).
- The documentation is published on Read the Docs at https://diskcache-community.readthedocs.io/, built from `master` on every push; the README links point there instead of at the `.rst` sources (PR #18).

### Features

- `Disk.with_options(on_error='miss')` returns a disk type, on any disk class including `SafeDisk` and the classes `with_types` returns, whose caches delete an entry they find but cannot read back (a corrupt or stale pickle, a refused type, a path outside the cache, an undecodable text file) and treat it as missing: `get` returns its default, `cache[key]` raises `KeyError`, `pop`, `pull`, `peek` and `peekitem` move on, and iteration skips unreadable keys. `Index.items()` and `values()` skip such entries too. The first such entry per cache is logged as a warning on the `diskcache_community` logger; a read-only cache does not delete it, and its `peek` and `peekitem` raise. A missing value file, `MemoryError` and `RecursionError` are never treated as unreadable. The default, `on_error='raise'`, keeps raising as before, and the option is a class attribute that is never persisted (PR #25).
- `configure(disk)` sets the disk type of every `Cache`, `FanoutCache`, `Deque`, `Index` and `DjangoCache` created afterwards without a disk, and `default_disk()` returns the type in effect. Without `configure`, the environment decides: `DISKCACHE_DISK=safe` selects `SafeDisk`, with `DISKCACHE_SAFE_TYPES` and `DISKCACHE_SAFE_MODULES` passed to `SafeDisk.with_types`, and `DISKCACHE_DISK` also takes `default` or the import path of a disk class. A disk passed explicitly always wins, so libraries that choose their own disk keep it; caches that already exist keep theirs, and nothing is persisted. The `disk` arguments now default to `None`, meaning that type (PR #24).

### Packaging

- **Breaking:** the package is imported as `diskcache_community` instead of `diskcache`, so it installs next to the upstream `diskcache` distribution without overwriting it, and a project can move to the fork while other dependencies still require `diskcache`. The public API, the `cache.db` schema, the file layout and the serialization are unchanged, so cache directories are shared with 5.6.3 in both directions. Django settings name `diskcache_community.DjangoCache` and `diskcache_community.SafeDisk`. The import-time warning about an upstream `diskcache` installed in the same environment is gone, and a CI job installs both distributions together, runs the golden tests in both directions and checks that uninstalling either leaves the other working (PR #22).
- `LICENSE` now holds the full Apache License 2.0 text instead of the short boilerplate notice, so GitHub and package indexes detect the license; the copyright and fork notice stay in `NOTICE` (PR #21).

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
