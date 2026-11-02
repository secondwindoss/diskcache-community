"""Test diskcache_community.SafeArrayDisk."""

import collections as co
import dataclasses
import io
import os.path as op
import pickle
import pickletools
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile

import pytest

import diskcache_community as dc
from diskcache_community import arrays
from diskcache_community.core import MODE_PICKLE

np = pytest.importorskip('numpy')

pytestmark = pytest.mark.filterwarnings('ignore', category=dc.EmptyDirWarning)

MissDisk = dc.SafeArrayDisk.with_options(on_error='miss')


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


class Outside:
    """A class outside the allowlist."""


class Temporaries:
    """Object that hands pickle arrays nothing else refers to."""

    def __init__(self, count):
        self.count = count

    def __reduce__(self):
        arrays = (np.arange(n, n + 2.0) for n in range(self.count))
        return (list, (), None, arrays)


class State:
    """A plain class holding arrays, as a library's state object does."""

    def __init__(self, tokens, scores):
        self.tokens = tokens
        self.scores = scores


@dataclasses.dataclass
class Result:
    name: str
    vector: object


Pair = co.namedtuple('Pair', 'left right')


@pytest.fixture
def directory():
    directory = tempfile.mkdtemp(prefix='diskcache-')
    yield directory
    shutil.rmtree(directory, ignore_errors=True)


def same(actual, expected):
    assert type(actual) is np.ndarray
    assert actual.dtype == expected.dtype
    assert actual.shape == expected.shape
    assert actual.tobytes() == expected.tobytes()


def npy_bytes(array):
    buffer = io.BytesIO()
    np.save(buffer, array, allow_pickle=False)
    return buffer.getvalue()


def persid(pid):
    """Return a pickle of one persistent ID, without using the code tested."""
    return pickle.dumps(pid, protocol=3)[:-1] + pickle.BINPERSID + pickle.STOP


def write_row(directory, data):
    """Store the pickle `data` in the value column of a row."""
    with dc.Cache(directory, disk=dc.SafeDisk) as cache:
        cache['key'] = 'value'
    con = sqlite3.connect(op.join(directory, 'cache.db'))
    con.execute(
        'UPDATE Cache SET mode = ?, value = ?',
        (MODE_PICKLE, sqlite3.Binary(data)),
    )
    con.commit()
    con.close()


def row_bytes(cache, key):
    return bytes(
        cache._sql('SELECT value FROM Cache WHERE key = ?', (key,)).fetchone()[
            0
        ]
    )


def npy(descr, shape, body=b'', version=1):
    header = "{'descr': %s, 'fortran_order': False, 'shape': %s, }" % (
        descr,
        shape,
    )
    return npy_header(header, body, version)


def npy_header(header, body=b'', version=1):
    header = header.encode('latin1')
    size = '<H' if version == 1 else '<I'
    prefix = 10 if version == 1 else 12
    header += b' ' * (64 - (prefix + len(header) + 1) % 64) + b'\n'
    magic = b'\x93NUMPY' + bytes([version, 0])
    return magic + struct.pack(size, len(header)) + header + body


@pytest.mark.parametrize(
    'array',
    [
        np.arange(6.0),
        np.arange(24, dtype=np.int8).reshape(2, 3, 4),
        np.array([True, False]),
        np.array([1 + 2j], dtype=np.complex64),
        np.array(['a', 'bcd']),
        np.array([b'a', b'bcd']),
        np.array([(1, 2.0)], dtype=[('a', 'i4'), ('b', 'f8')]),
        np.array(3.5),
        np.zeros((0, 3)),
        np.arange(4.0).reshape(2, 2).T,
        np.arange(3, dtype='>i4'),
    ],
    ids=lambda array: '%s-%s' % (array.dtype, array.shape),
)
def test_array_round_trip(directory, array):
    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        cache['key'] = array
        same(cache['key'], array)


def test_arrays_in_containers(directory):
    array = np.arange(3.0)
    value = {'a': array, 'b': [array, (array, 1)], 'c': 'text'}

    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        cache['key'] = value
        result = cache['key']

    same(result['a'], array)
    assert type(result['b']) is list
    same(result['b'][0], array)
    assert type(result['b'][1]) is tuple
    same(result['b'][1][0], array)
    assert result['b'][1][1] == 1
    assert result['c'] == 'text'


@pytest.mark.parametrize(
    'make',
    [
        lambda array: co.OrderedDict(a=array),
        lambda array: co.deque([array]),
        lambda array: co.defaultdict(list, a=array),
    ],
    ids=['ordereddict', 'deque', 'defaultdict'],
)
def test_arrays_in_the_other_safe_containers(directory, make):
    array = np.arange(2.0)
    value = make(array)

    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        cache['key'] = value
        result = cache['key']

    assert type(result) is type(value)
    item = result[0] if isinstance(result, co.deque) else result['a']
    same(item, array)


def test_arrays_in_allowed_classes(directory):
    array = np.arange(3.0)
    disk = dc.SafeArrayDisk.with_types(Result, Pair, State)

    with dc.Cache(directory, disk=disk) as cache:
        cache['dataclass'] = Result('name', array)
        cache['namedtuple'] = Pair(array, 1)
        cache['object'] = State(array, {'scores': array})
        same(cache['dataclass'].vector, array)
        same(cache['namedtuple'].left, array)
        same(cache['object'].tokens, array)
        same(cache['object'].scores['scores'], array)


def test_arrays_in_classes_outside_the_allowlist_are_refused(directory):
    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        with pytest.raises(TypeError):
            cache['key'] = Result('name', np.arange(2.0))
        with pytest.raises(TypeError):
            cache['key'] = {'a': np.arange(2.0), 'b': Outside()}


def test_writing_leaves_the_caller_value_alone(directory):
    array = np.arange(3.0)
    value = {'a': array}

    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        cache['key'] = value

    assert value['a'] is array


def test_shared_arrays_stay_shared_and_are_stored_once(directory):
    array = np.arange(1000.0)

    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        cache['one'] = [array]
        cache['many'] = [array] * 100
        result = cache['many']
        extra = len(row_bytes(cache, 'many')) - len(row_bytes(cache, 'one'))

    assert all(item is result[0] for item in result)
    assert extra < 1000


def test_temporary_arrays_keep_their_own_data(directory):
    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        cache['key'] = Temporaries(50)
        result = cache['key']

    assert [item.tolist() for item in result] == [
        [n, n + 1.0] for n in range(50)
    ]


def test_cycles_work(directory):
    array = np.arange(2.0)
    value = [array]
    value.append(value)

    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        cache['key'] = value
        result = cache['key']

    same(result[0], array)
    assert result[1] is result


def test_shared_structure_stays_linear(directory):
    """Walking this nesting without a memo would take 2**64 steps."""
    value = [np.arange(2.0)]
    for _ in range(64):
        value = [value, value]

    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        cache['key'] = value
        result = cache['key']

    assert result[0] is result[1]


@pytest.mark.parametrize('protocol', [0, 1, 2, 3, 4, 5])
def test_every_pickle_protocol_setting(directory, protocol):
    if protocol > pickle.HIGHEST_PROTOCOL:
        pytest.skip('protocol not available')

    with dc.Cache(
        directory, disk=dc.SafeArrayDisk, disk_pickle_protocol=protocol
    ) as cache:
        cache['key'] = {'a': np.arange(2.0), 'b': np.int64(1)}
        same(cache['key']['a'], np.arange(2.0))
        assert cache['key']['b'] == 1


@pytest.mark.parametrize(
    ('scalar', 'expected'),
    [
        (np.float64(1.5), 1.5),
        (np.float32(1.5), 1.5),
        (np.int64(2), 2),
        (np.uint8(2), 2),
        (np.bool_(True), True),
        (np.complex128(1j), 1j),
        (np.str_('text'), 'text'),
        (np.bytes_(b'data'), b'data'),
    ],
    ids=lambda value: type(value).__name__,
)
def test_scalars_become_python_values(directory, scalar, expected):
    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        cache['key'] = scalar
        cache['nested'] = {'metrics': [scalar]}
        assert cache['key'] == expected
        assert type(cache['key']) is type(expected)
        assert type(cache['nested']['metrics'][0]) is type(expected)


def test_a_top_level_integer_scalar_is_a_plain_row(directory):
    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        cache['key'] = np.int64(2)
        assert cache.incr('key') == 3


@pytest.mark.parametrize('kind', [np.float64, np.float32, np.float16])
def test_nan_scalar_is_not_lost(directory, kind):
    """A raw float NaN would come back as None, because SQLite stores NULL."""
    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        cache['key'] = kind('nan')
        cache['inf'] = kind('inf')
        result = cache['key']
        assert type(result) is float
        assert result != result
        assert cache['inf'] == float('inf')


def test_scalar_dict_keys_become_python_values(directory):
    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        cache['key'] = {np.int64(1): 'one'}
        assert cache['key'] == {1: 'one'}
        assert type(next(iter(cache['key']))) is int


@pytest.mark.parametrize(
    'make',
    [
        lambda scalar: {scalar},
        lambda scalar: frozenset([scalar]),
        lambda scalar: co.deque([scalar]),
        lambda scalar: co.OrderedDict(a=scalar),
        lambda scalar: co.Counter({'a': scalar}),
        lambda scalar: co.defaultdict(int, a=scalar),
    ],
    ids=['set', 'frozenset', 'deque', 'ordereddict', 'counter', 'defaultdict'],
)
def test_scalars_in_the_other_safe_containers(directory, make):
    value = make(np.int64(2))

    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        cache['key'] = value
        result = cache['key']

    assert type(result) is type(value)
    item = next(iter(result.values() if hasattr(result, 'values') else result))
    assert item == 2
    assert type(item) is int


@pytest.mark.parametrize(
    'scalar',
    [
        np.datetime64('2026-01-01T00:00:00.000000000'),
        np.timedelta64(5, 'ns'),
    ],
    ids=lambda value: type(value).__name__,
)
def test_time_scalars_are_refused(directory, scalar):
    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        with pytest.raises(TypeError):
            cache['key'] = scalar
        with pytest.raises(TypeError):
            cache['key'] = [scalar]


def test_long_double_reads_back_or_is_refused(directory):
    value = np.longdouble(1.5)

    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        try:
            cache['key'] = {'a': value}
        except TypeError:
            return
        assert cache['key'] == {'a': 1.5}


@pytest.mark.parametrize(
    'array',
    [
        np.array([object()], dtype=object),
        np.array([(1, None)], dtype=[('a', 'i4'), ('b', 'O')]),
        np.zeros(1, dtype=[('a', 'O', (2,))]),
    ],
    ids=['object', 'field', 'subarray'],
)
def test_object_arrays_are_refused(directory, array):
    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        with pytest.raises(TypeError):
            cache['key'] = array
        assert len(cache) == 0


@pytest.mark.parametrize(
    'array',
    [
        np.zeros(1, dtype=[('α', 'i4')]),
        np.zeros(1, dtype=[('f%d' % number, 'i4') for number in range(900)]),
        np.zeros(3, dtype=[]),
        np.zeros(
            2,
            dtype={
                'names': ['a', 'b'],
                'formats': ['i4', 'i2'],
                'offsets': [0, 2],
            },
        ),
    ],
    ids=['format-3', 'long-header', 'zero-width', 'overlapping-fields'],
)
def test_arrays_the_reader_would_refuse_fail_at_write(directory, array):
    with dc.Cache(directory, disk=MissDisk) as cache:
        with pytest.raises(TypeError):
            cache['key'] = array
        assert len(cache) == 0


@pytest.mark.parametrize(
    'make',
    [
        lambda: np.matrix([1, 2]),
        lambda: np.ma.masked_array([1, 2], mask=[1, 0]),
        lambda: np.array([1.0]).view(np.recarray),
    ],
    ids=['matrix', 'masked', 'recarray'],
)
def test_subclasses_are_refused(directory, make):
    """numpy.save would silently drop what makes them a subclass."""
    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        with pytest.raises(TypeError, match='subclass'):
            cache['key'] = make()
        with pytest.raises(TypeError, match='subclass'):
            cache['key'] = [make()]


def test_numpy_in_a_key_is_refused(directory):
    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        with pytest.raises(TypeError):
            cache[(np.int64(1),)] = 'value'
        with pytest.raises(TypeError):
            cache[(np.arange(2.0).tobytes(), np.arange(2.0))] = 'value'


def test_memoize(directory):
    calls = []

    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:

        @cache.memoize()
        def compute(size):
            calls.append(size)
            return np.arange(float(size))

        same(compute(3), np.arange(3.0))
        same(compute(3), np.arange(3.0))

    assert calls == [3]


def test_memoize_scalar_is_numpy_on_a_miss_and_python_on_a_hit(directory):
    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:

        @cache.memoize()
        def compute():
            return np.int64(3)

        assert type(compute()) is np.int64
        assert type(compute()) is int


def test_memoize_scalar_argument_is_refused(directory):
    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:

        @cache.memoize()
        def compute(value):
            return value

        with pytest.raises(TypeError):
            compute(np.int64(3))


def test_plain_values_behave_as_in_safedisk(directory):
    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        value = {'a': [1, 2.5, 'x', None, (True,)], 'b': {'c': b'data'}}
        cache['key'] = value
        assert cache['key'] == value
        with pytest.raises(TypeError):
            cache['outside'] = Outside()
        with pytest.raises(TypeError):
            cache['function'] = lambda: None


def test_plain_values_are_ordinary_pickles(directory):
    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        cache['key'] = {'a': [1, 2]}
        names = {
            op.name for op, _, _ in pickletools.genops(row_bytes(cache, 'key'))
        }

    assert 'BINPERSID' not in names

    with dc.Cache(directory, disk=dc.Disk) as cache:
        assert cache['key'] == {'a': [1, 2]}


def test_plain_values_skip_the_array_pickler(directory, monkeypatch):
    """Otherwise every object in them costs a call into Python."""

    def refuse(*args):
        raise AssertionError('plain value reached the array pickler')

    monkeypatch.setattr(arrays, '_ArrayPickler', refuse)

    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        cache['key'] = {'a': [1, 2.5, 'x']}
        assert cache['key'] == {'a': [1, 2.5, 'x']}


def test_plain_values_do_not_import_numpy(directory):
    code = (
        'import sys\n'
        'import diskcache_community as dc\n'
        'assert "numpy" not in sys.modules\n'
        'with dc.Cache(sys.argv[1], disk=dc.SafeArrayDisk) as cache:\n'
        '    cache["plain"] = {"a": [1, 2]}\n'
        '    assert cache["plain"] == {"a": [1, 2]}\n'
        'assert "numpy" not in sys.modules\n'
    )
    subprocess.run([sys.executable, '-c', code, directory], check=True)


def test_reads_an_array_in_a_process_that_has_not_imported_numpy(directory):
    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        cache['key'] = np.arange(2.0)

    code = (
        'import sys\n'
        'import diskcache_community as dc\n'
        'assert "numpy" not in sys.modules\n'
        'with dc.Cache(sys.argv[1], disk=dc.SafeArrayDisk) as cache:\n'
        '    assert cache["key"].tolist() == [0.0, 1.0]\n'
    )
    subprocess.run([sys.executable, '-c', code, directory], check=True)


def test_without_numpy_an_entry_raises_and_is_kept(directory):
    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        cache['key'] = np.arange(2.0)

    code = (
        'import sys\n'
        'sys.modules["numpy"] = None\n'
        'import diskcache_community as dc\n'
        'disk = dc.SafeArrayDisk.with_options(on_error="miss")\n'
        'with dc.Cache(sys.argv[1], disk=disk) as cache:\n'
        '    try:\n'
        '        cache.get("key")\n'
        '    except ImportError as error:\n'
        '        assert "numpy" in str(error)\n'
        '    else:\n'
        '        raise AssertionError("no ImportError")\n'
        '    cache.expire()\n'
        '    assert len(cache) == 1\n'
    )
    subprocess.run([sys.executable, '-c', code, directory], check=True)

    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        same(cache['key'], np.arange(2.0))


def test_missing_numpy_is_not_an_unreadable_entry(directory, monkeypatch):
    with dc.Cache(directory, disk=MissDisk) as cache:
        cache['key'] = np.arange(2.0)
        monkeypatch.setitem(sys.modules, 'numpy', None)
        with pytest.raises(ImportError, match='needs numpy'):
            cache.get('key')
        monkeypatch.undo()
        same(cache['key'], np.arange(2.0))


def test_real_memory_shortage_keeps_the_entry(directory, monkeypatch):
    def fail(*args, **kwargs):
        raise MemoryError

    with dc.Cache(directory, disk=MissDisk) as cache:
        cache['key'] = np.arange(2.0)
        monkeypatch.setattr(np.lib.format, 'read_array', fail)
        with pytest.raises(MemoryError):
            cache.get('key')
        monkeypatch.undo()
        same(cache['key'], np.arange(2.0))


def test_read_true_still_returns_a_file(directory):
    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        cache.set('key', io.BytesIO(b'raw'), read=True)
        with cache.get('key', read=True) as reader:
            assert reader.read() == b'raw'


def test_large_array_lives_in_a_file(directory):
    array = np.arange(100000.0)

    with dc.Cache(
        directory, disk=dc.SafeArrayDisk, disk_min_file_size=0
    ) as cache:
        cache['key'] = array
        same(cache['key'], array)
        assert cache.check() == []


def test_fanout_index_and_deque(directory):
    array = np.arange(3.0)

    with dc.FanoutCache(
        op.join(directory, 'fanout'), disk=dc.SafeArrayDisk
    ) as cache:
        cache['key'] = array
        same(cache['key'], array)

    index = dc.Index(op.join(directory, 'index'), disk=dc.SafeArrayDisk)
    index['key'] = array
    same(index['key'], array)
    index.cache.close()

    deque = dc.Deque(
        directory=op.join(directory, 'deque'), disk=dc.SafeArrayDisk
    )
    deque.append(array)
    same(deque.pop(), array)
    deque.cache.close()


def test_with_types_and_options_combine(directory):
    disk = dc.SafeArrayDisk.with_types(Pair).with_options(on_error='miss')

    with dc.Cache(directory, disk=disk) as cache:
        cache['pair'] = Pair(1, 2)
        cache['array'] = np.arange(2.0)
        assert cache['pair'] == Pair(1, 2)
        same(cache['array'], np.arange(2.0))
        copy = pickle.loads(pickle.dumps(cache))
        assert isinstance(copy.disk, dc.SafeArrayDisk)
        assert copy.disk.on_error == 'miss'
        copy.close()


def test_with_types_still_refuses_numpy():
    with pytest.raises(ValueError):
        dc.SafeArrayDisk.with_types(np.ndarray)


def test_row_format_is_pinned(directory):
    """Changing what is on disk breaks every cache: this is hand-built."""
    array = np.arange(3.0)
    write_row(directory, persid(('npy', npy_bytes(array))))

    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        same(cache['key'], array)

    other = op.join(directory, 'other')
    write_row(other, persid(('item', 1.5)))

    with dc.Cache(other, disk=dc.SafeArrayDisk) as cache:
        assert cache['key'] == 1.5


def test_stored_row_uses_the_pinned_format(directory):
    array = np.arange(3.0)

    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        cache['array'] = array
        cache['scalar'] = [np.int64(1)]
        rows = row_bytes(cache, 'array'), row_bytes(cache, 'scalar')

    ops = [(op.name, arg) for op, arg, _ in pickletools.genops(rows[0])]
    assert ('BINPERSID', None) in ops
    assert any(arg == 'npy' for _, arg in ops)
    assert any(arg == npy_bytes(array) for _, arg in ops)
    assert any(arg == 'item' for _, arg, _ in pickletools.genops(rows[1]))


@pytest.mark.parametrize('reader', [dc.Disk, dc.SafeDisk])
def test_another_disk_refuses_an_array_entry(directory, reader):
    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        cache['array'] = np.arange(2.0)
        cache['plain'] = {'a': 1}

    with dc.Cache(directory, disk=reader) as cache:
        assert cache['plain'] == {'a': 1}
        with pytest.raises(pickle.UnpicklingError):
            cache['array']


def test_another_disk_with_miss_deletes_an_array_entry(directory):
    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        cache['array'] = np.arange(2.0)

    disk = dc.SafeDisk.with_options(on_error='miss')

    with dc.Cache(directory, disk=disk) as cache:
        assert cache.get('array', 'default') == 'default'
        assert len(cache) == 0


def test_reads_safedisk_entries(directory):
    with dc.Cache(directory, disk=dc.SafeDisk) as cache:
        cache['key'] = {'a': [1, 2]}

    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        assert cache['key'] == {'a': [1, 2]}


def test_array_pickled_by_disk_is_refused(directory):
    with dc.Cache(directory, disk=dc.Disk) as cache:
        cache['key'] = np.arange(2.0)

    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        with pytest.raises(pickle.UnpicklingError):
            cache['key']

    with dc.Cache(directory, disk=MissDisk) as cache:
        assert cache.get('key', 'default') == 'default'


def test_poison_does_not_run(directory):
    marker = directory + '.executed'
    write_row(directory, pickle.dumps(Poison(marker), protocol=2))

    with dc.Cache(directory, disk=MissDisk) as cache:
        assert cache.get('key', 'default') == 'default'

    assert not op.exists(marker)


def test_poison_inside_a_persistent_id_does_not_run(directory):
    marker = directory + '.executed'
    write_row(directory, persid(('item', Poison(marker))))

    with dc.Cache(directory, disk=MissDisk) as cache:
        assert cache.get('key', 'default') == 'default'

    assert not op.exists(marker)


def test_pickle_in_the_array_slot_does_not_run(directory):
    marker = directory + '.executed'
    write_row(directory, persid(('npy', pickle.dumps(Poison(marker)))))

    with dc.Cache(directory, disk=MissDisk) as cache:
        assert cache.get('key', 'default') == 'default'

    assert not op.exists(marker)


FORGED = {
    'garbage': b'not an array',
    'empty': b'',
    'pickle': pickle.dumps([1, 2]),
    'zip magic': b'PK\x03\x04' + b'\x00' * 40,
    'npz-like': b'PK\x05\x06' + b'\x00' * 18,
    'truncated': npy("'<f8'", '(4,)', b'\x00' * 8),
    'too long': npy("'<f8'", '(1,)', b'\x00' * 16),
    'huge shape': npy("'<f8'", '(%d,)' % 10**15),
    'huge shape v2': npy("'<f8'", '(%d,)' % 10**15, version=2),
    'overflow shape': npy("'<f8'", '(%d, 16)' % 2**62),
    'negative shape': npy("'<f8'", '(-1, -1)', b'\x00' * 8),
    'object': npy("'|O'", '(1,)', b'\x00' * 8),
    'object field': npy("[('a', '|O')]", '(1,)', b'\x00' * 8),
    'nested object': npy("[('a', [('b', '|O')])]", '(1,)', b'\x00' * 8),
    'subarray object': npy("[('a', '|O', (2,))]", '(1,)', b'\x00' * 16),
    'bad descr': npy("'not a dtype'", '(1,)', b'\x00'),
    'bad header': b'\x93NUMPY\x01\x00\x10\x00' + b'x' * 16,
    'bad header type': npy_header('[1, 2, 3]'),
    'non-ascii header': b'\x93NUMPY\x01\x00\x04\x00\xff\xfe\xfd\n',
    'unknown version': b'\x93NUMPY\x09\x00\x10\x00' + b'x' * 16,
    'version 3': b'\x93NUMPY\x03\x00' + npy("'<f8'", '(1,)')[8:],
    'huge header size': b'\x93NUMPY\x02\x00' + struct.pack('<I', 2**31),
    'parser bomb': npy_header('~' * 9000),
    'deep brackets': npy_header('[' * 9000),
    'zero width void': npy("'|V0'", '(%d,)' % 10**15),
    'zero width bytes': npy("'|S0'", '(%d,)' % 10**15),
    'zero width text': npy("'<U0'", '(%d,)' % 10**15),
    'zero width struct': npy('[]', '(%d,)' % 10**15),
}


@pytest.mark.parametrize('data', FORGED.values(), ids=FORGED.keys())
def test_forged_array_is_refused(directory, data):
    write_row(directory, persid(('npy', data)))

    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        with pytest.raises(pickle.UnpicklingError):
            cache['key']


@pytest.mark.parametrize('data', FORGED.values(), ids=FORGED.keys())
def test_forged_array_is_a_miss(directory, data):
    write_row(directory, persid(('npy', data)))

    with dc.Cache(directory, disk=MissDisk) as cache:
        assert cache.get('key', 'default') == 'default'
        assert len(cache) == 0
        cache['key'] = np.arange(2.0)
        same(cache['key'], np.arange(2.0))


FORGED_IDS = {
    'bytes': b'data',
    'none': None,
    'list': ['npy', b'data'],
    'one item': ('npy',),
    'three items': ('npy', b'data', 1),
    'unknown kind': ('other', b'data'),
    'kind not a string': (1, b'data'),
    'array of str': ('npy', 'text'),
    'array of int': ('npy', 1),
    'array of none': ('npy', None),
    'array of list': ('npy', [1, 2]),
    'array of bytearray': ('npy', bytearray(b'data')),
}


@pytest.mark.parametrize('pid', FORGED_IDS.values(), ids=FORGED_IDS.keys())
def test_forged_persistent_id_is_refused(directory, pid):
    write_row(directory, persid(pid))

    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        with pytest.raises(pickle.UnpicklingError):
            cache['key']

    with dc.Cache(directory, disk=MissDisk) as cache:
        assert cache.get('key', 'default') == 'default'
        assert len(cache) == 0


@pytest.mark.parametrize(
    'pid',
    [('npy', npy_bytes(np.arange(2.0))), ('item', 1)],
    ids=['array', 'item'],
)
def test_persistent_id_in_a_key_row_is_refused(directory, pid):
    with dc.Cache(directory, disk=dc.SafeDisk) as cache:
        cache[('key',)] = 'value'
    con = sqlite3.connect(op.join(directory, 'cache.db'))
    con.execute(
        'UPDATE Cache SET key = ? WHERE raw = 0',
        (sqlite3.Binary(persid(pid)),),
    )
    con.commit()
    con.close()

    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        with pytest.raises(pickle.UnpicklingError):
            list(cache)

    with dc.Cache(directory, disk=MissDisk) as cache:
        assert list(cache) == []


def test_keys_still_read_back(directory):
    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        cache[('a', 1)] = np.arange(2.0)
        cache['text'] = np.arange(2.0)
        assert list(cache) == [('a', 1), 'text']


def test_forged_array_nested_in_a_value_is_a_miss(directory):
    inner = persid(('npy', FORGED['huge shape']))
    write_row(directory, b'\x80\x03]' + inner[2:-1] + b'a.')

    with dc.Cache(directory, disk=MissDisk) as cache:
        assert cache.get('key', 'default') == 'default'


def test_one_array_referenced_many_times_decodes_once(directory):
    """A row cannot decode to more than the data it holds."""
    array = np.zeros(1000)
    pid = pickle.dumps(('npy', npy_bytes(array)), protocol=3)[2:-1]
    data = b'\x80\x03]q\x00(' + pid + b'q\x01Q'
    data += b'h\x01Q' * 1000 + b'e.'
    write_row(directory, data)

    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        result = cache['key']

    assert len(result) == 1001
    assert all(item is result[0] for item in result)


def test_one_buffer_in_many_ids_decodes_once(directory):
    array = np.zeros(1000)
    data = b'\x80\x03]q\x00(\x8c\x03npyq\x01'
    data += pickle.dumps(npy_bytes(array), protocol=3)[2:-1] + b'q\x02\x86Q'
    data += b'h\x01h\x02\x86Q' * 1000 + b'e.'
    write_row(directory, data)

    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        result = cache['key']

    assert len(result) == 1001
    assert all(item is result[0] for item in result)


def test_deep_nesting_reads_without_recursing(directory):
    # Built by hand, because pickling this nesting would itself recurse.
    array = persid(('npy', npy_bytes(np.zeros(1))))
    data = b'\x80\x03' + b']' * 100000 + array[2:-1] + b'a' * 100000 + b'.'
    write_row(directory, data)

    with dc.Cache(directory, disk=MissDisk) as cache:
        result = cache.get('key', 'default')

    assert type(result) is list
