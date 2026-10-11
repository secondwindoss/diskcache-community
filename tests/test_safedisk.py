"""Test diskcache.SafeDisk."""

import collections as co
import datetime as dt
import decimal
import fractions
import io
import os
import os.path as op
import pickle
import random
import shutil
import sqlite3
import tempfile
import uuid
import zoneinfo

import pytest

import diskcache as dc
from diskcache.core import MODE_BINARY, MODE_PICKLE, SafeUnpickler

pytestmark = pytest.mark.filterwarnings('ignore', category=dc.EmptyDirWarning)


def _execute(path):
    """Marker that a crafted pickle ran code: it creates `path`."""
    with open(path, 'w', encoding='utf-8') as writer:
        writer.write('executed')
    return 'executed'


class Poison:
    """Object whose pickle calls `_execute` when loaded."""

    def __init__(self, path):
        self.path = path

    def __reduce__(self):
        return (_execute, (self.path,))


class Custom:
    """A class outside the allowlist."""

    def __init__(self, value=0):
        self.value = value

    def __eq__(self, other):
        return type(other) is Custom and other.value == self.value

    def __hash__(self):
        return hash(self.value)


class CustomTz(dt.tzinfo):
    """A tzinfo outside the allowlist."""

    def utcoffset(self, _):
        return dt.timedelta(0)


SAFE_VALUES = [
    None,
    True,
    False,
    0,
    -1,
    2**70,
    1.5,
    float('inf'),
    1 + 2j,
    '',
    'text',
    b'',
    b'bytes',
    bytearray(b'bytes'),
    [],
    [1, [2, [3]]],
    (),
    (1, (2, (3,))),
    {},
    {'a': 1, 2: 'b', (3,): [4]},
    set(),
    {1, 2, 3},
    frozenset({1, 2}),
    range(10),
    range(1, 10, 3),
    slice(1, 2, 3),
    co.OrderedDict([('b', 1), ('a', 2)]),
    co.defaultdict(list, {'a': [1]}),
    co.defaultdict(None, {'a': 1}),
    co.deque([1, 2, 3], maxlen=5),
    co.Counter('abracadabra'),
    dt.date(2020, 1, 2),
    dt.datetime(2020, 1, 2, 3, 4, 5, 6),
    dt.datetime(2020, 1, 2, tzinfo=dt.timezone.utc),
    dt.datetime(2020, 1, 2, tzinfo=dt.timezone(dt.timedelta(hours=2))),
    dt.time(3, 4, 5),
    dt.time(3, 4, 5, tzinfo=dt.timezone.utc),
    dt.timedelta(days=1, seconds=2, microseconds=3),
    dt.timezone.utc,
    decimal.Decimal('1.25'),
    decimal.Decimal('-1e100'),
    fractions.Fraction(1, 3),
    uuid.UUID('12345678-1234-5678-1234-567812345678'),
]

HASHABLE_VALUES = [
    value
    for value in SAFE_VALUES
    if isinstance(value, co.abc.Hashable)
    and not isinstance(value, (bytearray, range))
]

UNSAFE_VALUES = [
    Custom(),
    [Custom()],
    {'a': Custom()},
    {Custom(): 1},
    (1, (2, (Custom(),))),
    co.deque([Custom()]),
    co.defaultdict(Custom),
    dt.datetime(2020, 1, 2, tzinfo=CustomTz()),
    dt.time(1, tzinfo=CustomTz()),
    dt.datetime(2020, 1, 2, tzinfo=zoneinfo.ZoneInfo('UTC')),
    type,
    int,
    len,
    Poison,
    object(),
    Exception('boom'),
]


@pytest.fixture
def directory():
    directory = tempfile.mkdtemp(prefix='diskcache-')
    yield directory
    shutil.rmtree(directory, ignore_errors=True)


@pytest.fixture
def cache(directory):
    with dc.Cache(directory, disk=dc.SafeDisk) as cache:
        yield cache


def poison(directory, name):
    """Return (marker path, pickle bytes) for a payload that creates marker."""
    path = op.join(directory, name)
    return path, pickle.dumps(Poison(path))


def test_poisoned_inline_value(directory):
    path, data = poison(directory, 'inline')

    with dc.Cache(directory) as cache:
        cache['key'] = 'value'
        cache._sql(
            'UPDATE Cache SET mode = ?, value = ? WHERE key = ?',
            (MODE_PICKLE, sqlite3.Binary(data), 'key'),
        )
        assert cache['key'] == 'executed'  # The default Disk runs it.
        assert op.exists(path)

    os.remove(path)

    with dc.Cache(directory, disk=dc.SafeDisk) as cache:
        with pytest.raises(pickle.UnpicklingError, match='refuses'):
            cache['key']  # pylint: disable=pointless-statement
        assert not op.exists(path)


def test_poisoned_file_value(directory):
    path, data = poison(directory, 'file')

    with dc.Cache(directory) as cache:
        cache['key'] = 'value'
        filename, full_path = cache.disk.filename()
        os.makedirs(op.dirname(full_path))
        with open(full_path, 'wb') as writer:
            writer.write(data)
        cache._sql(
            'UPDATE Cache SET mode = ?, value = NULL, filename = ?'
            ' WHERE key = ?',
            (MODE_PICKLE, filename, 'key'),
        )
        assert cache['key'] == 'executed'
        assert op.exists(path)

    os.remove(path)

    with dc.Cache(directory, disk=dc.SafeDisk) as cache:
        with pytest.raises(pickle.UnpicklingError, match='refuses'):
            cache['key']  # pylint: disable=pointless-statement
        assert not op.exists(path)


def test_poisoned_key(directory):
    path, data = poison(directory, 'key')

    with dc.Cache(directory) as cache:
        cache['key'] = 'value'
        cache._sql(
            'UPDATE Cache SET key = ?, raw = 0 WHERE key = ?',
            (sqlite3.Binary(data), 'key'),
        )
        assert list(cache) == ['executed']
        assert op.exists(path)

    os.remove(path)

    with dc.Cache(directory, disk=dc.SafeDisk) as cache:
        with pytest.raises(pickle.UnpicklingError, match='refuses'):
            list(cache)
        assert not op.exists(path)


@pytest.mark.parametrize('protocol', [0, 1, 2, 3, 4, 5])
@pytest.mark.parametrize('min_file_size', [0, 2**15])
def test_round_trip(directory, protocol, min_file_size):
    with dc.Cache(
        directory,
        disk=dc.SafeDisk,
        disk_pickle_protocol=protocol,
        disk_min_file_size=min_file_size,
    ) as cache:
        for index, value in enumerate(SAFE_VALUES):
            cache['value-%d' % index] = value
            result = cache['value-%d' % index]
            assert result == value
            assert type(result) is type(value)

        for index, key in enumerate(HASHABLE_VALUES):
            cache[key] = index
            assert cache[key] == index
            assert key in cache

        assert cache.check() == []

    # The directory opens with the default Disk and reads the same values.

    with dc.Cache(directory) as cache:
        for index, value in enumerate(SAFE_VALUES):
            assert cache['value-%d' % index] == value


def test_property_round_trip(cache):
    rng = random.Random(1234)
    scalars = [
        None,
        True,
        7,
        2**65,
        -0.5,
        'word',
        b'raw',
        dt.date(2021, 5, 6),
        dt.timedelta(hours=1),
        decimal.Decimal('3.5'),
        fractions.Fraction(2, 7),
        uuid.UUID(int=42),
    ]

    def build(depth):
        if depth == 0 or rng.random() < 0.3:
            return rng.choice(scalars)
        kind = rng.choice(['list', 'tuple', 'dict', 'set', 'deque'])
        if kind == 'list':
            return [build(depth - 1) for _ in range(rng.randint(0, 4))]
        if kind == 'tuple':
            return tuple(build(depth - 1) for _ in range(rng.randint(0, 4)))
        if kind == 'dict':
            return {
                rng.choice(scalars[1:7]): build(depth - 1)
                for _ in range(rng.randint(0, 4))
            }
        if kind == 'set':
            return {rng.choice(scalars[1:7]) for _ in range(rng.randint(0, 4))}
        return co.deque(build(depth - 1) for _ in range(rng.randint(0, 4)))

    for index in range(200):
        value = build(4)
        cache[index] = value
        assert cache[index] == value


def test_self_referential_value(cache):
    value = [1, 2]
    value.append(value)
    cache['key'] = value
    result = cache['key']
    assert result[:2] == [1, 2]
    assert result[2] is result

    mapping = {}
    mapping['self'] = mapping
    cache['mapping'] = mapping
    result = cache['mapping']
    assert result['self'] is result


@pytest.mark.parametrize('value', UNSAFE_VALUES)
def test_write_rejected(cache, value):
    with pytest.raises(TypeError, match='SafeDisk cannot store value'):
        cache['key'] = value
    assert 'key' not in cache
    assert len(cache) == 0

    with pytest.raises(TypeError, match='SafeDisk cannot store value'):
        cache.add('key', value)

    with pytest.raises(TypeError, match='SafeDisk cannot store value'):
        cache.push(value)

    assert len(cache) == 0


def test_key_rejected(cache):
    with pytest.raises(TypeError, match='SafeDisk cannot store key'):
        cache[Custom()] = 1

    with pytest.raises(TypeError, match='SafeDisk cannot store key'):
        cache[(1, Custom())] = 1

    with pytest.raises(TypeError, match='SafeDisk cannot store key'):
        cache.get(Custom())

    assert len(cache) == 0


def test_typed_memoize_rejected(cache):
    @cache.memoize(typed=True)
    def identity(value):
        return value

    with pytest.raises(TypeError, match='SafeDisk cannot store key'):
        identity(1)

    @cache.memoize()
    def plain(value):
        return value

    assert plain(1) == 1
    assert plain(1) == 1
    assert len(cache) == 1


def test_read_values_untouched(cache):
    cache.set('key', io.BytesIO(b'stream'), read=True)
    assert cache['key'] == b'stream'

    with cache.read('key') as reader:
        assert reader.read() == b'stream'


def test_recipes(cache):
    averager = dc.Averager(cache, 'average')
    averager.add(1.0)
    averager.add(3.0)
    assert averager.get() == 2.0
    assert averager.pop() == 2.0

    with dc.Lock(cache, 'lock'):
        pass

    with dc.RLock(cache, 'rlock'):
        with dc.RLock(cache, 'rlock'):
            pass

    with dc.BoundedSemaphore(cache, 'semaphore', value=2):
        pass

    @dc.throttle(cache, 2, 1)
    def throttled():
        return 1

    assert throttled() == 1

    @dc.barrier(cache, dc.Lock)
    def guarded():
        return 2

    assert guarded() == 2

    @dc.memoize_stampede(cache, expire=10)
    def stampede(value):
        return value * 2

    assert stampede(3) == 6
    assert stampede(3) == 6


def test_safe_unpickler_blocks_globals():
    for target in (os.system, eval, Custom, Poison, zoneinfo.ZoneInfo):
        data = pickle.dumps(target)
        with pytest.raises(pickle.UnpicklingError, match='refuses'):
            SafeUnpickler(io.BytesIO(data)).load()

    data = pickle.dumps(zoneinfo.ZoneInfo('UTC'))
    with pytest.raises(pickle.UnpicklingError, match='builtins.getattr'):
        SafeUnpickler(io.BytesIO(data)).load()

    # Dotted names that would reach attributes of allowed types are refused.
    data = b'\x80\x04\x8c\x08builtins\x8c\x08int.real\x93.'
    with pytest.raises(pickle.UnpicklingError, match='refuses'):
        SafeUnpickler(io.BytesIO(data)).load()


@pytest.mark.parametrize(
    'filename',
    [
        '../escape.val',
        'ab/../../escape.val',
        'ab\\..\\..\\escape.val',
        '/etc/passwd',
        '\\\\server\\share\\escape.val',
    ]
    + (['C:\\escape.val', 'D:relative.val'] if os.name == 'nt' else []),
)
def test_path_confinement(cache, filename):
    disk = cache.disk

    with pytest.raises(ValueError, match='outside the cache directory'):
        disk.fetch(MODE_BINARY, filename, None, False)

    with pytest.raises(ValueError, match='outside the cache directory'):
        disk.fetch(MODE_PICKLE, filename, None, False)

    with pytest.raises(ValueError, match='outside the cache directory'):
        disk.remove(filename)


def test_path_confinement_row(cache, directory):
    outside = tempfile.mkdtemp(prefix='diskcache-outside-')
    try:
        target = op.join(outside, 'secret.val')
        with open(target, 'wb') as writer:
            writer.write(b'secret')
        cache['key'] = 'value'
        relative = op.relpath(target, directory)
        cache._sql(
            'UPDATE Cache SET mode = ?, value = NULL, filename = ?'
            ' WHERE key = ?',
            (MODE_BINARY, relative, 'key'),
        )

        with pytest.raises(ValueError, match='outside the cache directory'):
            cache['key']  # pylint: disable=pointless-statement

        with pytest.raises(ValueError, match='outside the cache directory'):
            del cache['key']

        assert op.exists(target)
    finally:
        shutil.rmtree(outside, ignore_errors=True)


@pytest.mark.skipif(
    not hasattr(os, 'symlink') or os.name == 'nt',
    reason='symlinks need privileges on Windows',
)
def test_path_confinement_symlink(cache, directory):
    outside = tempfile.mkdtemp(prefix='diskcache-outside-')
    try:
        target = op.join(outside, 'secret.val')
        with open(target, 'wb') as writer:
            writer.write(b'secret')
        os.makedirs(op.join(directory, 'ab', 'cd'))
        os.symlink(target, op.join(directory, 'ab', 'cd', 'link.val'))

        with pytest.raises(ValueError, match='outside the cache directory'):
            cache.disk.fetch(MODE_BINARY, 'ab/cd/link.val', None, False)
    finally:
        shutil.rmtree(outside, ignore_errors=True)


def test_file_values_inside_directory(directory):
    with dc.Cache(directory, disk=dc.SafeDisk, disk_min_file_size=0) as cache:
        cache['bytes'] = b'x' * 100
        cache['text'] = 'y' * 100
        cache['pickle'] = [1, 2, 3]
        assert cache['bytes'] == b'x' * 100
        assert cache['text'] == 'y' * 100
        assert cache['pickle'] == [1, 2, 3]
        del cache['bytes']
        assert cache.check() == []


def test_disk_choice_not_persisted(directory):
    with dc.Cache(directory, disk=dc.SafeDisk) as cache:
        cache['key'] = {'a': [1, 2]}
        keys = {key for (key,) in cache._sql('SELECT key FROM Settings')}

    expected = set(dc.DEFAULT_SETTINGS) | {'count', 'size', 'hits', 'misses'}
    assert keys == expected

    with dc.Cache(directory) as cache:
        assert type(cache.disk) is dc.Disk
        assert cache['key'] == {'a': [1, 2]}
        cache['custom'] = Custom(5)

    with dc.Cache(directory, disk=dc.SafeDisk) as cache:
        assert cache['key'] == {'a': [1, 2]}
        with pytest.raises(pickle.UnpicklingError):
            cache['custom']  # pylint: disable=pointless-statement


def test_deque_disk(directory):
    deque = dc.Deque(range(3), directory=directory, disk=dc.SafeDisk)
    assert type(deque.cache.disk) is dc.SafeDisk
    deque.append({'a': (1, 2)})
    assert list(deque) == [0, 1, 2, {'a': (1, 2)}]

    with pytest.raises(TypeError, match='SafeDisk cannot store value'):
        deque.append(Custom())

    with pytest.raises(TypeError, match='SafeDisk cannot store value'):
        deque.appendleft(Custom())

    assert len(deque) == 4

    other = dc.Deque(directory=directory, disk=dc.SafeDisk)
    assert list(other) == [0, 1, 2, {'a': (1, 2)}]

    default = dc.Deque(directory=directory)
    assert type(default.cache.disk) is dc.Disk

    deque.cache.close()
    other.cache.close()
    default.cache.close()


def test_index_disk(directory):
    index = dc.Index(directory, {'a': 1}, disk=dc.SafeDisk, b=2)
    assert type(index.cache.disk) is dc.SafeDisk
    assert dict(index) == {'a': 1, 'b': 2}

    with pytest.raises(TypeError, match='SafeDisk cannot store value'):
        index['c'] = Custom()

    with pytest.raises(TypeError, match='SafeDisk cannot store key'):
        index[Custom()] = 3

    assert len(index) == 2

    temporary = dc.Index(disk=dc.SafeDisk, c=3)
    assert type(temporary.cache.disk) is dc.SafeDisk
    assert temporary['c'] == 3

    default = dc.Index(directory)
    assert type(default.cache.disk) is dc.Disk
    assert default['b'] == 2

    index.cache.close()
    temporary.cache.close()
    default.cache.close()
    shutil.rmtree(temporary.directory, ignore_errors=True)


def test_fanout_disk(directory):
    with dc.FanoutCache(directory, shards=2, disk=dc.SafeDisk) as fanout:
        fanout['key'] = [1, 2]
        assert fanout['key'] == [1, 2]

        with pytest.raises(TypeError, match='SafeDisk cannot store value'):
            fanout['custom'] = Custom()

        sub = fanout.cache('sub')
        assert type(sub.disk) is dc.SafeDisk
        with pytest.raises(TypeError, match='SafeDisk cannot store value'):
            sub['custom'] = Custom()

        deque = fanout.deque('deque')
        assert type(deque.cache.disk) is dc.SafeDisk
        with pytest.raises(TypeError, match='SafeDisk cannot store value'):
            deque.append(Custom())

        index = fanout.index('index')
        assert type(index.cache.disk) is dc.SafeDisk
        with pytest.raises(TypeError, match='SafeDisk cannot store value'):
            index['custom'] = Custom()

        # An explicit disk argument is honoured for every sub-container.
        json_cache = fanout.cache('json', disk=dc.JSONDisk)
        assert type(json_cache.disk) is dc.JSONDisk
        json_cache['key'] = {'a': 1}
        assert json_cache['key'] == {'a': 1}

        plain_deque = fanout.deque('plain', disk=dc.Disk)
        assert type(plain_deque.cache.disk) is dc.Disk
        plain_deque.append(Custom(1))
        assert plain_deque[0] == Custom(1)

        plain_index = fanout.index('plain', disk=dc.Disk)
        assert type(plain_index.cache.disk) is dc.Disk
        plain_index['custom'] = Custom(2)
        assert plain_index['custom'] == Custom(2)

        for container in (sub, json_cache):
            container.close()
        for container in (deque, index, plain_deque, plain_index):
            container.cache.close()


def test_fanout_cache_disk_argument(directory):
    # Regression: FanoutCache.cache(name, disk=...) used to ignore `disk`.
    with dc.FanoutCache(directory, shards=2) as fanout:
        safe = fanout.cache('safe', disk=dc.SafeDisk)
        assert type(safe.disk) is dc.SafeDisk
        inherited = fanout.cache('inherited')
        assert type(inherited.disk) is dc.Disk
        safe.close()
        inherited.close()

