# Security

## Supported versions

Security fixes go into the latest 5.x release of diskcache-community only. There are no maintenance branches for older releases; if you are on an older release, upgrade to the latest one.

## Reporting a vulnerability

Do not open a public issue for a security problem. Report it privately through GitHub's private vulnerability reporting on this repository: https://github.com/secondwindoss/diskcache-community/security/advisories/new. Include the version you tested, what the problem is and, if you can, how to reproduce it.

You will hear back within a week. A confirmed problem is fixed in the next release, and the advisory is published once the fix is out. If you do not get a reply in that time, open an issue that says only that you have sent a report, without details.

## CVE-2025-69872

[CVE-2025-69872](https://github.com/advisories/GHSA-w8v5-vhqr-4h9v) (CWE-502) affects every released version of the upstream `diskcache` package, 5.6.3 included, and no fixed upstream version exists. The cache stores Python objects as pickles, in the `cache.db` database and in the `.val` files next to it, and reads them back with `pickle.load`. Anyone who can write into the cache directory can therefore run code in every process that reads from it. The process itself is not otherwise affected: the package installs and works as before.

Where this fork stands:

- 5.7.0, the first release of this fork, reads pickles with the default `Disk` exactly as 5.6.3 does, so it opens every 5.6.3 cache. It adds an opt-in `SafeDisk` that unpickles only an allowlist of standard-library types, rejects anything outside it at write time and confines value paths to the cache directory; `Cache`, `FanoutCache`, `Deque` and `Index` take it through `disk=SafeDisk` and the Django backend through the `DISK` option. New cache directories are created with mode `0700`.
- 6.0.0 makes safe reading the default and turns the trusted-pickle behaviour into an explicit choice, with a migration guide.

Until you run a version where safe reading is the default or you have opted into it, treat the cache directory as trusted input: keep it on local storage that only the user running the process can write to, and do not share it with other accounts.

A note on scanners: vulnerability scanners match on the distribution name, so `pip-audit`, Dependabot and similar tools report nothing for `diskcache-community` even though the default `Disk` in 5.7.0 behaves as it did in 5.6.3. A clean scan is not evidence that this issue is fixed. Use the list above instead, and the release notes of the version you run.

## Dependencies

The library has no runtime dependencies. Advisories for the development and CI dependencies are tracked through Dependabot alerts on this repository.
