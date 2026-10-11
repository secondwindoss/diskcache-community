"""Assertions shared by the golden tests, the fixture writer and the reverse
check.

Every function opens a fixture cache read-only (apart from the access-time
bookkeeping of the eviction policies) and raises AssertionError on the first
mismatch. The module runs under the current code when imported by pytest and
under the upstream 5.6.3 wheel when executed as a script from outside the
repository, which is how the writer checks its own output and how the reverse
test reads caches written by the current code.
"""

import argparse
import os
import os.path as op
import sys
from pathlib import Path

import diskcache

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    # Running as a script from outside the repository: make the recipe
    # importable under its package name without shadowing diskcache.
    sys.path.append(str(REPO_ROOT))

from tests.golden import recipe  # noqa: E402

MISSING = object()


def _schema_names(cache, kind):
    query = 'SELECT name FROM sqlite_master WHERE type = ?'
    rows = cache._sql(query, (kind,)).fetchall()
    return {name for (name,) in rows if not name.startswith('sqlite_')}


def check_clean(cache):
    """Assert Cache.check() finds nothing wrong with `cache`.

    The fixtures were written on a POSIX system, so the filename column holds
    '/'-separated relative paths. Windows opens those files fine, but
    Cache.check compares path strings and so reports every file-backed value
    as an unknown file (upstream issue #304). On Windows only that warning is
    accepted, and only for files that a row actually references.
    """
    warns = cache.check()
    if os.sep == '/':
        assert warns == [], [str(w.message) for w in warns]
        return
    rows = cache._sql(
        'SELECT filename FROM Cache WHERE filename IS NOT NULL'
    ).fetchall()
    known = {op.normpath(op.join(cache.directory, name)) for (name,) in rows}
    prefix = 'unknown file: '
    for warning in warns:
        message = str(warning.message)
        assert issubclass(warning.category, diskcache.UnknownFileWarning)
        assert message.startswith(prefix), message
        assert op.normpath(message[len(prefix) :]) in known, message


def check_schema(cache, policy, tag_index):
    """Assert the table, index and trigger names of a 5.6.3 cache."""
    assert _schema_names(cache, 'table') == recipe.TABLES
    indexes = set(recipe.BASE_INDEXES)
    if recipe.POLICY_INDEXES[policy]:
        indexes.add(recipe.POLICY_INDEXES[policy])
    if tag_index:
        indexes.add(recipe.TAG_INDEX)
    assert _schema_names(cache, 'index') == indexes
    assert _schema_names(cache, 'trigger') == recipe.TRIGGERS


def check_settings(cache, overrides):
    """Assert the persisted settings are the defaults plus `overrides`."""
    expected = dict(diskcache.DEFAULT_SETTINGS)
    expected['disk_pickle_protocol'] = recipe.WRITER_PICKLE_PROTOCOL
    expected.update(overrides)
    for key, value in expected.items():
        assert getattr(cache, key) == value, (key, getattr(cache, key), value)


def check_dataset(cache):
    """Assert the standard dataset reads back from `cache`.

    Works for Cache and FanoutCache alike.
    """
    assert len(cache) == recipe.ROW_COUNT, len(cache)
    assert cache.volume() > 0

    for key, value, tag, expire in recipe.live_entries():
        result, expire_time, read_tag = cache.get(
            key, default=MISSING, expire_time=True, tag=True
        )
        assert result is not MISSING, key
        assert result == value, key
        assert type(result) is type(value), key
        assert read_tag == tag, key
        if expire is None:
            assert expire_time is None, key
        else:
            assert abs(expire_time - expire) < recipe.EXPIRE_TOLERANCE, key
        assert key in cache

    for key, value, tag, expire in recipe.expired_entries():
        assert cache.get(key, default=MISSING) is MISSING, key
        assert key not in cache

    for key, delta, default, times in recipe.COUNTERS:
        assert cache.get(key) == recipe.counter_value(delta, default, times)

    memoized = cache.memoize()(recipe.golden_square)
    for number in recipe.MEMOIZE_ARGS:
        assert memoized.__cache_key__(number) == recipe.memoize_key(number)
        assert memoized(number) == number * number
        assert cache.get(recipe.memoize_key(number)) == number * number

    stored_keys = list(cache)
    assert len(stored_keys) == recipe.ROW_COUNT
    expected_keys = recipe.all_keys()
    for key in expected_keys:
        assert key in stored_keys, key
    for key in stored_keys:
        assert key in expected_keys, key

    check_clean(cache)


def verify_cache(path, policy='least-recently-stored', tag_index=0, **over):
    """Open the dataset cache at `path` and assert everything about it."""
    overrides = dict(over)
    overrides['eviction_policy'] = policy
    overrides['tag_index'] = tag_index
    with diskcache.Cache(path) as cache:
        check_settings(cache, overrides)
        check_schema(cache, policy, tag_index)
        check_dataset(cache)


def verify_statistics(path):
    """Assert the hit and miss counters persisted by the writer."""
    with diskcache.Cache(path) as cache:
        assert cache.statistics == 1
        hits, misses = cache.stats()
        assert (hits, misses) == (
            len(recipe.STATS_ITEMS),
            len(recipe.STATS_MISSES),
        ), (hits, misses)
        # Membership and iteration do not count as hits or misses, so the
        # counters stay as written and this check can run more than once.
        assert len(cache) == len(recipe.STATS_ITEMS)
        assert sorted(cache) == sorted(key for key, _ in recipe.STATS_ITEMS)
        for key, _ in recipe.STATS_ITEMS:
            assert key in cache, key
        for key in recipe.STATS_MISSES:
            assert key not in cache, key
        check_schema(cache, 'least-recently-stored', 0)
        check_clean(cache)


def verify_jsondisk(path):
    """Assert the JSONDisk cache reads back through JSONDisk."""
    with diskcache.Cache(path, disk=diskcache.JSONDisk) as cache:
        check_settings(cache, recipe.JSON_SETTINGS)
        assert isinstance(cache.disk, diskcache.JSONDisk)
        assert len(cache) == len(recipe.JSON_ENTRIES)
        for key, value in recipe.JSON_ENTRIES:
            result = cache.get(key, default=MISSING)
            assert result == value, key
            assert type(result) is type(value), key
        assert sorted(cache) == sorted(key for key, _ in recipe.JSON_ENTRIES)
        check_schema(cache, 'least-recently-stored', 0)
        check_clean(cache)


def verify_fanout(path):
    """Assert the FanoutCache dataset and its sub-containers."""
    shards = recipe.FANOUT_SHARDS
    with diskcache.FanoutCache(path, shards=shards) as cache:
        for number in range(shards):
            assert op.isdir(op.join(path, '%03d' % number)), number
        expected_limit = diskcache.DEFAULT_SETTINGS['size_limit'] / shards
        assert cache.size_limit == expected_limit
        check_dataset(cache)

        sub = cache.cache('sub')
        assert len(sub) == len(recipe.SUB_CACHE_ITEMS)
        for key, value in recipe.SUB_CACHE_ITEMS:
            assert sub.get(key, default=MISSING) == value, key
        check_clean(sub)

        deque = cache.deque('dq')
        assert list(deque) == list(recipe.DEQUE_ITEMS)
        check_clean(deque.cache)

        index = cache.index('ix')
        assert list(index.items()) == list(recipe.INDEX_ITEMS)
        check_clean(index.cache)

        sub.close()
        deque.cache.close()
        index.cache.close()


def verify_deque(path):
    """Assert the standalone Deque keeps its order and values."""
    deque = diskcache.Deque(directory=path)
    try:
        assert len(deque) == len(recipe.DEQUE_ITEMS)
        assert list(deque) == list(recipe.DEQUE_ITEMS)
        assert deque[0] == recipe.DEQUE_ITEMS[0]
        assert deque[-1] == recipe.DEQUE_ITEMS[-1]
        assert deque.cache.eviction_policy == 'none'
        check_schema(deque.cache, 'none', 0)
        check_clean(deque.cache)
    finally:
        deque.cache.close()


def verify_index(path):
    """Assert the standalone Index keeps its order, keys and values."""
    index = diskcache.Index(path)
    try:
        assert len(index) == len(recipe.INDEX_ITEMS)
        assert list(index.items()) == list(recipe.INDEX_ITEMS)
        for key, value in recipe.INDEX_ITEMS:
            assert index[key] == value, key
            assert type(index[key]) is type(value), key
        assert index.cache.eviction_policy == 'none'
        check_schema(index.cache, 'none', 0)
        check_clean(index.cache)
    finally:
        index.cache.close()


def verify_all(root):
    """Run every check against the fixture tree at `root`."""
    root = str(root)
    verify_cache(op.join(root, recipe.DIR_DEFAULT))
    verify_cache(op.join(root, recipe.DIR_TAG_INDEX), tag_index=1)
    for policy in recipe.EVICTION_POLICIES:
        verify_cache(op.join(root, recipe.DIR_POLICY.format(policy)), policy)
    verify_statistics(op.join(root, recipe.DIR_STATISTICS))
    verify_cache(
        op.join(root, recipe.DIR_SETTINGS), **recipe.SETTINGS_OVERRIDES
    )
    verify_jsondisk(op.join(root, recipe.DIR_JSONDISK))
    verify_fanout(op.join(root, recipe.DIR_FANOUT))
    verify_deque(op.join(root, recipe.DIR_DEQUE))
    verify_index(op.join(root, recipe.DIR_INDEX))


def require_version(version):
    """Abort unless the imported diskcache is `version` from site-packages."""
    location = Path(diskcache.__file__).resolve()
    if diskcache.__version__ != version:
        sys.exit(
            'expected diskcache %s, imported %s from %s'
            % (version, diskcache.__version__, location)
        )
    if REPO_ROOT in location.parents:
        sys.exit('diskcache was imported from the repository: %s' % location)


def main(argv=None):
    """Verify a fixture tree; used by the reverse-direction test."""
    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument('root', help='directory holding the fixture caches')
    parser.add_argument('--expect-version', help='required diskcache version')
    args = parser.parse_args(argv)
    if args.expect_version:
        require_version(args.expect_version)
    verify_all(args.root)
    print('verified %s with diskcache %s' % (args.root, diskcache.__version__))


if __name__ == '__main__':
    main()
