"""Test SafeDisk.with_signing()."""

import collections as co
import contextlib
import errno
import functools
import hashlib
import hmac
import math
import multiprocessing
import os
import os.path as op
import pickle
import sqlite3
import stat
import threading
import tracemalloc
import types
import typing
import warnings

import pytest

import diskcache_community as dc
from diskcache_community import signing
from diskcache_community.core import MODE_PICKLE, MODE_RAW

pytestmark = pytest.mark.filterwarnings('ignore', category=dc.EmptyDirWarning)

KEY = bytes(range(32))
OTHER_KEY = bytes(range(1, 33))
POSIX = os.name != 'nt'
ROOT = POSIX and os.geteuid() == 0
INLINE, FILE = 2**20, 0

Signed = dc.SafeDisk.with_signing()
Miss = Signed.with_options(on_error='miss')


def _execute(path):
    """Marker that a pickle ran code: it creates `path`."""
    with open(path, 'w', encoding='utf-8') as writer:
        writer.write('executed')
    return 'executed'


class Poison:
    """Object whose pickle calls `_execute` when loaded."""

    def __init__(self, path):
        self.path = path

    def __reduce__(self):
        return (_execute, (self.path,))


class Point:
    """A class outside every allowlist."""

    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __eq__(self, other):
        return type(other) is Point and (self.x, self.y) == (other.x, other.y)

    def __hash__(self):
        return hash((self.x, self.y))

    def norm(self):
        return abs(self.x) + abs(self.y)


def square(number):
    return number * number


T = typing.TypeVar('T')


class Box(typing.Generic[T]):
    def __init__(self, item):
        self.item = item


Pair = co.namedtuple('Pair', 'left right')


@pytest.fixture(autouse=True)
def key_file(tmp_path, monkeypatch):
    """Point the default key file of every test at its own folder."""
    path = tmp_path / 'keys' / 'signing.key'
    monkeypatch.setenv(signing.ENV_KEY_FILE, str(path))
    return path


@pytest.fixture
def directory(tmp_path):
    return str(tmp_path / 'cache')


def connect(directory):
    return contextlib.closing(sqlite3.connect(op.join(directory, 'cache.db')))


def row(directory, key):
    """Return the mode, filename and value columns of the row of `key`."""
    with connect(directory) as con:
        return con.execute(
            'SELECT mode, filename, value FROM Cache WHERE key = ?', (key,)
        ).fetchone()


def update(directory, which, **columns):
    """Set `columns` of the row whose key is `which`."""
    names = ', '.join('%s = ?' % name for name in columns)
    with connect(directory) as con:
        con.execute(
            'UPDATE Cache SET %s WHERE key = ?' % names,
            tuple(columns.values()) + (which,),
        )
        con.commit()


def flip(data, index):
    data = bytearray(data)
    data[index] ^= 1
    return bytes(data)


def mac_key(key):
    return hmac.new(key, signing._MAC_LABEL, hashlib.sha256).digest()


def write_key_file(path, data, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    path.write_bytes(data)
    os.chmod(path, mode)
    return path


# Round trips


@pytest.mark.parametrize('size', [INLINE, FILE], ids=['inline', 'file'])
def test_objects_no_allowlist_holds_round_trip(directory, size):
    point = Point(1, -2)
    value = {
        'point': point,
        'function': square,
        'bound method': point.norm,
        'alias': Box[int],
        'instance of an alias': Box[int](3),
        'partial': functools.partial(max, 1),
        'ordered': co.OrderedDict(a=1),
    }

    with dc.Cache(directory, disk=Signed, disk_min_file_size=size) as cache:
        cache['key'] = value
        result = cache['key']
        assert cache.get('key', read=True)['point'] == point

    assert result['point'] == point
    assert result['function'] is square
    assert result['bound method']() == 3
    assert result['alias'] == Box[int]
    assert result['instance of an alias'].item == 3
    assert result['partial'](0) == 1
    assert result['ordered'] == co.OrderedDict(a=1)

    mode, filename, db_value = row(directory, 'key')
    assert mode == MODE_PICKLE
    assert db_value[:4] == signing.MAGIC
    if size == FILE:
        assert len(db_value) == signing.PREFIX_SIZE
        path = op.join(directory, filename)
        assert open(path, 'rb').read()[:1] == b'\x80'
    else:
        assert filename is None
        assert len(db_value) > signing.PREFIX_SIZE


def test_values_stored_without_pickling_are_stored_as_on_every_disk(
    directory,
):
    values = {'str': 'text', 'bytes': b'\x00\xff', 'int': -7, 'float': 1.5}

    with dc.Cache(directory, disk=Signed) as cache:
        for key, value in values.items():
            cache[key] = value

    for key in values:
        assert row(directory, key)[0] == MODE_RAW

    with dc.Cache(directory, disk=dc.SafeDisk) as cache:
        assert {key: cache[key] for key in values} == values


def test_nan_and_large_int_values_are_signed(directory):
    with dc.Cache(directory, disk=Signed) as cache:
        cache['nan'] = float('nan')
        cache['large'] = 2**70
        assert math.isnan(cache['nan'])
        assert cache['large'] == 2**70

    assert row(directory, 'nan')[2][:4] == signing.MAGIC
    assert row(directory, 'large')[2][:4] == signing.MAGIC


def test_values_that_cannot_be_pickled_raise_type_error(directory):
    with dc.Cache(directory, disk=Signed) as cache:
        with pytest.raises(TypeError, match='cannot store value'):
            cache['key'] = lambda: None
        with pytest.raises(TypeError):
            cache['key'] = threading.Lock()
        assert 'key' not in cache


@pytest.mark.parametrize(
    'settings',
    [{}, {'statistics': True}, {'eviction_policy': 'least-recently-used'}],
    ids=['metadata', 'statistics', 'eviction policy'],
)
def test_every_path_of_get_checks_the_cache_key(directory, settings):
    with dc.Cache(directory, disk=Signed, **settings) as cache:
        cache.set('a', Point(1, 1), expire=60, tag='first')
        cache.set('b', Point(2, 2))
        value, _, tag = cache.get('a', expire_time=True, tag=True)
        assert (value, tag) == (Point(1, 1), 'first')
        assert cache['a'] == Point(1, 1)

    _, _, value = row(directory, 'a')
    update(directory, 'b', value=value)

    with dc.Cache(directory, disk=Signed, **settings) as cache:
        with pytest.raises(pickle.UnpicklingError, match='does not match'):
            cache.get('b', tag=True)
        with pytest.raises(pickle.UnpicklingError, match='does not match'):
            cache['b']


def test_read_only_cache_reads_signed_rows(directory):
    with dc.Cache(directory, disk=Signed) as cache:
        cache['key'] = Point(1, 2)

    with dc.Cache(directory, disk=Signed, read_only=True) as cache:
        assert cache['key'] == Point(1, 2)


# Refusals


@pytest.mark.parametrize('size', [INLINE, FILE], ids=['inline', 'file'])
@pytest.mark.parametrize('planted', ['poison', 'plain dict'])
def test_unsigned_pickles_are_refused(directory, tmp_path, size, planted):
    marker = tmp_path / 'marker'
    value = Poison(str(marker)) if planted == 'poison' else {'plain': 1}

    with dc.Cache(directory, disk=dc.Disk, disk_min_file_size=size) as cache:
        cache['key'] = value

    with dc.Cache(directory, disk=Signed) as cache:
        with pytest.raises(pickle.UnpicklingError, match='unsigned'):
            cache['key']
        assert 'key' in cache

    with dc.Cache(directory, disk=Miss) as cache:
        assert cache.get('key') is None
        assert 'key' not in cache

    assert not marker.exists()


@pytest.mark.parametrize('size', [INLINE, FILE], ids=['inline', 'file'])
@pytest.mark.parametrize('where', ['tag', 'pickle'])
def test_tampered_rows_are_refused(directory, size, where):
    with dc.Cache(directory, disk=Signed, disk_min_file_size=size) as cache:
        cache['key'] = Point(1, 2)

    _, filename, value = row(directory, 'key')
    if where == 'tag':
        update(directory, 'key', value=flip(value, 20))
    elif filename is None:
        update(directory, 'key', value=flip(value, len(value) - 2))
    else:
        path = op.join(directory, filename)
        with open(path, 'rb') as reader:
            data = reader.read()
        with open(path, 'wb') as writer:
            writer.write(flip(data, len(data) - 2))

    with dc.Cache(directory, disk=Signed) as cache:
        with pytest.raises(pickle.UnpicklingError, match='does not match'):
            cache['key']


def test_rows_signed_with_another_key_are_refused(directory, tmp_path):
    with dc.Cache(directory, disk=Signed) as cache:
        cache['key'] = Point(1, 2)

    others = [
        dc.SafeDisk.with_signing(tmp_path / 'other.key'),
        dc.SafeDisk.with_signing(key=KEY),
    ]
    for disk in others:
        with dc.Cache(directory, disk=disk) as cache:
            with pytest.raises(pickle.UnpicklingError, match='another key'):
                cache['key']


def test_users_with_different_keys_delete_each_others_rows_under_miss(
    directory, tmp_path
):
    with dc.Cache(directory, disk=Signed) as cache:
        cache['key'] = Point(1, 2)

    other = dc.SafeDisk.with_signing(tmp_path / 'other.key')
    with dc.Cache(
        directory, disk=other.with_options(on_error='miss')
    ) as cache:
        assert cache.get('key') is None
        assert len(cache) == 0


@pytest.mark.parametrize('size', [INLINE, FILE], ids=['inline', 'file'])
def test_a_value_moved_under_another_key_is_refused(directory, size):
    with dc.Cache(directory, disk=Signed, disk_min_file_size=size) as cache:
        cache['a'] = Point(1, 1)
        cache['b'] = Point(2, 2)

    _, filename_a, value_a = row(directory, 'a')
    _, filename_b, value_b = row(directory, 'b')
    update(directory, 'a', filename=filename_b, value=value_b)
    update(directory, 'b', filename=filename_a, value=value_a)

    with dc.Cache(directory, disk=Signed) as cache:
        for key in 'ab':
            with pytest.raises(pickle.UnpicklingError, match='does not match'):
                cache[key]


def test_rows_of_the_wrong_shape_or_version_are_refused(directory):
    with dc.Cache(directory, disk=Signed, disk_min_file_size=FILE) as cache:
        cache['file'] = Point(1, 1)
    with dc.Cache(directory, disk=Signed, disk_min_file_size=INLINE) as cache:
        cache['inline'] = Point(1, 1)

    _, _, prefix = row(directory, 'file')
    _, _, inline = row(directory, 'inline')
    cases = [
        ('inline', dict(value=prefix), 'wrong shape'),
        ('inline', dict(value=signing.MAGIC + b'\x01'), 'wrong shape'),
        ('file', dict(value=prefix + b'\x00'), 'wrong shape'),
        ('inline', dict(value=inline[:4] + b'\x02' + inline[5:]), 'version 2'),
    ]

    for key, columns, message in cases:
        original = row(directory, key)
        update(directory, key, **columns)
        with dc.Cache(directory, disk=Signed) as cache:
            with pytest.raises(pickle.UnpicklingError, match=message):
                cache[key]
        update(directory, key, filename=original[1], value=original[2])


def test_a_signed_row_read_without_its_cache_key_is_refused(directory):
    with dc.Cache(directory, disk=Signed) as cache:
        cache['key'] = Point(1, 2)
        mode, filename, value = row(directory, 'key')
        with pytest.raises(pickle.UnpicklingError, match='without its cache'):
            cache.disk.fetch(mode, filename, value, False)


def _planted_large_file(directory):
    with dc.Cache(directory, disk=Signed, disk_min_file_size=FILE) as cache:
        cache['key'] = Point(1, 2)
    _, filename, _ = row(directory, 'key')
    return op.join(directory, filename)


def _peak_while(function):
    tracemalloc.start()
    try:
        function()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def test_a_large_planted_file_is_refused_in_constant_memory(directory):
    path = _planted_large_file(directory)
    with open(path, 'r+b') as writer:
        writer.truncate(2**25)

    def read():
        with dc.Cache(directory, disk=Signed) as cache:
            with pytest.raises(pickle.UnpicklingError, match='does not match'):
                cache['key']

    assert _peak_while(read) < 2**23

    with dc.Cache(directory, disk=Miss) as cache:
        assert cache.get('key') is None
    assert not op.exists(path)


def test_a_file_rewritten_between_the_two_passes_is_refused(
    directory, monkeypatch
):
    path = _planted_large_file(directory)
    check_tag = signing._check_tag
    calls = []

    def check_then_rewrite(expected, tag):
        check_tag(expected, tag)
        if not calls:
            calls.append(1)
            with open(path, 'r+b') as writer:
                writer.write(b'\x80' * 64)
                writer.truncate(2**25)

    monkeypatch.setattr(signing, '_check_tag', check_then_rewrite)

    def read():
        with dc.Cache(directory, disk=Signed) as cache:
            with pytest.raises(pickle.UnpicklingError, match='does not match'):
                cache['key']

    assert _peak_while(read) < 2**23
    assert calls == [1]


# Cache keys


def test_numeric_keys_that_sqlite_matches_verify_on_every_path(directory):
    with dc.Cache(directory, disk=Signed) as cache:
        cache[1.0] = Point(1, 1)
        cache[0.0] = Point(0, 0)
        cache[-(2.0**63)] = Point(-1, -1)
        cache[2.0**63] = Point(9, 9)

        assert cache.get(1) == Point(1, 1)
        assert cache[-0.0] == Point(0, 0)
        assert cache[-(2**63)] == Point(-1, -1)
        assert cache[2.0**63] == Point(9, 9)
        assert cache.peekitem(last=False) == (1.0, Point(1, 1))
        assert cache.peekitem() == (2.0**63, Point(9, 9))
        assert cache.peek() == (1.0, Point(1, 1))
        assert cache.pull() == (1.0, Point(1, 1))
        assert cache.pop(0) == Point(0, 0)


def test_nan_keys_are_refused(directory):
    with dc.Cache(directory, disk=Signed) as cache:
        with pytest.raises(TypeError, match='NaN'):
            cache[float('nan')] = Point(1, 2)
        with pytest.raises(TypeError, match='NaN'):
            cache.get(float('nan'))


def test_a_row_whose_key_is_null_is_refused(directory):
    with dc.Cache(directory, disk=Signed) as cache:
        cache['key'] = Point(1, 2)
    update(directory, 'key', key=None)

    with dc.Cache(directory, disk=Signed) as cache:
        with pytest.raises(pickle.UnpicklingError, match='NULL'):
            cache.peekitem()

    with dc.Cache(directory, disk=Miss) as cache:
        with pytest.raises(KeyError):
            cache.peekitem()
        assert len(cache) == 0


@pytest.mark.parametrize('size', [INLINE, FILE], ids=['inline', 'file'])
def test_push_and_pull_round_trip(directory, size):
    with dc.Cache(directory, disk=Signed, disk_min_file_size=size) as cache:
        for number in range(3):
            cache.push(Point(number, number))
        cache.push(Point(9, 9), prefix='queue', side='front')
        cache.push('plain')

        assert cache.peek()[1] == Point(0, 0)
        assert [cache.pull()[1] for _ in range(4)] == [
            Point(number, number) for number in range(3)
        ] + ['plain']
        assert cache.pull(prefix='queue')[1] == Point(9, 9)


def test_str_bytes_and_pickled_keys_are_kept_apart(directory):
    with dc.Cache(directory, disk=Signed) as cache:
        cache['k'] = Point(1, 1)
        cache[b'k'] = Point(2, 2)
        cache[('k',)] = Point(3, 3)
        assert [cache['k'], cache[b'k'], cache[('k',)]] == [
            Point(1, 1),
            Point(2, 2),
            Point(3, 3),
        ]

    _, _, value = row(directory, 'k')
    update(directory, b'k', value=value)
    with dc.Cache(directory, disk=Signed) as cache:
        with pytest.raises(pickle.UnpicklingError, match='does not match'):
            cache[b'k']


def test_a_pushed_value_moved_to_another_key_is_refused(directory):
    with dc.Cache(directory, disk=Signed) as cache:
        first = cache.push(Point(1, 1))
        second = cache.push(Point(2, 2))
        cache['other'] = 'plain'

    _, _, value = row(directory, first)
    update(directory, 'other', mode=MODE_PICKLE, value=value)
    update(directory, second, value=value)

    with dc.Cache(directory, disk=Signed) as cache:
        assert cache.pull() == (first, Point(1, 1))
        for read in (lambda: cache['other'], cache.pull):
            with pytest.raises(pickle.UnpicklingError, match='does not match'):
                read()


def test_push_hashes_the_value_before_its_transaction(directory, monkeypatch):
    events = []
    store, finish = signing.store, signing.finish

    def recording_store(*args):
        result = store(*args)
        events.append('hashed')
        return result

    def recording_finish(*args):
        events.append('signed')
        return finish(*args)

    monkeypatch.setattr(signing, 'store', recording_store)
    monkeypatch.setattr(signing, 'finish', recording_finish)

    with dc.Cache(directory, disk=Signed) as cache:
        transact = cache._transact

        @contextlib.contextmanager
        def recording_transact(*args, **kwargs):
            with transact(*args, **kwargs) as result:
                events.append('began')
                yield result

        monkeypatch.setattr(cache, '_transact', recording_transact)
        cache.push(Point(1, 1))
        assert cache.pull()[1] == Point(1, 1)

    assert events[:3] == ['hashed', 'began', 'signed']


def _push_many(directory, count):
    with dc.Cache(directory, disk=Signed) as cache:
        for number in range(count):
            cache.push(Point(os.getpid(), number))


def test_two_processes_pushing_at_once(directory):
    with dc.Cache(directory, disk=Signed) as cache:
        cache.push(Point(0, 0))

    context = multiprocessing.get_context('spawn')
    processes = [
        context.Process(target=_push_many, args=(directory, 50))
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(60)
    assert [process.exitcode for process in processes] == [0, 0]

    with dc.Cache(directory, disk=Signed) as cache:
        values = [cache.pull()[1] for _ in range(101)]
        assert cache.pull() == (None, None)
    assert all(type(value) is Point for value in values)
    assert len(set(values)) == 101


def test_housekeeping_on_signed_file_rows(directory):
    with dc.Cache(
        directory, disk=Signed, disk_min_file_size=FILE, tag_index=True
    ) as cache:
        cache.set('a', Point(1, 1), tag='first')
        cache.set('b', Point(2, 2), tag='second')

        with warnings.catch_warnings():
            warnings.simplefilter('error')
            assert cache.check(fix=True) == []

        assert cache.evict('first') == 1
        assert cache['b'] == Point(2, 2)
        assert cache.volume() > 0

        cache.reset('size_limit', 0)
        assert cache.cull() >= 1
        assert len(cache) == 0

    files = [name for _, _, names in os.walk(directory) for name in names]
    assert all(name.startswith('cache.db') for name in files)


# Key files


def test_a_key_file_inside_the_cache_directory_is_refused(directory):
    os.makedirs(directory)
    for path in ('signing.key', op.join('sub', 'signing.key')):
        disk = dc.SafeDisk.with_signing(op.join(directory, path))
        with pytest.raises(ValueError, match='inside the cache directory'):
            dc.Cache(directory, disk=disk)


@pytest.mark.skipif(not POSIX, reason='symlinks need privileges on Windows')
def test_a_symlink_to_a_key_file_inside_the_cache_is_refused(
    directory, tmp_path
):
    os.makedirs(directory)
    target = write_key_file(
        tmp_path / 'cache' / 'hidden.key', KEY.hex().encode()
    )
    link = tmp_path / 'link.key'
    link.symlink_to(target)

    with pytest.raises(ValueError, match='inside the cache directory'):
        dc.Cache(directory, disk=dc.SafeDisk.with_signing(link))


def test_a_key_file_spelled_with_another_case_is_refused(directory):
    os.makedirs(directory)
    swapped = op.join(op.dirname(directory), op.basename(directory).upper())
    if not op.exists(swapped) or not op.samefile(swapped, directory):
        pytest.skip('the file system is case-sensitive')

    disk = dc.SafeDisk.with_signing(op.join(swapped, 'signing.key'))
    with pytest.raises(ValueError, match='inside the cache directory'):
        dc.Cache(directory, disk=disk)


def test_a_key_file_in_a_fanout_cache_directory_is_refused(tmp_path):
    root = tmp_path / 'fanout'
    disk = dc.SafeDisk.with_signing(root / 'signing.key')
    with pytest.raises(ValueError, match='inside the cache directory'):
        dc.FanoutCache(str(root), disk=disk, shards=2)


def test_a_zero_inode_falls_back_to_comparing_paths(
    directory, tmp_path, monkeypatch
):
    os.makedirs(directory)
    os.makedirs(tmp_path / 'keys')
    real_stat = os.stat

    def stat_without_inode(path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        return os.stat_result(result[:1] + (0,) + result[2:10])

    monkeypatch.setattr(signing.os, 'stat', stat_without_inode)
    inside = op.join(op.realpath(directory), 'signing.key')
    outside = op.join(op.realpath(tmp_path), 'keys', 'signing.key')
    assert signing._inside(inside, directory)
    assert not signing._inside(outside, directory)


def test_the_environment_variable_names_the_default_key_file(
    tmp_path, monkeypatch, directory
):
    path = tmp_path / 'elsewhere' / 'my.key'
    monkeypatch.setenv(signing.ENV_KEY_FILE, str(path))
    assert signing.default_key_file() == str(path)

    with dc.Cache(directory, disk=Signed):
        pass
    assert path.exists()


@pytest.mark.parametrize(
    'platform, environ, home, expected',
    [
        ('linux', {'XDG_DATA_HOME': '/data'}, '/home/u', '/data'),
        ('linux', {}, '/home/u', op.join('/home/u', '.local', 'share')),
        (
            'linux',
            {'XDG_DATA_HOME': 'relative'},
            '/home/u',
            op.join('/home/u', '.local', 'share'),
        ),
        (
            'darwin',
            {},
            '/Users/u',
            op.join('/Users/u', 'Library', 'Application Support'),
        ),
        ('win32', {'LOCALAPPDATA': '/appdata'}, '/home/u', '/appdata'),
        ('win32', {}, '/home/u', None),
        ('linux', {}, '~', None),
    ],
)
def test_data_directory(platform, environ, home, expected):
    assert signing.data_directory(environ, platform, home) == expected


def test_the_default_key_file_is_in_the_data_directory(
    tmp_path, monkeypatch, directory
):
    monkeypatch.delenv(signing.ENV_KEY_FILE)
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'data'))

    path = signing.default_key_file()
    assert path.startswith(str(tmp_path))
    assert path.endswith(op.join('diskcache-community', 'signing.key'))

    with dc.Cache(directory, disk=Signed):
        pass
    assert op.exists(path)


def test_no_home_directory_raises_with_a_hint(monkeypatch):
    monkeypatch.delenv(signing.ENV_KEY_FILE)
    monkeypatch.setattr(signing, 'data_directory', lambda *args: None)
    with pytest.raises(OSError, match=signing.ENV_KEY_FILE):
        signing.default_key_file()


@pytest.mark.skipif(not POSIX, reason='POSIX modes')
def test_a_new_key_file_is_private(directory, key_file):
    with dc.Cache(directory, disk=Signed):
        pass

    assert stat.S_IMODE(os.stat(key_file).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(key_file.parent).st_mode) == 0o700
    content = key_file.read_bytes()
    assert len(content) == 65 and content.endswith(b'\n')
    bytes.fromhex(content.decode('ascii'))
    assert os.listdir(key_file.parent) == ['signing.key']


def test_concurrent_first_use_creates_one_key(tmp_path, directory):
    os.makedirs(directory)
    path = str(tmp_path / 'new' / 'signing.key')
    barrier = threading.Barrier(16)
    key_ids = []

    def load():
        barrier.wait()
        key_ids.append(signing.KeyFile(path).load(directory)[0].key_id)

    threads = [threading.Thread(target=load) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(key_ids) == 16
    assert len(set(key_ids)) == 1
    assert os.listdir(op.dirname(path)) == ['signing.key']


def test_a_file_system_without_hard_links(tmp_path, directory, monkeypatch):
    os.makedirs(directory)

    def no_link(source, target):
        raise OSError(errno.EPERM, 'hard links are not supported')

    monkeypatch.setattr(signing.os, 'link', no_link)
    path = str(tmp_path / 'new' / 'signing.key')
    barrier = threading.Barrier(8)
    key_ids = []

    def load():
        barrier.wait()
        key_ids.append(signing.KeyFile(path).load(directory)[0].key_id)

    threads = [threading.Thread(target=load) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(key_ids) == 8
    assert len(set(key_ids)) == 1
    assert os.listdir(op.dirname(path)) == ['signing.key']


@pytest.mark.skipif(not POSIX or ROOT, reason='POSIX modes, not as root')
def test_a_key_file_that_cannot_be_created_raises_with_a_hint(
    tmp_path, directory
):
    os.makedirs(directory)
    folder = tmp_path / 'read-only'
    folder.mkdir()
    folder.chmod(0o500)
    try:
        disk = dc.SafeDisk.with_signing(folder / 'keys' / 'signing.key')
        with pytest.raises(OSError, match=signing.ENV_KEY_FILE):
            dc.Cache(directory, disk=disk)
    finally:
        folder.chmod(0o700)


@pytest.mark.skipif(not POSIX or ROOT, reason='POSIX modes, not as root')
@pytest.mark.parametrize(
    'mode, message',
    [
        (0o620, 'written by other users'),
        (0o602, 'written by other users'),
        (0o640, 'chmod 600'),
        (0o604, 'chmod 600'),
    ],
)
def test_key_files_other_users_can_use_are_refused(
    directory, key_file, mode, message
):
    with dc.Cache(directory, disk=Signed):
        pass
    key_file.chmod(mode)

    with pytest.raises(ValueError, match=message):
        dc.Cache(directory, disk=Signed)


@pytest.mark.skipif(not POSIX or ROOT, reason='POSIX modes, not as root')
def test_a_key_folder_others_can_write_is_refused_unless_sticky(
    directory, key_file
):
    with dc.Cache(directory, disk=Signed):
        pass

    key_file.parent.chmod(0o770)
    with pytest.raises(ValueError, match='folder'):
        dc.Cache(directory, disk=Signed)

    key_file.parent.chmod(0o1777)
    with dc.Cache(directory, disk=Signed):
        pass
    key_file.parent.chmod(0o700)


@pytest.mark.skipif(not POSIX or ROOT, reason='POSIX modes, not as root')
def test_the_environment_variable_cannot_name_a_shared_key(
    tmp_path, monkeypatch, directory
):
    path = write_key_file(tmp_path / 'shared.key', KEY.hex().encode(), 0o644)
    monkeypatch.setenv(signing.ENV_KEY_FILE, str(path))
    with pytest.raises(ValueError, match='chmod 600'):
        dc.Cache(directory, disk=Signed)


@pytest.mark.skipif(not POSIX, reason='POSIX modes')
def test_owners_of_key_files(key_file):
    write_key_file(key_file, KEY.hex().encode())
    path = str(key_file)
    uid = os.geteuid()

    def status(mode, owner):
        return os.stat_result((mode, 0, 0, 1, owner, 0, 0, 0, 0, 0))

    # A root-owned secret that others can read, as containers mount them.
    signing.check_permissions(status(stat.S_IFREG | 0o444, 0), path)
    signing.check_permissions(status(stat.S_IFREG | 0o600, uid), path)

    with pytest.raises(ValueError, match='belongs to uid'):
        signing.check_permissions(status(stat.S_IFREG | 0o600, uid + 1), path)
    with pytest.raises(ValueError, match='not a file'):
        signing.check_permissions(status(stat.S_IFDIR | 0o700, uid), path)


def test_permissions_are_not_checked_on_windows(key_file, monkeypatch):
    write_key_file(key_file, KEY.hex().encode())
    shared = os.stat_result(
        (stat.S_IFREG | 0o666, 0, 0, 1, 12345, 0) + (0,) * 4
    )
    monkeypatch.setattr(os, 'name', 'nt')
    signing.check_permissions(shared, str(key_file))


def test_only_a_trailing_newline_is_stripped(tmp_path, directory):
    os.makedirs(directory)
    expected = signing.InMemoryKey(KEY).key.key_id

    def key_id(name, content):
        path = write_key_file(tmp_path / name, content)
        return signing.KeyFile(str(path)).load(directory)[0].key_id

    assert key_id('plain', KEY) == expected
    assert key_id('newline', KEY + b'\n') == expected
    assert key_id('crlf', KEY + b'\r\n') == expected
    assert key_id('space', KEY + b' \n') != expected
    assert key_id('leading', b' ' + KEY) != expected


def test_key_files_of_the_wrong_size_are_refused(tmp_path, directory):
    os.makedirs(directory)
    short = write_key_file(tmp_path / 'short', b'x' * 31 + b'\n')
    long = write_key_file(tmp_path / 'long', b'x' * 5000)

    with pytest.raises(ValueError, match='at least 32 bytes, not 31'):
        signing.KeyFile(str(short)).load(directory)
    with pytest.raises(ValueError, match='at most'):
        signing.KeyFile(str(long)).load(directory)


# Keeping the key out of sight


def _contains(value, secrets):
    if isinstance(value, (bytes, bytearray, memoryview)):
        data = bytes(value)
    elif isinstance(value, str):
        data = value.encode('utf-8', 'surrogatepass')
    else:
        data = repr(value).encode('utf-8', 'backslashreplace')
    return any(secret in data for secret in secrets)


def _secrets(key):
    derived = mac_key(key)
    return [key, key.hex().encode(), derived, derived.hex().encode()]


def test_the_key_never_appears_in_pickles_or_reprs(directory, tmp_path):
    with dc.Cache(directory, disk=Signed) as cache:
        cache['key'] = Point(1, 2)
        with open(signing.default_key_file(), 'rb') as reader:
            secrets = _secrets(reader.read().rstrip(b'\n'))
        shown = [
            pickle.dumps(cache),
            pickle.dumps(type(cache.disk)),
            repr(type(cache.disk)),
            repr(cache.disk.signing),
            repr(vars(cache.disk)),
            repr(cache.disk._signing_key),
        ]

    with dc.FanoutCache(str(tmp_path / 'fanout'), disk=Signed) as cache:
        shown.append(pickle.dumps(cache))
    shown.append(pickle.dumps(dc.Deque(directory=str(tmp_path / 'deque'))))
    shown.append(pickle.dumps(dc.Index(str(tmp_path / 'index'))))

    for item in shown:
        assert not _contains(item, secrets)


def test_an_in_memory_key_is_never_pickled(directory, tmp_path):
    disk = dc.SafeDisk.with_signing(key=KEY)
    assert KEY.hex() not in repr(disk)
    assert signing.InMemoryKey(KEY).key.key_id.hex() in repr(disk)

    with pytest.raises(TypeError, match='in-memory'):
        pickle.dumps(disk)
    with dc.Cache(directory, disk=disk) as cache:
        with pytest.raises(TypeError, match='in-memory'):
            pickle.dumps(cache)
        with pytest.raises(TypeError, match='cannot be pickled'):
            pickle.dumps(cache.disk._signing_key)
    with dc.FanoutCache(str(tmp_path / 'fanout'), disk=disk) as cache:
        with pytest.raises(TypeError, match='in-memory'):
            pickle.dumps(cache)


def _library_locals(traceback):
    package = op.dirname(dc.__file__)
    while traceback is not None:
        frame = traceback.tb_frame
        if frame.f_code.co_filename.startswith(package):
            yield from frame.f_locals.values()
        traceback = traceback.tb_next


def test_tracebacks_of_refused_rows_hold_no_key_bytes(directory):
    disk = dc.SafeDisk.with_signing(key=KEY)
    with dc.Cache(directory, disk=disk) as cache:
        cache['key'] = Point(1, 2)
    update(directory, 'key', value=flip(row(directory, 'key')[2], 20))

    with dc.Cache(directory, disk=disk) as cache:
        with pytest.raises(pickle.UnpicklingError) as info:
            cache['key']

    values = list(_library_locals(info.value.__traceback__))
    assert values
    assert not any(_contains(value, _secrets(KEY)) for value in values)


def test_tracebacks_of_short_keys_hold_no_key_bytes(tmp_path, directory):
    os.makedirs(directory)
    content = b'secret-but-too-short\n'
    path = write_key_file(tmp_path / 'short', content)

    with pytest.raises(ValueError) as info:
        signing.KeyFile(str(path)).load(directory)
    for value in _library_locals(info.value.__traceback__):
        assert not _contains(value, [content.strip()])

    with pytest.raises(ValueError) as info:
        dc.SafeDisk.with_signing(key=b'secret-but-too-short')
    assert 'secret' not in str(info.value)


# Combinations


def test_with_types_widens_only_what_keys_may_hold(directory):
    disk = dc.SafeDisk.with_types(Pair).with_signing()
    with dc.Cache(directory, disk=disk) as cache:
        cache[Pair(1, 2)] = Point(1, 2)
        assert cache[Pair(1, 2)] == Point(1, 2)
        with pytest.raises(TypeError):
            cache[Point(1, 1)] = 1


@pytest.mark.parametrize(
    'make',
    [
        lambda: dc.SafeDisk.with_signing().with_options(on_error='miss'),
        lambda: dc.SafeDisk.with_options(on_error='miss').with_signing(),
        lambda: dc.SafeDisk.with_types(Pair)
        .with_options(on_error='miss')
        .with_signing(),
        lambda: dc.SafeDisk.with_signing()
        .with_types(Pair)
        .with_options(on_error='miss'),
    ],
)
def test_options_combine_in_any_order(directory, tmp_path, make):
    disk = make()
    assert disk.on_error == 'miss'
    assert isinstance(disk.signing, signing.KeyFile)

    marker = tmp_path / 'marker'
    with dc.Cache(directory, disk=dc.Disk) as cache:
        cache['planted'] = Poison(str(marker))
    with dc.Cache(directory, disk=disk) as cache:
        cache['signed'] = Point(1, 2)
        assert cache['signed'] == Point(1, 2)
        assert cache.get('planted') is None
    assert not marker.exists()

    pickled = pickle.loads(pickle.dumps(disk))
    assert pickled.on_error == 'miss'
    assert isinstance(pickled.signing, signing.KeyFile)


def test_with_signing_again_replaces_the_key():
    first = dc.SafeDisk.with_signing(key=KEY)
    second = first.with_signing(key=OTHER_KEY)
    assert (
        second.signing.key.key_id == signing.InMemoryKey(OTHER_KEY).key.key_id
    )
    assert first.signing.key.key_id == signing.InMemoryKey(KEY).key.key_id


def test_with_numpy_does_not_combine():
    with pytest.raises(TypeError, match='with_numpy'):
        dc.SafeDisk.with_numpy().with_signing()
    with pytest.raises(TypeError, match='with_numpy'):
        dc.SafeDisk.with_signing().with_numpy()


def test_safejsondisk_has_nothing_to_sign():
    with pytest.raises(TypeError, match='SafeJSONDisk'):
        dc.SafeJSONDisk.with_signing()


def test_with_signing_argument_errors(tmp_path):
    with pytest.raises(TypeError, match='not both'):
        dc.SafeDisk.with_signing(tmp_path / 'key', key=KEY)
    with pytest.raises(TypeError, match='bytes'):
        dc.SafeDisk.with_signing(key=KEY.hex())
    with pytest.raises(ValueError, match='at least 32 bytes, not 31'):
        dc.SafeDisk.with_signing(key=KEY[:31])

    disk = dc.SafeDisk.with_signing(op.join('~', 'relative.key'))
    assert op.isabs(disk.signing.path)
    assert dc.SafeDisk.with_signing(b'/bytes.key').signing.path == (
        op.abspath('/bytes.key')
    )


class WithKey(dc.SafeDisk):
    def fetch(self, mode, filename, value, read, key=None):
        return super().fetch(mode, filename, value, read, key=key)


class WithKeywords(dc.SafeDisk):
    def fetch(self, *args, **kwargs):
        return super().fetch(*args, **kwargs)


class WithArguments(dc.SafeDisk):
    def fetch(self, *args):
        return super().fetch(*args)


class WithoutKey(dc.SafeDisk):
    def fetch(self, mode, filename, value, read):
        return super().fetch(mode, filename, value, read)


@pytest.mark.parametrize('disk', [WithKey, WithKeywords])
def test_subclasses_whose_fetch_accepts_key(directory, disk):
    with dc.Cache(directory, disk=disk.with_signing()) as cache:
        cache['key'] = Point(1, 2)
        assert cache['key'] == Point(1, 2)


@pytest.mark.parametrize('disk', [WithArguments, WithoutKey])
def test_subclasses_whose_fetch_refuses_key(disk):
    with pytest.raises(TypeError, match='keyword argument key'):
        disk.with_signing()


def test_subclasses_whose_fetch_cannot_be_inspected(monkeypatch):
    def cannot_inspect(function):
        raise ValueError('no signature')

    monkeypatch.setattr(
        signing, 'inspect', types.SimpleNamespace(signature=cannot_inspect)
    )
    with pytest.raises(TypeError, match='keyword argument key'):
        WithKey.with_signing()
    dc.SafeDisk.with_signing()


# Older readers


@pytest.mark.parametrize('size', [INLINE, FILE], ids=['inline', 'file'])
@pytest.mark.parametrize(
    'disk, message',
    [
        (dc.Disk, 'invalid load key'),
        (dc.SafeDisk, 'signed entry'),
        (dc.SafeDisk.with_types(Pair), 'signed entry'),
    ],
    ids=['Disk', 'SafeDisk', 'with_types'],
)
def test_disks_without_signing_raise_on_signed_rows(
    directory, tmp_path, size, disk, message
):
    marker = tmp_path / 'marker'
    with dc.Cache(directory, disk=Signed, disk_min_file_size=size) as cache:
        cache['key'] = Poison(str(marker))

    with dc.Cache(directory, disk=disk) as cache:
        with pytest.raises(pickle.UnpicklingError, match=message):
            cache['key']
        with pytest.raises(pickle.UnpicklingError):
            cache.get('key', read=True)

    with dc.Cache(directory, disk=disk.with_options(on_error='miss')) as cache:
        assert cache.get('key') is None
        assert len(cache) == 0

    assert not marker.exists()


# Golden version 1 rows: the writer must keep producing them, and later
# releases must keep reading them, byte for byte. They were computed from the
# format's description, not with this code.

GOLDEN_VALUE = {'golden': [1, 2.5, 'three'], 'nested': ('a', b'b')}
GOLDEN_PICKLE = bytes.fromhex(
    '80049538000000000000007d94288c06676f6c64656e945d94284b01474004000000'
    '0000008c05746872656594658c066e6573746564948c016194430162948694752e'
)
GOLDEN_PREFIX = bytes.fromhex(
    'ff44435301d6501f4f9886a1f2529ffd0cb33d012488d809c1f055a2bbc0cac46fca'
    '2125ee85dbe9050b0b8e4c'
)


@pytest.mark.parametrize('size', [INLINE, FILE], ids=['inline', 'file'])
def test_golden_rows_of_version_1(directory, size):
    disk = dc.SafeDisk.with_signing(key=KEY)
    settings = dict(disk_pickle_protocol=4, disk_min_file_size=size)

    with dc.Cache(directory, disk=disk, **settings) as cache:
        cache['golden'] = GOLDEN_VALUE

    _, filename, value = row(directory, 'golden')
    if pickle.dumps(GOLDEN_VALUE, protocol=4) == GOLDEN_PICKLE:
        if size == INLINE:
            assert value == GOLDEN_PREFIX + GOLDEN_PICKLE
        else:
            assert value == GOLDEN_PREFIX
            with open(op.join(directory, filename), 'rb') as reader:
                assert reader.read() == GOLDEN_PICKLE

    if size == INLINE:
        update(directory, 'golden', value=GOLDEN_PREFIX + GOLDEN_PICKLE)
    else:
        with open(op.join(directory, filename), 'wb') as writer:
            writer.write(GOLDEN_PICKLE)
        update(directory, 'golden', value=GOLDEN_PREFIX)

    with dc.Cache(directory, disk=disk) as cache:
        assert cache['golden'] == GOLDEN_VALUE


# The rest of the API


def test_memoize(directory):
    calls = []

    with dc.Cache(directory, disk=Signed) as cache:

        @cache.memoize(typed=True)
        def make(number):
            calls.append(number)
            return Point(number, number)

        assert make(1) == make(1) == Point(1, 1)
        assert make(1.0) == Point(1.0, 1.0)

    assert calls == [1, 1.0]


def test_deque_and_index(tmp_path):
    deque = dc.Deque(directory=str(tmp_path / 'deque'), disk=Signed)
    deque.append(Point(1, 1))
    deque.appendleft(Point(0, 0))
    deque[1] = Point(2, 2)
    assert list(deque) == [Point(0, 0), Point(2, 2)]
    assert deque.pop() == Point(2, 2)

    index = dc.Index(str(tmp_path / 'index'), disk=Signed)
    index['a'] = Point(1, 1)
    index.update(b=Point(2, 2))
    assert dict(index.items()) == {'a': Point(1, 1), 'b': Point(2, 2)}
    assert index.peekitem() == ('b', Point(2, 2))


def test_fanout_cache(tmp_path):
    with dc.FanoutCache(str(tmp_path / 'fanout'), disk=Signed) as cache:
        cache['a'] = Point(1, 1)
        assert cache['a'] == Point(1, 1)

        sub = cache.cache('sub')
        sub['b'] = Point(2, 2)
        assert sub['b'] == Point(2, 2)

        deque = cache.deque('deque')
        deque.append(Point(3, 3))
        assert deque.popleft() == Point(3, 3)

        index = cache.index('index')
        index['c'] = Point(4, 4)
        assert index['c'] == Point(4, 4)


def test_djangocache(tmp_path):
    pytest.importorskip('django')
    from diskcache_community.djangocache import DjangoCache

    cache = DjangoCache(str(tmp_path / 'django'), {'DISK': Signed})
    try:
        cache.set('a', Point(1, 1))
        assert cache.get('a') == Point(1, 1)
    finally:
        cache.close()
