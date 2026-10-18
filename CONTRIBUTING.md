# Contributing

diskcache-community is a community fork of [DiskCache](https://github.com/grantjenks/python-diskcache). Bug reports, fixes and small, focused features are welcome. For anything larger, open an issue first so the approach can be agreed before the work is done.

## Setting up

Clone the repository, create a virtual environment and install the package in editable mode together with the test dependencies. The commands below use [uv](https://docs.astral.sh/uv/); `python -m venv` and `pip` work the same way, and `pip install -r requirements-dev.txt` installs everything the linters and benchmarks need as well.

```bash
uv venv
uv pip install -e . "django==4.2.*" pytest pytest-cov pytest-django pytest-xdist
```

## Running tests

`pytest` reads its options from the `[pytest]` section of `tox.ini`: tests run in parallel with `-n auto`, branch coverage of the `diskcache` package must stay at 98 % or above, and the doctests in `docs/*.rst` run as part of the suite. The Django tests need two environment variables, which `tox` sets for you:

```bash
DJANGO_SETTINGS_MODULE=tests.settings PYTHONPATH=. pytest
```

`tox -e py` does the same in a fresh environment. The suite takes about ten seconds.

## Linting

The lint checks run as tox environments, and CI runs each of them:

```bash
tox -e bluecheck,isortcheck,flake8,mypy,pylint,doc8,rstcheck,docs
```

`blue` and `isort` format the code (`tox -e blue,isort` applies the formatting), `flake8`, `mypy` and `pylint` check it, `doc8` and `rstcheck` check the reStructuredText, and `docs` builds the Sphinx documentation.

## How changes land

Work on a branch and open a pull request against `master`. CI runs the lint checks, the test suite on Python 3.10 to 3.14 on Linux, macOS and Windows, the Django 4.2 and 6.0 jobs and an import check without Django, and a pull request merges once CI is green and the change has been reviewed. Keep each pull request to one change, and write commit subjects as one sentence that says what the change does. In the description, say what was wrong, list the concrete changes, and say what you ran to check them.

Fixes imported from upstream pull requests keep their original commits and authors; the description says which upstream pull request is imported. Entries for merged changes go into [CHANGELOG.md](CHANGELOG.md) under `Unreleased`.

## Compatibility contract

This fork publishes the same library under a new distribution name, `diskcache-community`, and a new import name, `diskcache_community`, so it installs next to the upstream `diskcache` package. The following stay as upstream left them, and a change to any of them is a compatibility break that needs a major version:

- the import name, `import diskcache_community` (it replaced `import diskcache` in 5.8.0, before any dependent used the fork), and the public API exported by `diskcache_community/__init__.py`;
- the `cache.db` schema: the `Settings` and `Cache` tables, the value modes 1 to 4, and the index and trigger names;
- the directory layout: `<dir>/ab/cd/<28 hex>.val` for values and `%03d` for `FanoutCache` shards;
- the `RAW`, `BINARY`, `TEXT` and `PICKLE` serialization and the bytes `JSONDisk` writes;
- the key format `memoize` derives from a call;
- the persisted `Settings` keys; no new `disk_*` or `Settings` key before 6.0.0.

A process running 5.6.3 must be able to open a directory written by this fork, and the reverse. Golden fixtures written by the 5.6.3 wheel guard this in the test suite.
