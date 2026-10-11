# Changelog

diskcache-community forked from DiskCache at upstream commit ebfa37c (3 March 2024), two commits after the 5.6.3 release. Each entry names the pull request in this repository; imported upstream pull requests name their original author.

## Unreleased

- Replace the upstream CI with one `ci.yml` workflow: lint checks, tests on Python 3.10 to 3.14 on Linux, macOS and Windows, Django 4.2 and 6.0 jobs, and an import check without Django (#1).
- Move packaging from `setup.py` to `pyproject.toml` under the distribution name `diskcache-community`; the import name stays `diskcache`. Includes upstream grantjenks/python-diskcache#326 by @akx, which removes the `setup.py test` command (#2).
- Add the fork notice and migration steps to the README, plus `NOTICE`, `SECURITY.md`, `CONTRIBUTING.md` and this changelog; point the documentation and repository links at this fork and remove the upstream analytics, logo and funding links from the docs (this PR).
