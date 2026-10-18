"""Test read-only caches and reopening without writes (upstream issue 113)."""

import hashlib
import os
import os.path as op
import shutil
import sqlite3
import stat
import tempfile

import pytest

import diskcache_community as dc

POSIX = os.name != 'nt'
ROOT = getattr(os, 'geteuid', lambda: 1)() == 0
needs_permissions = pytest.mark.skipif(
    not POSIX or ROOT, reason='needs POSIX permissions that bind'
)
BIG = b'x' * 70000  # Above disk_min_file_size, so stored in a file.


def square(value):
    """Memoized by the tests; the cache key is derived from this name."""
    return value * value


def sha256(path):
    with open(path, 'rb') as reader:
        return hashlib.sha256(reader.read()).hexdigest()


def listing(directory):
    return sorted(
        name
        for name in os.listdir(directory)
        if name.startswith(dc.core.DBNAME)
    )


def populate(cache):
    """Store every value kind, tags, expired rows, a queue and a memoized call."""
    cache['text'] = 'text'
    cache[b'bytes'] = b'bytes'
    cache['float'] = 1.5
    cache['pickle'] = {'a': (1, 2)}
    cache['big'] = BIG
    cache.set('tagged', 1, tag='tag')
    cache.set('expired', 1, expire=-1)
    cache.push('q0', expire=-1)
    cache.push('q1')
    cache.push('q2', expire=-1)
    cache.memoize()(square)(3)
    return len(cache)


def check_reads(cache, count, peek=True):
    assert cache['text'] == 'text'
    assert cache[b'bytes'] == b'bytes'
    assert cache['float'] == 1.5
    assert cache['pickle'] == {'a': (1, 2)}
    assert cache['big'] == BIG
    assert cache.get('tagged', tag=True) == (1, 'tag')
    assert cache.get('expired') is None
    assert 'text' in cache
    assert 'missing' not in cache
    assert len(cache) == count
    assert cache.volume() > 0
    assert cache.check() == []
    assert len(list(cache.iterkeys())) == count
    assert len(list(cache)) == count

    if peek:  # Expired queue items are skipped rather than removed.
        assert cache.peek()[1] == 'q1'
        assert cache.peek(side='back')[1] == 'q1'
        assert cache.peekitem(last=False)[0] == 'text'

    memoized = cache.memoize()(square)
    assert cache.get(memoized.__cache_key__(3)) == 9
    assert memoized(3) == 9


def check_writes_raise(cache):
    memoized = cache.memoize()(square)
    attempts = [
        lambda: cache.set('new', 1),
        lambda: cache.__setitem__('new', 1),
        lambda: cache.add('new', 1),
        lambda: cache.incr('counter'),
        lambda: cache.decr('counter'),
        lambda: cache.touch('text'),
        lambda: cache.pop('text'),
        lambda: cache.__delitem__('text'),
        lambda: cache.delete('text'),
        lambda: cache.push('new'),
        cache.pull,
        lambda: cache.evict('tag'),
        cache.expire,
        cache.cull,
        cache.clear,
        cache.create_tag_index,
        cache.drop_tag_index,
        lambda: cache.check(fix=True),
        lambda: cache.reset('size_limit', 5),
        lambda: memoized(4),
    ]

    for attempt in attempts:
        with pytest.raises(dc.ReadOnlyError):
            attempt()


@pytest.fixture
def directory():
    path = tempfile.mkdtemp()
    yield path
    for dirpath, dirnames, filenames in os.walk(path):
        os.chmod(dirpath, 0o755)
        for name in filenames:
            os.chmod(op.join(dirpath, name), 0o644)
    shutil.rmtree(path, ignore_errors=True)


def test_reopen_does_not_write(directory):
    with dc.Cache(directory, cull_limit=0) as cache:
        count = populate(cache)

    assert listing(directory) == [dc.core.DBNAME]
    path = op.join(directory, dc.core.DBNAME)
    digest, mtime = sha256(path), os.stat(path).st_mtime_ns

    for _ in range(2):
        with dc.Cache(directory) as cache:
            assert not cache.read_only
            check_reads(cache, count, peek=False)  # peek removes expired rows

    assert listing(directory) == [dc.core.DBNAME]
    assert sha256(path) == digest
    assert os.stat(path).st_mtime_ns == mtime


def test_reopen_writes_only_changed_settings(directory):
    with dc.Cache(directory) as cache:
        cache['a'] = 1

    path = op.join(directory, dc.core.DBNAME)
    digest = sha256(path)

    with dc.Cache(directory, size_limit=123) as cache:
        assert cache.size_limit == 123

    assert sha256(path) != digest

    with dc.Cache(directory) as cache:
        assert cache.size_limit == 123


def test_reopen_tag_index_only_when_changed(directory):
    with dc.Cache(directory, tag_index=True) as cache:
        cache.set('a', 1, tag='t')

    path = op.join(directory, dc.core.DBNAME)
    digest = sha256(path)

    with dc.Cache(directory) as cache:
        assert cache.tag_index == 1

    assert sha256(path) == digest

    with dc.Cache(directory, tag_index=False) as cache:
        assert cache.tag_index == 0

    assert sha256(path) != digest


def test_statistics_write_on_read_but_not_when_read_only(directory):
    with dc.Cache(directory, statistics=1) as cache:
        cache['a'] = 1

    path = op.join(directory, dc.core.DBNAME)
    digest = sha256(path)

    with dc.Cache(directory) as cache:
        assert cache['a'] == 1
        assert cache.get('missing') is None

    # Hits and misses are counters in the database, so reads write.
    assert sha256(path) != digest

    with dc.Cache(directory) as cache:
        assert cache.stats() == (1, 1)

    with dc.Cache(directory, read_only=True) as cache:
        assert cache['a'] == 1
        assert cache.get('missing') is None
        assert cache.stats(enable=False, reset=True) == (1, 1)

    with dc.Cache(directory) as cache:
        assert cache.stats() == (1, 1)


def test_explicit_read_only(directory):
    with dc.Cache(directory, cull_limit=0) as cache:
        count = populate(cache)

    path = op.join(directory, dc.core.DBNAME)
    digest = sha256(path)

    with dc.Cache(directory, read_only=True) as cache:
        assert cache.read_only
        check_reads(cache, count)
        check_writes_raise(cache)

    assert sha256(path) == digest

    with dc.Cache(directory) as cache:
        assert not cache.read_only
        cache['new'] = 1
        del cache['new']


def test_read_only_requires_database(directory):
    with pytest.raises(dc.ReadOnlyError):
        dc.Cache(directory, read_only=True)

    assert not op.exists(op.join(directory, dc.core.DBNAME))


def test_read_only_error_is_operational_error(directory):
    with dc.Cache(directory) as cache:
        cache['a'] = 1

    with dc.Cache(directory, read_only=True) as cache:
        with pytest.raises(sqlite3.OperationalError):
            cache['b'] = 2


def test_read_only_eviction_policies(directory):
    for policy in dc.EVICTION_POLICY:
        subdir = op.join(directory, policy)

        with dc.Cache(subdir, eviction_policy=policy) as cache:
            cache['a'] = 1

        with dc.Cache(subdir, read_only=True) as cache:
            assert cache['a'] == 1
            assert cache.get('a', expire_time=True) == (1, None)


def test_read_only_transaction_write_raises(directory):
    with dc.Cache(directory) as cache:
        cache['a'] = 1

    with dc.Cache(directory, read_only=True) as cache:
        with pytest.raises(dc.ReadOnlyError):
            with cache.transact():
                cache._sql('DELETE FROM Cache')

        assert cache['a'] == 1


def test_read_only_file_attribute(directory):
    with dc.Cache(directory, cull_limit=0) as cache:
        count = populate(cache)

    path = op.join(directory, dc.core.DBNAME)
    os.chmod(path, stat.S_IREAD)
    digest = sha256(path)

    try:
        with dc.Cache(directory) as cache:
            assert cache.read_only
            check_reads(cache, count)
            check_writes_raise(cache)
    finally:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)

    assert sha256(path) == digest

    with dc.Cache(directory) as cache:
        assert not cache.read_only


@needs_permissions
def test_read_only_directory(directory):
    with dc.Cache(directory, cull_limit=0) as cache:
        count = populate(cache)

    path = op.join(directory, dc.core.DBNAME)
    digest = sha256(path)
    files = sorted(os.listdir(directory))
    os.chmod(path, 0o444)
    os.chmod(directory, 0o555)

    try:
        with dc.Cache(directory) as cache:
            assert cache.read_only
            check_reads(cache, count)
            check_writes_raise(cache)
    finally:
        os.chmod(directory, 0o755)
        os.chmod(path, 0o644)

    assert sha256(path) == digest
    assert sorted(os.listdir(directory)) == files


@needs_permissions
def test_read_only_directory_without_settings(directory):
    path = op.join(directory, dc.core.DBNAME)
    sqlite3.connect(path).close()
    os.chmod(path, 0o444)
    os.chmod(directory, 0o555)

    try:
        with pytest.raises(dc.ReadOnlyError):
            dc.Cache(directory)
    finally:
        os.chmod(directory, 0o755)
        os.chmod(path, 0o644)


def test_read_only_fanout_deque_index(directory):
    fanout_dir = op.join(directory, 'fanout')
    deque_dir = op.join(directory, 'deque')
    index_dir = op.join(directory, 'index')

    with dc.FanoutCache(fanout_dir, shards=2) as fanout:
        fanout['a'] = 1
        fanout['big'] = BIG

    deque = dc.Deque('abc', deque_dir)
    deque._cache.close()
    index = dc.Index(index_dir, a=1, b=2)
    index._cache.close()

    with dc.FanoutCache(fanout_dir, shards=2, read_only=True) as fanout:
        assert all(shard.read_only for shard in fanout._shards)
        assert fanout['a'] == 1
        assert fanout['big'] == BIG
        assert len(fanout) == 2

        with pytest.raises(dc.ReadOnlyError):
            fanout['b'] = 2

    deque = dc.Deque.fromcache(dc.Cache(deque_dir, read_only=True))
    assert list(deque) == ['a', 'b', 'c']
    assert deque[0] == 'a'
    assert deque.peekleft() == 'a'
    assert deque.peek() == 'c'

    with pytest.raises(dc.ReadOnlyError):
        deque.append('d')

    deque._cache.close()

    index = dc.Index.fromcache(dc.Cache(index_dir, read_only=True))
    assert dict(index) == {'a': 1, 'b': 2}
    assert index.peekitem() == ('b', 2)

    with pytest.raises(dc.ReadOnlyError):
        index['c'] = 3

    index._cache.close()


def test_read_only_django(directory):
    pytest.importorskip('django')
    from django.conf import settings

    if not settings.configured:
        pytest.skip('Django settings are not configured')

    from diskcache_community import DjangoCache

    cache = DjangoCache(directory, {})
    cache.set('a', 1)
    cache.close()

    cache = DjangoCache(directory, {'OPTIONS': {'read_only': True}})
    assert cache.get('a') == 1

    with pytest.raises(dc.ReadOnlyError):
        cache.set('b', 2)

    cache.close()


def test_read_only_without_metadata_rows(directory):
    with dc.Cache(directory) as cache:
        cache['a'] = 1
        cache._sql("DELETE FROM Settings WHERE key IN ('hits', 'misses')")

    with dc.Cache(directory, read_only=True) as cache:
        assert cache['a'] == 1
        assert cache.stats() == (0, 0)

    with dc.Cache(directory) as cache:
        assert cache.stats() == (0, 0)
        assert cache.reset('hits') == 0
