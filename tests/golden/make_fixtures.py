"""Write the golden fixture caches and pack them into the archive.

Run this with an interpreter whose ``diskcache`` is the upstream 5.6.3 wheel,
from a working directory outside the repository, so that the repository
cannot shadow the wheel::

    $ cd /tmp
    $ /path/to/venv-5.6.3/bin/python -I \\
          /path/to/repo/tests/golden/make_fixtures.py

The script refuses to run unless the imported diskcache is 5.6.3 and comes
from site-packages, writes every cache described in ``recipe.py``, verifies
its own output with the same interpreter, and writes a reproducible
``diskcache-5.6.3.tar.gz`` next to this file.
"""

import argparse
import datetime
import gzip
import io
import os
import os.path as op
import platform
import sqlite3
import sys
import tarfile
import tempfile
import time
from pathlib import Path

if __name__ == '__main__':
    import diskcache
else:
    import diskcache_community as diskcache

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    # Running as a script from outside the repository: make the recipe
    # importable under its package name without shadowing diskcache.
    sys.path.append(str(REPO_ROOT))

from tests.golden import recipe, verify  # noqa: E402

HERE = Path(__file__).resolve().parent
ARCHIVE_MTIME = 1693440000  # 2023-08-31, the release date of 5.6.3


def _expire(marker):
    if marker is None:
        return None
    return marker - time.time()


def write_dataset(cache):
    """Store the standard dataset in `cache` (a Cache or FanoutCache)."""
    for key, value, tag, expire in recipe.live_entries():
        cache.set(key, value, expire=_expire(expire), tag=tag)
    for key, delta, default, times in recipe.COUNTERS:
        for _ in range(times):
            cache.incr(key, delta, default)
    recipe.ALLOW_COMPUTE = True
    try:
        memoized = cache.memoize()(recipe.golden_square)
        for number in recipe.MEMOIZE_ARGS:
            memoized(number)
    finally:
        recipe.ALLOW_COMPUTE = False


def write_expired(cache):
    """Store the entries that must be expired by the time they are read."""
    for key, value, tag, _ in recipe.expired_entries():
        cache.set(key, value, expire=recipe.EXPIRE_SECONDS, tag=tag)


def write_cache(path, **settings):
    with diskcache.Cache(path, **settings) as cache:
        write_dataset(cache)
        write_expired(cache)


def write_statistics(path):
    with diskcache.Cache(path, statistics=True) as cache:
        for key, value in recipe.STATS_ITEMS:
            cache.set(key, value)
        for key, _ in recipe.STATS_ITEMS:
            cache.get(key)
        for key in recipe.STATS_MISSES:
            cache.get(key)


def write_jsondisk(path):
    with diskcache.Cache(
        path, disk=diskcache.JSONDisk, **recipe.JSON_SETTINGS
    ) as cache:
        for key, value in recipe.JSON_ENTRIES:
            cache.set(key, value)


def write_fanout(path):
    shards = recipe.FANOUT_SHARDS
    with diskcache.FanoutCache(path, shards=shards) as cache:
        write_dataset(cache)
        sub = cache.cache('sub')
        for key, value in recipe.SUB_CACHE_ITEMS:
            sub.set(key, value)
        deque = cache.deque('dq')
        deque.extend(recipe.DEQUE_ITEMS)
        index = cache.index('ix')
        index.update(recipe.INDEX_ITEMS)
        write_expired(cache)
        sub.close()
        deque.cache.close()
        index.cache.close()


def write_deque(path):
    deque = diskcache.Deque(recipe.DEQUE_ITEMS[1:], directory=path)
    deque.appendleft(recipe.DEQUE_ITEMS[0])
    deque.cache.close()


def write_index(path):
    index = diskcache.Index(path, recipe.INDEX_ITEMS)
    index.cache.close()


def write_all(root):
    """Write every fixture cache below `root`."""
    root = str(root)
    write_cache(op.join(root, recipe.DIR_DEFAULT))
    write_cache(op.join(root, recipe.DIR_TAG_INDEX), tag_index=True)
    for policy in recipe.EVICTION_POLICIES:
        path = op.join(root, recipe.DIR_POLICY.format(policy))
        write_cache(path, eviction_policy=policy)
    write_statistics(op.join(root, recipe.DIR_STATISTICS))
    write_cache(
        op.join(root, recipe.DIR_SETTINGS), **recipe.SETTINGS_OVERRIDES
    )
    write_jsondisk(op.join(root, recipe.DIR_JSONDISK))
    write_fanout(op.join(root, recipe.DIR_FANOUT))
    write_deque(op.join(root, recipe.DIR_DEQUE))
    write_index(op.join(root, recipe.DIR_INDEX))


def write_provenance(root):
    """Record what wrote the fixtures."""
    now = datetime.datetime.now(datetime.timezone.utc)
    lines = [
        'diskcache %s' % diskcache.__version__,
        'wheel %s sha256 %s' % (recipe.WHEEL_FILENAME, recipe.WHEEL_SHA256),
        'python %s' % platform.python_version(),
        'sqlite %s' % sqlite3.sqlite_version,
        'platform %s' % platform.platform(),
        'pickle protocol %d' % recipe.WRITER_PICKLE_PROTOCOL,
        'written %s' % now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        '',
    ]
    with open(op.join(root, recipe.PROVENANCE), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def assert_closed(root):
    """Abort if any SQLite write-ahead log or shared memory file remains."""
    for dirpath, _, files in os.walk(root):
        for name in files:
            if name.endswith(('-wal', '-shm', '-journal')):
                sys.exit(
                    'open database left behind: %s' % op.join(dirpath, name)
                )


def pack(root, archive):
    """Write `root` into `archive` as ARCHIVE_ROOT with fixed metadata."""
    entries = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            full = op.join(dirpath, name)
            rel = op.relpath(full, root).replace(os.sep, '/')
            entries.append((full, recipe.ARCHIVE_ROOT + '/' + rel))
    buffer = io.BytesIO()
    with gzip.GzipFile(filename='', mode='wb', fileobj=buffer, mtime=0) as gz:
        with tarfile.open(
            fileobj=gz, mode='w', format=tarfile.PAX_FORMAT
        ) as tar:
            for full, arcname in entries:
                info = tar.gettarinfo(full, arcname)
                info.uid = info.gid = 0
                info.uname = info.gname = ''
                info.mtime = ARCHIVE_MTIME
                info.mode = 0o644
                with open(full, 'rb') as f:
                    tar.addfile(info, f)
    with open(archive, 'wb') as f:
        f.write(buffer.getvalue())
    return len(entries), len(buffer.getvalue())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument(
        '--output',
        default=str(HERE / recipe.ARCHIVE),
        help='archive to write (default: %(default)s)',
    )
    parser.add_argument(
        '--expect-version',
        default=recipe.WHEEL_VERSION,
        help='required diskcache version (default: %(default)s)',
    )
    args = parser.parse_args(argv)
    verify.require_version(args.expect_version)

    with tempfile.TemporaryDirectory(prefix='golden-') as root:
        write_all(root)
        time.sleep(recipe.EXPIRE_SECONDS + 0.5)
        verify.verify_all(root)
        write_provenance(root)
        assert_closed(root)
        count, size = pack(root, args.output)

    print(
        'wrote %s: %d files, %d bytes, written by diskcache %s from %s'
        % (args.output, count, size, diskcache.__version__, diskcache.__file__)
    )


if __name__ == '__main__':
    main()
