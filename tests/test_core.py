"""Test diskcache_community.core.Cache."""

import _thread
import errno
import gc
import hashlib
import io
import os
import os.path as op
import pathlib
import pickle
import shutil
import signal
import sqlite3
import stat
import subprocess as sp
import tempfile
import threading
import time
import warnings
from unittest import mock

import pytest

import diskcache_community as dc

pytestmark = pytest.mark.filterwarnings('ignore', category=dc.EmptyDirWarning)


@pytest.fixture
def cache():
    with dc.Cache() as cache:
        yield cache
    shutil.rmtree(cache.directory, ignore_errors=True)


def test_init(cache):
    for key, value in dc.DEFAULT_SETTINGS.items():
        assert getattr(cache, key) == value
    cache.check()
    cache.close()
    cache.close()


def test_init_path(cache):
    path = pathlib.Path(cache.directory)
    other = dc.Cache(path)
    other.close()
    assert cache.directory == other.directory


def test_init_disk():
    with dc.Cache(disk_pickle_protocol=1, disk_min_file_size=2**20) as cache:
        key = (None, 0, 'abc')
        cache[key] = 0
        cache.check()
        assert cache.disk_min_file_size == 2**20
        assert cache.disk_pickle_protocol == 1
    shutil.rmtree(cache.directory, ignore_errors=True)


def test_disk_reset():
    with dc.Cache(disk_min_file_size=0, disk_pickle_protocol=0) as cache:
        value = (None, 0, 'abc')

        cache[0] = value
        cache.check()

        assert cache.disk_min_file_size == 0
        assert cache.disk_pickle_protocol == 0
        assert cache._disk.min_file_size == 0
        assert cache._disk.pickle_protocol == 0

        cache.reset('disk_min_file_size', 2**10)
        cache.reset('disk_pickle_protocol', 2)

        cache[1] = value
        cache.check()

        assert cache.disk_min_file_size == 2**10
        assert cache.disk_pickle_protocol == 2
        assert cache._disk.min_file_size == 2**10
        assert cache._disk.pickle_protocol == 2

    shutil.rmtree(cache.directory, ignore_errors=True)


def test_disk_valueerror():
    with pytest.raises(ValueError):
        with dc.Cache(disk=dc.Disk('test')):
            pass


def test_custom_disk():
    with dc.Cache(disk=dc.JSONDisk, disk_compress_level=6) as cache:
        values = [None, True, 0, 1.23, {}, [None] * 10000]

        for value in values:
            cache[value] = value

        for value in values:
            assert cache[value] == value

        for key, value in zip(cache, values):
            assert key == value

        test_memoize_iter(cache)

    shutil.rmtree(cache.directory, ignore_errors=True)


class SHA256FilenameDisk(dc.Disk):
    def filename(self, key=dc.UNKNOWN, value=dc.UNKNOWN):
        filename = hashlib.sha256(key).hexdigest()[:32]
        full_path = op.join(self._directory, filename)
        return filename, full_path


def test_custom_filename_disk():
    with dc.Cache(disk=SHA256FilenameDisk) as cache:
        for count in range(100, 200):
            key = str(count).encode('ascii')
            cache[key] = str(count) * int(1e5)

    for count in range(100, 200):
        key = str(count).encode('ascii')
        filename = hashlib.sha256(key).hexdigest()[:32]
        full_path = op.join(cache.directory, filename)

        with open(full_path) as reader:
            content = reader.read()
            assert content == str(count) * int(1e5)

    shutil.rmtree(cache.directory, ignore_errors=True)


def test_init_makedirs():
    cache_dir = tempfile.mkdtemp()
    shutil.rmtree(cache_dir)
    mkdir = mock.Mock(side_effect=OSError(errno.EACCES))

    with pytest.raises(EnvironmentError):
        try:
            with mock.patch('os.mkdir', mkdir):
                dc.Cache(cache_dir)
        except EnvironmentError:
            shutil.rmtree(cache_dir, ignore_errors=True)
            raise


def test_pragma_error(cache):
    local = mock.Mock()
    con = mock.Mock()
    execute = mock.Mock()
    cursor = mock.Mock()
    fetchall = mock.Mock()

    local.pid = os.getpid()
    local.con = con
    con.execute = execute
    execute.return_value = cursor
    cursor.fetchall = fetchall
    fetchall.side_effect = [sqlite3.OperationalError] * 60000

    size = 2**28

    with mock.patch('time.sleep', lambda num: 0):
        with mock.patch.object(cache, '_local', local):
            with pytest.raises(sqlite3.OperationalError):
                cache.reset('sqlite_mmap_size', size)


def test_close_error(cache):
    class LocalTest(object):
        def __init__(self):
            self._calls = 0

        def __getattr__(self, name):
            if self._calls:
                raise AttributeError
            else:
                self._calls += 1
                return mock.Mock()

    with mock.patch.object(cache, '_local', LocalTest()):
        cache.close()


def test_getsetdel(cache):
    values = [
        (None, False),
        ((None,) * 2**20, False),
        (1234, False),
        (2**512, False),
        (56.78, False),
        ('hello', False),
        ('hello' * 2**20, False),
        (b'world', False),
        (b'world' * 2**20, False),
        (io.BytesIO(b'world' * 2**20), True),
    ]

    for key, (value, file_like) in enumerate(values):
        assert cache.set(key, value, read=file_like)

    assert len(cache) == len(values)

    for key, (value, file_like) in enumerate(values):
        if file_like:
            assert cache[key] == value.getvalue()
        else:
            assert cache[key] == value

    for key, _ in enumerate(values):
        del cache[key]

    assert len(cache) == 0

    for value, (key, _) in enumerate(values):
        cache[key] = value

    assert len(cache) == len(values)

    for value, (key, _) in enumerate(values):
        assert cache[key] == value

    for _, (key, _) in enumerate(values):
        del cache[key]

    assert len(cache) == 0

    cache.check()


def test_get_keyerror1(cache):
    with pytest.raises(KeyError):
        cache[0]


def test_get_keyerror4(cache):
    func = mock.Mock(side_effect=IOError(errno.ENOENT, ''))

    cache.reset('statistics', True)
    cache[0] = b'abcd' * 2**20

    with mock.patch('diskcache_community.core.open', func):
        with pytest.raises((IOError, KeyError, OSError)):
            cache[0]


def test_read(cache):
    cache.set(0, b'abcd' * 2**20)
    with cache.read(0) as reader:
        assert reader is not None


def test_read_keyerror(cache):
    with pytest.raises(KeyError):
        with cache.read(0):
            pass


def test_set_twice(cache):
    large_value = b'abcd' * 2**20

    cache[0] = 0
    cache[0] = 1

    assert cache[0] == 1

    cache[0] = large_value

    assert cache[0] == large_value
    with cache.get(0, read=True) as reader:
        assert reader.name is not None

    cache[0] = 2

    assert cache[0] == 2
    assert cache.get(0, read=True) == 2

    cache.check()


def test_set_timeout(cache):
    local = mock.Mock()
    con = mock.Mock()
    execute = mock.Mock()

    local.pid = os.getpid()
    local.con = con
    con.execute = execute
    execute.side_effect = sqlite3.OperationalError

    with pytest.raises(dc.Timeout):
        try:
            with mock.patch.object(cache, '_local', local):
                cache.set('a', 'b' * 2**20)
        finally:
            cache.check()


def test_raw(cache):
    assert cache.set(0, io.BytesIO(b'abcd'), read=True)
    assert cache[0] == b'abcd'


def test_get(cache):
    assert cache.get(0) is None
    assert cache.get(1, 'dne') == 'dne'
    assert cache.get(2, {}) == {}
    assert cache.get(0, expire_time=True, tag=True) == (None, None, None)

    assert cache.set(0, 0, expire=None, tag='number')

    assert cache.get(0, expire_time=True) == (0, None)
    assert cache.get(0, tag=True) == (0, 'number')
    assert cache.get(0, expire_time=True, tag=True) == (0, None, 'number')


def test_get_expired_fast_path(cache):
    assert cache.set(0, 0, expire=0.001)
    time.sleep(0.01)
    assert cache.get(0) is None


def test_get_ioerror_fast_path(cache):
    assert cache.set(0, 0)

    disk = mock.Mock()
    put = mock.Mock()
    fetch = mock.Mock()

    disk.put = put
    put.side_effect = [(0, True)]
    disk.fetch = fetch
    io_error = IOError()
    io_error.errno = errno.ENOENT
    fetch.side_effect = io_error

    with mock.patch.object(cache, '_disk', disk):
        assert cache.get(0) is None


def test_get_expired_slow_path(cache):
    cache.stats(enable=True)
    cache.reset('eviction_policy', 'least-recently-used')
    assert cache.set(0, 0, expire=0.001)
    time.sleep(0.01)
    assert cache.get(0) is None


def test_pop(cache):
    assert cache.incr('alpha') == 1
    assert cache.pop('alpha') == 1
    assert cache.get('alpha') is None
    assert cache.check() == []

    assert cache.set('alpha', 123, expire=1, tag='blue')
    assert cache.pop('alpha', tag=True) == (123, 'blue')

    assert cache.set('beta', 456, expire=1e-9, tag='green')
    time.sleep(0.01)
    assert cache.pop('beta', 'dne') == 'dne'

    assert cache.set('gamma', 789, tag='red')
    assert cache.pop('gamma', expire_time=True, tag=True) == (789, None, 'red')

    assert cache.pop('dne') is None

    assert cache.set('delta', 210)
    assert cache.pop('delta', expire_time=True) == (210, None)

    assert cache.set('epsilon', '0' * 2**20)
    assert cache.pop('epsilon') == '0' * 2**20


def test_pop_ioerror(cache):
    assert cache.set(0, 0)

    disk = mock.Mock()
    put = mock.Mock()
    fetch = mock.Mock()

    disk.put = put
    put.side_effect = [(0, True)]
    disk.fetch = fetch
    io_error = IOError()
    io_error.errno = errno.ENOENT
    fetch.side_effect = io_error

    with mock.patch.object(cache, '_disk', disk):
        assert cache.pop(0) is None


def test_delete(cache):
    cache[0] = 0
    assert cache.delete(0)
    assert len(cache) == 0
    assert not cache.delete(0)
    assert len(cache.check()) == 0


def test_del(cache):
    with pytest.raises(KeyError):
        del cache[0]


def test_del_expired(cache):
    cache.set(0, 0, expire=0.001)
    time.sleep(0.01)
    with pytest.raises(KeyError):
        del cache[0]


def test_stats(cache):
    cache[0] = 0

    assert cache.stats(enable=True) == (0, 0)

    for _ in range(100):
        cache[0]

    for _ in range(10):
        cache.get(1)

    assert cache.stats(reset=True) == (100, 10)
    assert cache.stats(enable=False) == (0, 0)

    for _ in range(100):
        cache[0]

    for _ in range(10):
        cache.get(1)

    assert cache.stats() == (0, 0)
    assert len(cache.check()) == 0


def test_path(cache):
    cache[0] = 'abc'
    large_value = b'abc' * 2**20
    cache[1] = large_value

    assert cache.get(0, read=True) == 'abc'

    with cache.get(1, read=True) as reader:
        assert reader.name is not None
        path = reader.name

    with open(path, 'rb') as reader:
        value = reader.read()

    assert value == large_value

    assert len(cache.check()) == 0


def test_expire_rows(cache):
    cache.reset('cull_limit', 0)

    for value in range(10):
        assert cache.set(value, value, expire=1e-9)

    for value in range(10, 15):
        assert cache.set(value, value)

    assert len(cache) == 15

    time.sleep(0.01)
    cache.reset('cull_limit', 10)

    assert cache.set(15, 15)

    assert len(cache) == 6
    assert len(cache.check()) == 0


def test_least_recently_stored(cache):
    cache.reset('eviction_policy', 'least-recently-stored')
    cache.reset('size_limit', int(10.1e6))
    cache.reset('cull_limit', 2)

    million = b'x' * int(1e6)

    for value in range(10):
        cache[value] = million

    assert len(cache) == 10

    for value in range(10):
        assert cache[value] == million

    for value in range(10, 20):
        cache[value] = million

    assert len(cache) == 10

    for value in range(10):
        cache[value] = million

    count = len(cache)

    for index, length in enumerate([1, 2, 3, 4]):
        cache[10 + index] = million * length
        assert len(cache) == count - length

    assert cache[12] == million * 3
    assert cache[13] == million * 4

    assert len(cache.check()) == 0


def test_least_recently_used(cache):
    cache.reset('eviction_policy', 'least-recently-used')
    cache.reset('size_limit', int(10.1e6))
    cache.reset('cull_limit', 5)

    million = b'x' * int(1e6)

    for value in range(10):
        cache[value] = million

    assert len(cache) == 10

    time.sleep(0.01)

    cache[0]
    cache[1]
    cache[7]
    cache[8]
    cache[9]

    cache[10] = million

    assert len(cache) == 6

    for value in [0, 1, 7, 8, 9, 10]:
        assert cache[value] == million

    assert len(cache.check()) == 0


def test_least_frequently_used(cache):
    cache.reset('eviction_policy', 'least-frequently-used')
    cache.reset('size_limit', int(10.1e6))
    cache.reset('cull_limit', 5)

    million = b'x' * int(1e6)

    for value in range(10):
        cache[value] = million

    assert len(cache) == 10

    cache[0], cache[0], cache[0], cache[0], cache[0]
    cache[1], cache[1], cache[1], cache[1]
    cache[7], cache[7], cache[7]
    cache[8], cache[8]
    cache[9]

    cache[10] = million

    assert len(cache) == 6

    for value in [0, 1, 7, 8, 9, 10]:
        assert cache[value] == million

    assert len(cache.check()) == 0


def test_check(cache):
    blob = b'a' * 2**20
    keys = (0, 1, 1234, 56.78, 'hello', b'world', None)

    for key in keys:
        cache[key] = blob

    # Cause mayhem.

    with cache.get(0, read=True) as reader:
        full_path = reader.name
    os.rename(full_path, full_path + '_moved')

    with cache.get(1, read=True) as reader:
        full_path = reader.name
    os.remove(full_path)

    cache._sql('UPDATE Cache SET size = 0 WHERE rowid > 1')
    cache.reset('count', 0)
    cache.reset('size', 0)

    with warnings.catch_warnings():
        warnings.filterwarnings('ignore')
        cache.check()
        cache.check(fix=True)

    assert len(cache.check()) == 0  # Should display no warnings.


def test_integrity_check(cache):
    for value in range(1000):
        cache[value] = value

    cache.close()

    with io.open(op.join(cache.directory, 'cache.db'), 'r+b') as writer:
        writer.seek(52)
        writer.write(b'\x00\x01')  # Should be 0, change it.

    cache = dc.Cache(cache.directory)

    with warnings.catch_warnings():
        warnings.filterwarnings('ignore')
        cache.check()
        cache.check(fix=True)

    assert len(cache.check()) == 0


def test_expire(cache):
    cache.reset('cull_limit', 0)  # Disable expiring keys on `set`.
    now = time.time()
    time_time = mock.Mock(return_value=now)

    with mock.patch('time.time', time_time):
        for value in range(1, 101):
            assert cache.set(value, value, expire=value)

    assert len(cache) == 100

    time_time = mock.Mock(return_value=now + 11)
    cache.reset('cull_limit', 10)
    with mock.patch('time.time', time_time):
        assert cache.expire() == 10

    assert len(cache) == 90
    assert len(cache.check()) == 0


def test_tag_index():
    with dc.Cache(tag_index=True) as cache:
        assert cache.tag_index == 1
    shutil.rmtree(cache.directory, ignore_errors=True)


def test_evict(cache):
    colors = ('red', 'blue', 'yellow')

    for value in range(90):
        assert cache.set(value, value, tag=colors[value % len(colors)])

    assert len(cache) == 90
    assert cache.evict('red') == 30
    assert len(cache) == 60
    assert len(cache.check()) == 0


def test_clear(cache):
    for value in range(100):
        cache[value] = value
    assert len(cache) == 100
    assert cache.clear() == 100
    assert len(cache) == 0
    assert len(cache.check()) == 0


def test_clear_timeout(cache):
    transact = mock.Mock()
    transact.side_effect = dc.Timeout
    with mock.patch.object(cache, '_transact', transact):
        with pytest.raises(dc.Timeout):
            cache.clear()


def test_tag(cache):
    assert cache.set(0, None, tag='zero')
    assert cache.set(1, None, tag=1234)
    assert cache.set(2, None, tag=5.67)
    assert cache.set(3, None, tag=b'three')

    assert cache.get(0, tag=True) == (None, 'zero')
    assert cache.get(1, tag=True) == (None, 1234)
    assert cache.get(2, tag=True) == (None, 5.67)
    assert cache.get(3, tag=True) == (None, b'three')


def test_with(cache):
    with dc.Cache(cache.directory) as tmp:
        tmp['a'] = 0
        tmp['b'] = 1

    assert cache['a'] == 0
    assert cache['b'] == 1


def test_contains(cache):
    assert 0 not in cache
    cache[0] = 0
    assert 0 in cache


def test_touch(cache):
    assert cache.set(0, None, expire=60)
    assert cache.touch(0, expire=None)
    assert cache.touch(0, expire=0)
    assert not cache.touch(0)


def test_add(cache):
    assert cache.add(1, 1)
    assert cache.get(1) == 1
    assert not cache.add(1, 2)
    assert cache.get(1) == 1
    assert cache.delete(1)
    assert cache.add(1, 1, expire=0.001)
    time.sleep(0.01)
    assert cache.add(1, 1)
    cache.check()


def test_add_large_value(cache):
    value = b'abcd' * 2**20
    assert cache.add(b'test-key', value)
    assert cache.get(b'test-key') == value
    assert not cache.add(b'test-key', value * 2)
    assert cache.get(b'test-key') == value
    cache.check()


def test_add_timeout(cache):
    local = mock.Mock()
    con = mock.Mock()
    execute = mock.Mock()

    local.pid = os.getpid()
    local.con = con
    con.execute = execute
    execute.side_effect = sqlite3.OperationalError

    with pytest.raises(dc.Timeout):
        try:
            with mock.patch.object(cache, '_local', local):
                cache.add(0, 0)
        finally:
            cache.check()


def test_incr(cache):
    assert cache.incr('key', default=5) == 6
    assert cache.incr('key', 2) == 8
    assert cache.get('key', expire_time=True, tag=True) == (8, None, None)
    assert cache.delete('key')
    assert cache.set('key', 100, expire=10)
    assert cache.get('key') == 100
    expire_now(cache, 'key')
    assert cache.incr('key') == 1


def expire_now(cache, key):
    """Move the expiry of `key` into the past without waiting for the clock."""
    cache._sql(
        'UPDATE Cache SET expire_time = ? WHERE key = ?',
        (time.time() - 1, key),
    )


def test_incr_insert_keyerror(cache):
    with pytest.raises(KeyError):
        cache.incr('key', default=None)


def test_incr_update_keyerror(cache):
    assert cache.set('key', 100, expire=10)
    assert cache.get('key') == 100
    expire_now(cache, 'key')
    with pytest.raises(KeyError):
        cache.incr('key', default=None)


def test_decr(cache):
    assert cache.decr('key', default=5) == 4
    assert cache.decr('key', 2) == 2
    assert cache.get('key', expire_time=True, tag=True) == (2, None, None)
    assert cache.delete('key')
    assert cache.set('key', 100, expire=10)
    assert cache.get('key') == 100
    expire_now(cache, 'key')
    assert cache.decr('key') == -1


def test_iter(cache):
    sequence = list('abcdef') + [('g',)]

    for index, value in enumerate(sequence):
        cache[value] = index

    iterator = iter(cache)

    assert all(one == two for one, two in zip(sequence, iterator))

    cache['h'] = 7

    with pytest.raises(StopIteration):
        next(iterator)


def test_iter_expire(cache):
    cache.reset('cull_limit', 0)
    for num in range(100):
        cache.set(num, num, expire=1e-9)
    assert len(cache) == 100
    assert list(cache) == list(range(100))


def test_iter_error(cache):
    with pytest.raises(StopIteration):
        next(iter(cache))


def test_reversed(cache):
    sequence = 'abcdef'

    for index, value in enumerate(sequence):
        cache[value] = index

    iterator = reversed(cache)

    pairs = zip(reversed(sequence), iterator)
    assert all(one == two for one, two in pairs)

    try:
        next(iterator)
    except StopIteration:
        pass
    else:
        assert False, 'StopIteration expected'


def test_reversed_error(cache):
    with pytest.raises(StopIteration):
        next(reversed(cache))


def test_push_pull(cache):
    for value in range(10):
        cache.push(value)

    for value in range(10):
        _, pull_value = cache.pull()
        assert pull_value == value

    assert len(cache) == 0


def test_push_pull_prefix(cache):
    for value in range(10):
        cache.push(value, prefix='key')

    for value in range(10):
        key, peek_value = cache.peek(prefix='key')
        key, pull_value = cache.pull(prefix='key')
        assert key.startswith('key')
        assert peek_value == value
        assert pull_value == value

    assert len(cache) == 0
    assert len(cache.check()) == 0


def test_push_pull_extras(cache):
    cache.push('test')
    assert cache.pull() == (500000000000000, 'test')
    assert len(cache) == 0

    cache.push('test', expire=10)
    (key, value), expire_time = cache.peek(expire_time=True)
    assert key == 500000000000000
    assert value == 'test'
    assert expire_time > time.time()
    assert len(cache) == 1
    (key, value), expire_time = cache.pull(expire_time=True)
    assert key == 500000000000000
    assert value == 'test'
    assert expire_time > time.time()
    assert len(cache) == 0

    cache.push('test', tag='foo')
    (key, value), tag = cache.peek(tag=True)
    assert key == 500000000000000
    assert value == 'test'
    assert tag == 'foo'
    assert len(cache) == 1
    (key, value), tag = cache.pull(tag=True)
    assert key == 500000000000000
    assert value == 'test'
    assert tag == 'foo'
    assert len(cache) == 0

    cache.push('test')
    (key, value), expire_time, tag = cache.peek(expire_time=True, tag=True)
    assert key == 500000000000000
    assert value == 'test'
    assert expire_time is None
    assert tag is None
    assert len(cache) == 1
    (key, value), expire_time, tag = cache.pull(expire_time=True, tag=True)
    assert key == 500000000000000
    assert value == 'test'
    assert expire_time is None
    assert tag is None
    assert len(cache) == 0

    assert cache.pull(default=(0, 1)) == (0, 1)

    assert len(cache.check()) == 0


def test_push_pull_expire(cache):
    cache.push(0, expire=0.1)
    cache.push(0, expire=0.1)
    cache.push(0, expire=0.1)
    cache.push(1)
    time.sleep(0.2)
    assert cache.pull() == (500000000000003, 1)
    assert len(cache) == 0
    assert len(cache.check()) == 0


def test_push_peek_expire(cache):
    cache.push(0, expire=0.1)
    cache.push(0, expire=0.1)
    cache.push(0, expire=0.1)
    cache.push(1)
    time.sleep(0.2)
    assert cache.peek() == (500000000000003, 1)
    assert len(cache) == 1
    assert len(cache.check()) == 0


def test_push_pull_large_value(cache):
    value = b'test' * (2**20)
    cache.push(value)
    assert cache.pull() == (500000000000000, value)
    assert len(cache) == 0
    assert len(cache.check()) == 0


def test_push_peek_large_value(cache):
    value = b'test' * (2**20)
    cache.push(value)
    assert cache.peek() == (500000000000000, value)
    assert len(cache) == 1
    assert len(cache.check()) == 0


def test_pull_ioerror(cache):
    assert cache.push(0) == 500000000000000

    disk = mock.Mock()
    put = mock.Mock()
    fetch = mock.Mock()

    disk.put = put
    put.side_effect = [(0, True)]
    disk.fetch = fetch
    io_error = IOError()
    io_error.errno = errno.ENOENT
    fetch.side_effect = io_error

    with mock.patch.object(cache, '_disk', disk):
        assert cache.pull() == (None, None)


def test_peek_ioerror(cache):
    assert cache.push(0) == 500000000000000

    disk = mock.Mock()
    put = mock.Mock()
    fetch = mock.Mock()

    disk.put = put
    put.side_effect = [(0, True)]
    disk.fetch = fetch
    io_error = IOError()
    io_error.errno = errno.ENOENT
    fetch.side_effect = [io_error, 0]

    with mock.patch.object(cache, '_disk', disk):
        _, value = cache.peek()
        assert value == 0


def test_peekitem_extras(cache):
    with pytest.raises(KeyError):
        cache.peekitem()

    assert cache.set('a', 0)
    assert cache.set('b', 1)
    assert cache.set('c', 2, expire=10, tag='foo')
    assert cache.set('d', 3, expire=0.1)
    assert cache.set('e', 4, expire=0.1)

    time.sleep(0.2)

    (key, value), expire_time, tag = cache.peekitem(expire_time=True, tag=True)
    assert key == 'c'
    assert value == 2
    assert expire_time > 0
    assert tag == 'foo'

    (key, value), expire_time = cache.peekitem(expire_time=True)
    assert key == 'c'
    assert value == 2
    assert expire_time > 0

    (key, value), tag = cache.peekitem(tag=True)
    assert key == 'c'
    assert value == 2
    assert expire_time > 0
    assert tag == 'foo'


def test_peekitem_ioerror(cache):
    assert cache.set('a', 0)
    assert cache.set('b', 1)
    assert cache.set('c', 2)

    disk = mock.Mock()
    put = mock.Mock()
    fetch = mock.Mock()

    disk.put = put
    put.side_effect = [(0, True)]
    disk.fetch = fetch
    io_error = IOError()
    io_error.errno = errno.ENOENT
    fetch.side_effect = [io_error, 2]

    with mock.patch.object(cache, '_disk', disk):
        _, value = cache.peekitem()
        assert value == 2


def test_iterkeys(cache):
    assert list(cache.iterkeys()) == []


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('tag', [None, '', b'', 0, False, 1.5, 'counter'])
def test_iterkeys_tag(cache, reverse, tag):
    assert list(cache.iterkeys(reverse=reverse, tag=tag)) == []
    cache.set('a', 1, tag=tag)
    cache.set('b', 2, tag='other')
    cache.set('c', 3, tag=tag)
    cache.set('d', 4)

    expected = ['a', 'c', 'd'] if tag is None else ['a', 'c']
    assert list(cache.iterkeys(reverse=reverse, tag=tag)) == (
        expected[::-1] if reverse else expected
    )
    assert list(cache.iterkeys(reverse=reverse, tag='missing')) == []
    assert list(cache.iterkeys(reverse)) == (
        ['d', 'c', 'b', 'a'] if reverse else ['a', 'b', 'c', 'd']
    )


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('tag_index', [False, True])
def test_iterkeys_tag_pagination(cache, reverse, tag_index):
    if tag_index:
        cache.create_tag_index()

    expected = []
    for convert in (
        int,
        lambda num: 'key-%03d' % num,
        lambda num: bytes([num]),
    ):
        for num in range(240):
            key = convert(num)
            tag = 'counter' if num % 2 else 'other'
            cache.set(key, None, tag=tag)
            if num % 2:
                expected.append(key)

    assert list(cache.iterkeys(reverse=reverse, tag='counter')) == (
        expected[::-1] if reverse else expected
    )


@pytest.mark.parametrize('reverse', [False, True])
def test_iterkeys_tag_raw_collision(cache, reverse):
    pairs = []
    for num in range(105):
        key = (num,)
        raw_key = bytes(cache.disk.put(key)[0])
        cache.set(key, None, tag='counter')
        cache.set(raw_key, None, tag='counter' if num % 2 else 'other')
        pairs.append((raw_key, key, num % 2))

    expected = []
    for raw_key, key, matching in sorted(pairs):
        expected.append(key)
        if matching:
            expected.append(raw_key)

    assert list(cache.iterkeys(reverse=reverse, tag='counter')) == (
        expected[::-1] if reverse else expected
    )


def test_iterkeys_tag_does_not_fetch_values(cache):
    cache.set('key', {'value': 1}, tag='counter')
    with mock.patch.object(cache.disk, 'fetch') as fetch:
        assert list(cache.iterkeys(tag='counter')) == ['key']
    fetch.assert_not_called()


def test_iterkeys_tag_includes_expired(cache):
    cache.reset('cull_limit', 0)
    cache.set('expired', 1, tag='counter', expire=-1)
    cache.set('live', 2, tag='counter')
    assert list(cache.iterkeys(tag='counter')) == ['expired', 'live']


def test_pickle(cache):
    for num, val in enumerate('abcde'):
        cache[val] = num

    data = pickle.dumps(cache)
    other = pickle.loads(data)

    for key in other:
        assert other[key] == cache[key]


def test_pragmas(cache):
    results = []

    def compare_pragmas():
        valid = True

        for key, value in dc.DEFAULT_SETTINGS.items():
            if not key.startswith('sqlite_'):
                continue

            pragma = key[7:]

            result = cache._sql('PRAGMA %s' % pragma).fetchall()

            if result == [(value,)]:
                continue

            args = pragma, result, [(value,)]
            print('pragma %s mismatch: %r != %r' % args)
            valid = False

        results.append(valid)

    threads = []

    for count in range(8):
        thread = threading.Thread(target=compare_pragmas)
        thread.start()
        threads.append(thread)

    for thread in threads:
        thread.join()

    assert all(results)


def test_size_limit_with_files(cache):
    cache.reset('cull_limit', 0)
    size_limit = 30 * cache.disk_min_file_size
    cache.reset('size_limit', size_limit)
    value = b'foo' * cache.disk_min_file_size

    for key in range(40):
        cache.set(key, value)

    assert cache.volume() > size_limit
    cache.cull()
    assert cache.volume() <= size_limit


def test_size_limit_with_database(cache):
    cache.reset('cull_limit', 0)
    size_limit = 2 * cache.disk_min_file_size
    cache.reset('size_limit', size_limit)
    value = b'0123456789' * 10
    count = size_limit // (8 + len(value))

    for key in range(count):
        cache.set(key, value)

    assert cache.volume() > size_limit
    cache.cull()
    assert cache.volume() <= size_limit


def test_cull_eviction_policy_none(cache):
    cache.reset('eviction_policy', 'none')
    size_limit = 2 * cache.disk_min_file_size
    cache.reset('size_limit', size_limit)
    value = b'0123456789' * 10
    count = size_limit // (8 + len(value))

    for key in range(count):
        cache.set(key, value)

    assert cache.volume() > size_limit
    cache.cull()
    assert cache.volume() > size_limit


def test_cull_size_limit_0(cache):
    cache.reset('cull_limit', 0)
    size_limit = 2 * cache.disk_min_file_size
    cache.reset('size_limit', 0)
    value = b'0123456789' * 10
    count = size_limit // (8 + len(value))

    for key in range(count):
        cache.set(key, value)

    assert cache.volume() > size_limit
    cache.cull()
    assert cache.volume() <= size_limit


def test_cull_timeout(cache):
    transact = mock.Mock()
    transact.side_effect = [dc.Timeout]

    with mock.patch.object(cache, 'expire', lambda now: 0):
        with mock.patch.object(cache, 'volume', lambda: int(1e12)):
            with mock.patch.object(cache, '_transact', transact):
                with pytest.raises(dc.Timeout):
                    cache.cull()


def test_key_roundtrip(cache):
    key_part_0 = 'part0'
    key_part_1 = 'part1'
    to_test = [
        (key_part_0, key_part_1),
        [key_part_0, key_part_1],
    ]

    for key in to_test:
        cache.clear()
        cache[key] = {'example0': ['value0']}
        keys = list(cache)
        assert len(keys) == 1
        cache_key = keys[0]
        assert cache[key] == {'example0': ['value0']}
        assert cache[cache_key] == {'example0': ['value0']}


def test_constant():
    import diskcache_community.core

    assert repr(diskcache_community.core.ENOVAL) == 'ENOVAL'


def test_copy():
    cache_dir1 = tempfile.mkdtemp()

    with dc.Cache(cache_dir1) as cache1:
        for count in range(10):
            cache1[count] = str(count)

        for count in range(10, 20):
            cache1[count] = str(count) * int(1e5)

    cache_dir2 = tempfile.mkdtemp()
    shutil.rmtree(cache_dir2)
    shutil.copytree(cache_dir1, cache_dir2)

    with dc.Cache(cache_dir2) as cache2:
        for count in range(10):
            assert cache2[count] == str(count)

        for count in range(10, 20):
            assert cache2[count] == str(count) * int(1e5)

    shutil.rmtree(cache_dir1, ignore_errors=True)
    shutil.rmtree(cache_dir2, ignore_errors=True)


def run(command):
    print('run$ %r' % command)
    try:
        result = sp.check_output(command, stderr=sp.STDOUT)
        print(result)
    except sp.CalledProcessError as exc:
        print(exc.output)
        raise


def test_rsync():
    try:
        run(['rsync', '--version'])
    except OSError:
        return  # No rsync installed. Skip test.

    rsync_args = ['rsync', '-a', '--checksum', '--delete', '--stats']
    cache_dir1 = tempfile.mkdtemp() + os.sep
    cache_dir2 = tempfile.mkdtemp() + os.sep

    # Store some items in cache_dir1.

    with dc.Cache(cache_dir1) as cache1:
        for count in range(100):
            cache1[count] = str(count)

        for count in range(100, 200):
            cache1[count] = str(count) * int(1e5)

    # Rsync cache_dir1 to cache_dir2.

    run(rsync_args + [cache_dir1, cache_dir2])

    # Validate items in cache_dir2.

    with dc.Cache(cache_dir2) as cache2:
        for count in range(100):
            assert cache2[count] == str(count)

        for count in range(100, 200):
            assert cache2[count] == str(count) * int(1e5)

    # Store more items in cache_dir2.

    with dc.Cache(cache_dir2) as cache2:
        for count in range(200, 300):
            cache2[count] = str(count)

        for count in range(300, 400):
            cache2[count] = str(count) * int(1e5)

    # Rsync cache_dir2 to cache_dir1.

    run(rsync_args + [cache_dir2, cache_dir1])

    # Validate items in cache_dir1.

    with dc.Cache(cache_dir1) as cache1:
        for count in range(100):
            assert cache1[count] == str(count)

        for count in range(100, 200):
            assert cache1[count] == str(count) * int(1e5)

        for count in range(200, 300):
            assert cache1[count] == str(count)

        for count in range(300, 400):
            assert cache1[count] == str(count) * int(1e5)

    shutil.rmtree(cache_dir1, ignore_errors=True)
    shutil.rmtree(cache_dir2, ignore_errors=True)


def test_custom_eviction_policy(cache):
    dc.EVICTION_POLICY['lru-gt-1s'] = {
        'init': (
            'CREATE INDEX IF NOT EXISTS Cache_access_time ON'
            ' Cache (access_time)'
        ),
        'get': 'access_time = {now}',
        'cull': (
            'SELECT {fields} FROM Cache'
            ' WHERE access_time < ({now} - 1)'
            ' ORDER BY access_time LIMIT ?'
        ),
    }

    size_limit = int(1e5)

    cache.reset('eviction_policy', 'lru-gt-1s')
    cache.reset('size_limit', size_limit)

    for count in range(100, 150):
        cache[count] = str(count) * 500

    size = cache.volume()
    assert size > size_limit
    assert cache.cull() == 0
    assert size == cache.volume()

    for count in range(100, 150):
        assert cache[count] == str(count) * 500

    time.sleep(1.1)

    assert cache.cull() > 0
    assert cache.volume() < size_limit


def test_lru_incr(cache):
    cache.reset('eviction_policy', 'least-recently-used')
    cache.incr(0)
    cache.decr(0)
    assert cache[0] == 0


def test_memoize(cache):
    count = 1000

    def fibiter(num):
        alpha, beta = 0, 1

        for _ in range(num):
            alpha, beta = beta, alpha + beta

        return alpha

    @cache.memoize()
    def fibrec(num):
        if num == 0:
            return 0
        elif num == 1:
            return 1
        else:
            return fibrec(num - 1) + fibrec(num - 2)

    cache.stats(enable=True)

    for value in range(count):
        assert fibrec(value) == fibiter(value)

    hits1, misses1 = cache.stats()

    for value in range(count):
        assert fibrec(value) == fibiter(value)

    hits2, misses2 = cache.stats()

    assert hits2 == (hits1 + count)
    assert misses2 == misses1


def test_memoize_kwargs(cache):
    @cache.memoize(typed=True)
    def foo(*args, **kwargs):
        return args, kwargs

    assert foo(1, 2, 3, a=4, b=5) == ((1, 2, 3), {'a': 4, 'b': 5})


def test_cleanup_dirs(cache):
    value = b'\0' * 2**20
    start_count = len(os.listdir(cache.directory))
    for i in range(10):
        cache[i] = value
    set_count = len(os.listdir(cache.directory))
    assert set_count > start_count
    for i in range(10):
        del cache[i]
    del_count = len(os.listdir(cache.directory))
    assert start_count == del_count


def test_disk_write_os_error(cache):
    func = mock.Mock(side_effect=[OSError] * 10)
    with mock.patch('diskcache_community.core.open', func):
        with pytest.raises(OSError):
            cache[0] = '\0' * 2**20


def test_memoize_ignore(cache):
    @cache.memoize(ignore={1, 'arg1'})
    def test(*args, **kwargs):
        return args, kwargs

    cache.stats(enable=True)
    assert test('a', 'b', 'c', arg0='d', arg1='e', arg2='f')
    assert test('a', 'w', 'c', arg0='d', arg1='x', arg2='f')
    assert test('a', 'y', 'c', arg0='d', arg1='z', arg2='f')
    assert cache.stats() == (2, 1)


def test_memoize_key_format(cache):
    # The key format is part of the on-disk compatibility contract: caches
    # written by earlier versions must keep hitting, so pin it.
    @cache.memoize(name='plain')
    def plain(a, b=2, *args, **kwargs):
        return a

    key = plain.__cache_key__
    assert key(1, 2) == ('plain', 1, 2, None)
    assert key(1, b=2) == ('plain', 1, None, 'b', 2)
    assert key(1, 2, 3, d=4, c=5) == ('plain', 1, 2, 3, None, 'c', 5, 'd', 4)

    @cache.memoize(name='typed', typed=True)
    def typed(a, b=2):
        return a

    key = typed.__cache_key__
    assert key(1, b=2.0) == ('typed', 1, None, 'b', 2.0, int, float)
    assert key(1, 2.0) == ('typed', 1, 2.0, None, int, float)

    class Thing:
        @cache.memoize()
        def method(self, a):
            return a

    thing = Thing()
    base = dc.core.full_name(Thing.method.__wrapped__)
    assert thing.method.__cache_key__(thing, 1) == (base, thing, 1, None)

    # Naming an ignored parameter leaves the keys of the other calls alone.
    @cache.memoize(name='named', ignore={'b'})
    def named(a, b=2):
        return a

    key = named.__cache_key__
    assert key(1) == ('named', 1, None)
    assert key(1, b=5) == ('named', 1, None)
    assert key(1, 5) == ('named', 1, None)


def test_memoize_ignore_positional_by_name(cache):
    # Upstream issue 240: a name in `ignore` must match the argument whether
    # it is passed positionally or by keyword. Locks cannot be pickled, so a
    # leak into the key raises instead of silently missing the cache.
    @cache.memoize(ignore={'session'})
    def get(entity_id, session):
        return entity_id

    cache.stats(enable=True)
    assert get('a', threading.Lock()) == 'a'
    assert get('a', session=threading.Lock()) == 'a'
    assert get('a', threading.Lock()) == 'a'
    assert cache.stats() == (2, 1)
    assert get.__cache_key__('a', 1) == get.__cache_key__('a', session=2)


def test_memoize_ignore_positions_and_names(cache):
    @cache.memoize(name='mixed', ignore={0, 'c'})
    def mixed(a, b, c=None):
        return b

    key = mixed.__cache_key__
    assert key(1, 2, 3) == ('mixed', 2, None)
    assert key(1, 2, c=3) == ('mixed', 2, None)
    assert key(9, 2) == ('mixed', 2, None)

    @cache.memoize(name='posonly', ignore={'a'})
    def posonly(a, /, b):
        return b

    assert posonly.__cache_key__(1, 2) == ('posonly', 2, None)
    assert posonly.__cache_key__(1, b=2) == ('posonly', None, 'b', 2)


def test_memoize_ignore_keyword_only_and_var_positional(cache):
    # Only positional parameters resolve to positions: `args` collects the
    # extra positional arguments and `key` is keyword-only.
    @cache.memoize(name='kwonly', ignore={'key', 'args'})
    def kwonly(a, *args, key=None):
        return a

    key = kwonly.__cache_key__
    assert key(1, 2, 3, key=4) == ('kwonly', 1, 2, 3, None)
    assert key(1, key=4) == ('kwonly', 1, None)


def test_memoize_ignore_without_signature(cache):
    # Callables without a signature keep the position-only matching.
    signature = mock.Mock(side_effect=ValueError('no signature'))

    with mock.patch.object(dc.core.inspect, 'signature', signature):

        @cache.memoize(name='nosig', ignore={'b'})
        def nosig(a, b):
            return a

    assert signature.called
    key = nosig.__cache_key__
    assert key(1, 2) == ('nosig', 1, 2, None)
    assert key(1, b=2) == ('nosig', 1, None)


def test_memoize_iter(cache):
    @cache.memoize()
    def test(*args, **kwargs):
        return sum(args) + sum(kwargs.values())

    cache.clear()
    assert test(1, 2, 3)
    assert test(a=1, b=2, c=3)
    assert test(-1, 0, 1, a=1, b=2, c=3)
    assert len(cache) == 3
    for key in cache:
        assert cache[key] == 6


LEGACY_TRIGGERS = {
    # Trigger text written by diskcache 5.6.3 and earlier: double-quoted
    # literals, which SQLite builds compiled with SQLITE_DQS=0 reject.
    'Settings_count_insert': (
        'AFTER INSERT ON Cache FOR EACH ROW BEGIN'
        ' UPDATE Settings SET value = value + 1'
        ' WHERE key = "count"; END'
    ),
    'Settings_count_delete': (
        'AFTER DELETE ON Cache FOR EACH ROW BEGIN'
        ' UPDATE Settings SET value = value - 1'
        ' WHERE key = "count"; END'
    ),
    'Settings_size_insert': (
        'AFTER INSERT ON Cache FOR EACH ROW BEGIN'
        ' UPDATE Settings SET value = value + NEW.size'
        ' WHERE key = "size"; END'
    ),
    'Settings_size_update': (
        'AFTER UPDATE ON Cache FOR EACH ROW BEGIN'
        ' UPDATE Settings'
        ' SET value = value + NEW.size - OLD.size'
        ' WHERE key = "size"; END'
    ),
    'Settings_size_delete': (
        'AFTER DELETE ON Cache FOR EACH ROW BEGIN'
        ' UPDATE Settings SET value = value - OLD.size'
        ' WHERE key = "size"; END'
    ),
}


def stored_triggers(cache):
    select = "SELECT name, sql FROM sqlite_master WHERE type = 'trigger'"
    return dict(cache._sql(select).fetchall())


def test_legacy_triggers_recreated(cache):
    directory = cache.directory
    cache[0] = b'x' * 2**16  # Stored in a file, so size is tracked.

    for name, definition in LEGACY_TRIGGERS.items():
        cache._sql('DROP TRIGGER %s' % name)
        try:
            cache._sql('CREATE TRIGGER %s %s' % (name, definition))
        except sqlite3.OperationalError:
            pytest.skip('SQLite build rejects double-quoted literals')

    assert all('"' in sql for sql in stored_triggers(cache).values())
    cache.close()

    other = dc.Cache(directory)

    try:
        definitions = dict(dc.core.SETTINGS_TRIGGERS)
        triggers = stored_triggers(other)
        assert set(triggers) == set(definitions)
        for name, sql in triggers.items():
            assert sql == 'CREATE TRIGGER %s %s' % (name, definitions[name])
        assert len(other) == 1
        assert other.reset('size') == 2**16
        other[1] = b'y' * 2**16
        assert len(other) == 2
        assert other.reset('size') == 2**17
        del other[0]
        assert len(other) == 1
        assert other.reset('size') == 2**16
        assert other.check() == []
    finally:
        other.close()


def test_reopen_leaves_schema_unchanged(cache):
    directory = cache.directory
    cache[0] = 0
    cache.close()

    other = dc.Cache(directory)
    ((before,),) = other._sql('PRAGMA schema_version').fetchall()
    other.close()

    other = dc.Cache(directory)
    ((after,),) = other._sql('PRAGMA schema_version').fetchall()
    other.close()

    assert before == after


def test_update_triggers_race(cache):
    # Another opener recreated the triggers between the check and the lock.
    stale = mock.Mock(side_effect=[True, False])

    with mock.patch.object(cache, '_triggers_stale', stale):
        cache._update_triggers(cache._sql_retry)

    assert stale.call_count == 2
    cache[0] = 0  # Raises Timeout if a transaction were left open.
    assert cache.check() == []


def test_update_triggers_rollback(cache):
    stale = mock.Mock(side_effect=[True, RuntimeError])

    with mock.patch.object(cache, '_triggers_stale', stale):
        with pytest.raises(RuntimeError):
            cache._update_triggers(cache._sql_retry)

    cache[0] = 0  # Raises Timeout if a transaction were left open.
    assert cache.check() == []


# The separator a cache written on the other operating system would store in
# the Cache table's filename column (upstream issue 304).
FOREIGN_SEP = '\\' if os.sep == '/' else '/'


def foreign_separators(cache):
    """Rewrite stored filenames as a cache written on the other OS stores them."""
    cache._sql(
        'UPDATE Cache SET filename = replace(filename, ?, ?)'
        ' WHERE filename IS NOT NULL',
        (os.sep, FOREIGN_SEP),
    )
    rows = cache._sql(
        'SELECT filename FROM Cache WHERE filename IS NOT NULL'
    ).fetchall()
    assert rows
    assert all(FOREIGN_SEP in filename for (filename,) in rows)
    assert not any(os.sep in filename for (filename,) in rows)


def value_files(cache):
    return sorted(
        op.join(dirpath, name)
        for dirpath, _, files in os.walk(cache.directory)
        for name in files
        if dc.core.DBNAME not in name
    )


def test_native_filename(monkeypatch):
    monkeypatch.setattr(os, 'sep', '/')
    assert dc.core.native_filename('ab\\cd\\ef.val') == 'ab/cd/ef.val'
    assert dc.core.native_filename('ab/cd/ef.val') == 'ab/cd/ef.val'
    assert dc.core.native_filename('flat.val') == 'flat.val'
    monkeypatch.setattr(os, 'sep', '\\')
    assert dc.core.native_filename('ab/cd/ef.val') == 'ab\\cd\\ef.val'
    assert dc.core.native_filename('ab\\cd\\ef.val') == 'ab\\cd\\ef.val'
    assert dc.core.native_filename('flat.val') == 'flat.val'


def test_foreign_separator_fetch_and_check(cache):
    binary = b'a' * 2**16
    text = 'b' * 2**16
    obj = list(range(2**14))  # Pickles to about 48 KiB, so a file.
    cache['binary'] = binary
    cache['text'] = text
    cache['pickle'] = obj
    cache['raw'] = 1
    foreign_separators(cache)
    files = value_files(cache)
    assert len(files) == 3

    assert cache['binary'] == binary
    assert cache['text'] == text
    assert cache['pickle'] == obj
    assert cache['raw'] == 1
    with cache.get('binary', read=True) as reader:
        assert reader.read() == binary
    assert cache.check() == []
    assert cache.check(fix=True) == []
    assert value_files(cache) == files  # Nothing deleted as "unknown".
    assert cache['binary'] == binary


def test_foreign_separator_remove(cache):
    cache['binary'] = b'a' * 2**16
    cache['text'] = 'b' * 2**16
    cache['popped'] = b'c' * 2**16
    foreign_separators(cache)
    assert len(value_files(cache)) == 3

    del cache['binary']
    assert len(value_files(cache)) == 2
    assert cache.pop('popped') == b'c' * 2**16
    assert len(value_files(cache)) == 1
    assert cache.check() == []

    cache.clear()
    assert value_files(cache) == []
    assert cache.check() == []


def directory_modes(root):
    return {
        op.join(dirpath, name): stat.S_IMODE(
            os.stat(op.join(dirpath, name)).st_mode
        )
        for dirpath, dirnames, _ in os.walk(root)
        for name in dirnames
    }


@pytest.mark.skipif(os.name == 'nt', reason='POSIX permission bits')
def test_private_directories():
    umask = os.umask(0)
    root = tempfile.mkdtemp()

    try:
        directory = op.join(root, 'parent', 'cache')

        with dc.Cache(directory) as cache:
            cache[0] = b'x' * 2**16  # Stored in a file under ab/cd/.

        modes = directory_modes(root)
        # The parent, the cache directory and the two levels of value
        # subdirectories were all created by the cache.
        assert len(modes) == 4
        assert op.join(root, 'parent') in modes
        assert directory in modes
        assert all(mode == 0o700 for mode in modes.values()), modes
    finally:
        os.umask(umask)
        shutil.rmtree(root, ignore_errors=True)


@pytest.mark.skipif(os.name == 'nt', reason='POSIX permission bits')
def test_existing_directory_keeps_mode():
    umask = os.umask(0)
    directory = tempfile.mkdtemp()

    try:
        os.chmod(directory, 0o755)

        with dc.Cache(directory) as cache:
            cache[0] = 0

        assert stat.S_IMODE(os.stat(directory).st_mode) == 0o755
    finally:
        os.umask(umask)
        shutil.rmtree(directory, ignore_errors=True)


def resource_warnings(caught):
    return [w for w in caught if issubclass(w.category, ResourceWarning)]


def wait_for_child(pid, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rpid, status = os.waitpid(pid, os.WNOHANG)
        if rpid:
            return os.waitstatus_to_exitcode(status)
        time.sleep(0.01)
    os.kill(pid, signal.SIGKILL)
    os.waitpid(pid, 0)
    pytest.fail('child process did not exit within %s seconds' % timeout)


def forget_inherited(con):
    # Undo an in-process simulation of a fork child: here it is safe to
    # close the connection, because this process did open it.
    dc.core._INHERITED_CONNECTIONS.remove(con)
    con.close()


def test_close_closes_connections_of_exited_threads(cache):
    cache.set('main', 0)
    threads = [
        threading.Thread(target=cache.set, args=(num, num)) for num in range(3)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    done = threading.Event()

    def foreign():
        # A thread with no threading.Thread object, like a Qt thread.
        cache.set('foreign', 1)
        done.set()

    _thread.start_new_thread(foreign, ())
    assert done.wait(10)
    items = cache._cons._items
    main = threading.get_ident()
    deadline = time.monotonic() + 10
    while any(ref() for ident, (ref, _) in items.items() if ident != main):
        assert time.monotonic() < deadline, 'thread-local state not released'
        time.sleep(0.01)
    # Opening a connection closes those of exited threads, so at most the
    # main thread's and the last thread's connections are left.
    assert 1 <= len(items) <= 2
    gc.collect()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        cache.close()
        gc.collect()

    assert not resource_warnings(caught)
    assert cache._cons._items == {}
    assert cache.get('main') == 0  # Reconnects on use.
    assert cache.get('foreign') == 1


def test_close_leaves_connections_of_live_threads(cache):
    ready = threading.Event()
    release = threading.Event()
    results = []

    def work():
        cache.set('thread', 1)
        ready.set()
        release.wait(10)
        results.append(cache.get('thread'))

    thread = threading.Thread(target=work)
    thread.start()
    assert ready.wait(10)
    cache.close()
    release.set()
    thread.join(10)
    assert results == [1]


def test_connection_of_lost_thread_state_is_closed(cache):
    cache.set('a', 1)
    first = cache._local.con
    # The interpreter drops a thread's local state when the thread exits or
    # when a foreign thread gets a new thread state; simulate that here.
    del cache._local.con
    del cache._local.sentinel
    cache.set('b', 2)
    assert cache._local.con is not first
    assert len(cache._cons._items) == 1
    with pytest.raises(sqlite3.ProgrammingError):
        first.execute('SELECT 1')


def test_garbage_collected_cache_closes_connections():
    cache = dc.Cache()
    directory = cache.directory
    cache.set('a', 1)
    gc.collect()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        del cache
        gc.collect()

    assert not resource_warnings(caught)
    shutil.rmtree(directory, ignore_errors=True)


def test_after_fork_in_child_discards_connections(cache):
    # Run the at-fork child handler in this process.
    cache.set('a', 1)
    con = cache._local.con
    assert con not in dc.core._INHERITED_CONNECTIONS
    dc.core._after_fork_in_child()
    assert con in dc.core._INHERITED_CONNECTIONS
    assert getattr(cache._local, 'con', None) is None
    assert cache._cons._items == {}
    assert cache.get('a') == 1
    assert cache._local.con is not con
    forget_inherited(con)


def test_before_fork_closes_idle_connection(cache):
    # Run the at-fork parent handlers in this process.
    cache.set('a', 1)
    con = cache._local.con

    with cache.transact():
        dc.core._before_fork()
        dc.core._FORK_GATE.after_fork_parent()
        assert cache._local.con is con  # Not closed inside a transaction.

    dc.core._before_fork()
    dc.core._FORK_GATE.after_fork_parent()
    assert getattr(cache._local, 'con', None) is None
    assert con not in dc.core._INHERITED_CONNECTIONS
    with pytest.raises(sqlite3.ProgrammingError):
        con.execute('SELECT 1')
    assert cache.get('a') == 1  # Reconnects on use.


def test_pid_change_discards_connections(cache):
    # The fallback for a fork the at-fork handler did not see.
    cache.set('a', 1)
    con = cache._local.con
    cache._cons.pid = -1
    assert cache.get('a') == 1
    assert cache._local.con is not con
    assert cache._cons.pid == os.getpid()
    assert con in dc.core._INHERITED_CONNECTIONS
    forget_inherited(con)


def test_close_after_pid_change_discards_connections(cache):
    cache.set('a', 1)
    con = cache._local.con
    cache._cons.pid = -1
    cache.close()
    assert con in dc.core._INHERITED_CONNECTIONS
    assert cache._cons.pid == os.getpid()
    assert cache.get('a') == 1
    forget_inherited(con)


def test_close_all_after_pid_change_discards_connections():
    cons = dc.core._Connections()
    con = sqlite3.connect(':memory:', check_same_thread=False)
    sentinel = dc.core._ThreadSentinel()
    assert cons.add(threading.get_ident(), sentinel, con) == []
    cons.pid = -1
    cons.close_all()
    assert con in dc.core._INHERITED_CONNECTIONS
    forget_inherited(con)


def test_connections_add_replaces_same_thread(cache):
    cons = dc.core._Connections()
    sentinel = dc.core._ThreadSentinel()
    first = sqlite3.connect(':memory:', check_same_thread=False)
    second = sqlite3.connect(':memory:', check_same_thread=False)
    ident = threading.get_ident()
    assert cons.add(ident, sentinel, first) == []
    assert cons.add(ident, sentinel, second) == [first]
    assert cons.pop(ident) == [second]
    assert cons.pop(ident) == []
    first.close()
    second.close()


def test_fork_gate_timeout():
    gate = dc.core._ForkGate()
    gate.timeout = 0.05
    entered = threading.Event()
    release = threading.Event()

    def hold():
        with gate:
            entered.set()
            release.wait(10)

    thread = threading.Thread(target=hold)
    thread.start()
    assert entered.wait(10)

    with pytest.warns(RuntimeWarning, match='forking while'):
        gate.before_fork()

    gate.after_fork_parent()
    release.set()
    thread.join(10)


def test_fork_gate_nesting_and_child_reset():
    gate = dc.core._ForkGate()

    with gate:
        with gate:
            assert gate._active == 1
        gate.before_fork()  # The forking thread's own transaction.
        gate.after_fork_parent()
        assert gate._active == 1

    assert gate._active == 0

    with gate:
        gate.after_fork_child()

    assert gate._active == 0


def test_fork_gate_blocks_new_transactions_while_forking():
    gate = dc.core._ForkGate()
    gate.before_fork()
    entered = threading.Event()

    def enter():
        with gate:
            entered.set()

    thread = threading.Thread(target=enter)
    thread.start()
    assert not entered.wait(0.2)
    gate.after_fork_parent()
    assert entered.wait(10)
    thread.join(10)


@pytest.mark.skipif(not hasattr(os, 'fork'), reason='requires os.fork')
def test_fork_child_opens_its_own_connections(cache):
    # Two caches on one directory, then fork: upstream issue 325.
    other = dc.Cache(cache.directory)
    cache.set('parent', 1)
    other.set('other', 2)
    inherited = len(dc.core._INHERITED_CONNECTIONS)
    read_fd, write_fd = os.pipe()
    pid = os.fork()

    if pid == 0:  # pragma: no cover
        try:
            checks = (
                cache.get('parent') == 1,
                other.get('other') == 2,
                # Both connections were closed before the fork.
                len(dc.core._INHERITED_CONNECTIONS) == inherited,
            )
            other.set('child', 3)
            os.write(write_fd, bytes(checks))
        except BaseException:
            os.write(write_fd, b'\xff')
        finally:
            os._exit(0)

    os.close(write_fd)
    assert wait_for_child(pid) == 0
    assert os.read(read_fd, 3) == b'\x01\x01\x01'
    os.close(read_fd)
    assert other.get('child') == 3
    other.close()


@pytest.mark.skipif(not hasattr(os, 'fork'), reason='requires os.fork')
def test_fork_waits_for_transactions_in_other_threads(cache):
    entered = threading.Event()
    release = threading.Event()

    def hold():
        with cache.transact():
            cache.set('held', 1)
            entered.set()
            release.wait(10)

    holder = threading.Thread(target=hold)
    holder.start()
    assert entered.wait(10)
    forked = threading.Event()
    pids = []
    read_fd, write_fd = os.pipe()

    def forker():
        pid = os.fork()
        if pid == 0:  # pragma: no cover
            try:
                cache.set('child', 2)
                os.write(write_fd, b'\x01')
            except BaseException:
                os.write(write_fd, b'\xff')
            finally:
                os._exit(0)
        pids.append(pid)
        forked.set()

    thread = threading.Thread(target=forker)
    thread.start()
    assert not forked.wait(0.5)  # The fork waits for the transaction.
    release.set()
    holder.join(10)
    assert forked.wait(10)
    thread.join(10)
    os.close(write_fd)
    assert wait_for_child(pids[0]) == 0
    assert os.read(read_fd, 1) == b'\x01'
    os.close(read_fd)
    assert cache.get('held') == 1
    assert cache.get('child') == 2


@pytest.mark.parametrize('statistics', [False, True])
def test_get_store_time(cache, statistics):
    if statistics:
        cache.stats(enable=True)  # Take the transactional path in get.

    before = time.time()
    cache.set(0, 0, tag='number')
    after = time.time()

    value, store_time = cache.get(0, store_time=True)
    assert value == 0
    assert isinstance(store_time, float)
    assert before <= store_time <= after
    assert cache.get(0, store_time=True) == (0, store_time)
    assert cache.get(0, expire_time=True, store_time=True) == (
        0,
        None,
        store_time,
    )
    assert cache.get(0, tag=True, store_time=True) == (0, 'number', store_time)
    assert cache.get(0, expire_time=True, tag=True, store_time=True) == (
        0,
        None,
        'number',
        store_time,
    )
    assert cache.get(0, expire_time=True, tag=True) == (0, None, 'number')
    assert cache.get(0) == 0

    assert cache.get(1, store_time=True) == (None, None)
    assert cache.get(1, default=7, tag=True, store_time=True) == (
        7,
        None,
        None,
    )
    assert cache.get(1, expire_time=True, tag=True, store_time=True) == (
        None,
        None,
        None,
        None,
    )


def test_get_store_time_read(cache):
    cache.set('key', io.BytesIO(b'value'), read=True)
    reader, store_time = cache.get('key', read=True, store_time=True)
    assert reader.read() == b'value'
    assert isinstance(store_time, float)
