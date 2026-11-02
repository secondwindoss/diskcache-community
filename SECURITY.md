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
- 5.8.0 is imported as `diskcache_community`, next to the upstream `diskcache` package. `SafeDisk.with_types` allows your own classes and the classes defined in named modules while everything else stays refused; numpy classes cannot be allowed, because numpy unpickling is not memory-safe. `configure()` and `DISKCACHE_DISK=safe` select `SafeDisk` for caches created without a disk, including those that libraries create through `diskcache_community`. `Disk.with_options(on_error='miss')` deletes entries that cannot be read and treats them as missing. The steps are in [Fix CVE-2025-69872 in diskcache](https://diskcache-community.readthedocs.io/en/latest/fix-cve-2025-69872.html).
- `JSONDisk` writes no pickles but still reads one from a crafted row, as it does in 5.6.3. `SafeJSONDisk` reads and writes the same files and never reads a pickle; `SafeDisk` does not decode what `JSONDisk` wrote.
- `SafeDisk.with_numpy()` returns a `SafeDisk` that also stores numpy arrays, in the `.npy` format rather than as pickles. numpy pickles stay refused, because unpickling an array is not memory-safe.
- The default stays as it is. Existing caches hold objects outside any allowlist, such as instances of your own classes, Django responses and the keys of `memoize(typed=True)`, so `SafeDisk` remains an explicit choice.

## Dependencies

The library has no runtime dependencies. Advisories for the development and CI dependencies are tracked through Dependabot alerts on this repository.
