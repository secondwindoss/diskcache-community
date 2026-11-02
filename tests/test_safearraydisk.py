"""Test diskcache_community.SafeArrayDisk."""

import collections as co
import io
import os
import os.path as op
import pickle
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile

import pytest

import diskcache_community as dc
from diskcache_community.arrays import _NPY_KEY
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


def write_row(directory, stored):
    """Store `stored` in the value column of a pickle row."""
    with dc.Cache(directory, disk=dc.SafeDisk) as cache:
        cache['key'] = 'value'
    con = sqlite3.connect(op.join(directory, 'cache.db'))
    con.execute(
        'UPDATE Cache SET mode = ?, value = ?',
        (MODE_PICKLE, sqlite3.Binary(pickle.dumps(stored, protocol=2))),
    )
    con.commit()
    con.close()


def npy(descr, shape, body=b'', version=1):
    header = "{'descr': %s, 'fortran_order': False, 'shape': %s, }" % (
        descr,
        shape,
    )
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


def test_writing_leaves_the_caller_value_alone(directory):
    array = np.arange(3.0)
    value = {'a': array}

    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        cache['key'] = value

    assert value['a'] is array


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


def test_scalar_dict_keys_become_python_values(directory):
    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        cache['key'] = {np.int64(1): 'one'}
        assert cache['key'] == {1: 'one'}
        assert type(next(iter(cache['key']))) is int


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


def test_field_names_that_need_format_3_are_refused(directory):
    array = np.zeros(1, dtype=[('α', 'i4')])

    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        with pytest.raises(TypeError):
            cache['key'] = array


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
        with pytest.raises(TypeError):
            cache['key'] = make()


@pytest.mark.parametrize(
    'make',
    [
        lambda array: Pair(array, 1),
        lambda array: co.OrderedDict(a=array),
        lambda array: co.deque([array]),
    ],
    ids=['namedtuple', 'ordereddict', 'deque'],
)
def test_arrays_in_other_containers_are_refused(directory, make):
    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        with pytest.raises(TypeError):
            cache['key'] = make(np.arange(2.0))


def test_array_key_is_refused(directory):
    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        with pytest.raises(TypeError):
            cache[(np.int64(1),)] = 'value'


def test_reserved_key_is_refused(directory):
    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        with pytest.raises(TypeError):
            cache['key'] = {_NPY_KEY: b'data'}
        with pytest.raises(TypeError):
            cache['key'] = [{'a': {_NPY_KEY: 1, 'other': 2}}]


def test_reserved_key_is_refused_without_numpy(directory):
    code = (
        'import sys\n'
        'import diskcache_community as dc\n'
        'from diskcache_community.arrays import _NPY_KEY\n'
        'assert "numpy" not in sys.modules\n'
        'with dc.Cache(sys.argv[1], disk=dc.SafeArrayDisk) as cache:\n'
        '    cache["plain"] = {"a": [1, 2]}\n'
        '    assert cache["plain"] == {"a": [1, 2]}\n'
        '    try:\n'
        '        cache["key"] = {_NPY_KEY: b"data"}\n'
        '    except TypeError:\n'
        '        pass\n'
        '    else:\n'
        '        raise AssertionError("not refused")\n'
        'assert "numpy" not in sys.modules\n'
    )
    subprocess.run([sys.executable, '-c', code, directory], check=True)


def test_plain_values_behave_as_in_safedisk(directory):
    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        value = {'a': [1, 2.5, 'x', None, (True,)], 'b': {'c': b'data'}}
        cache['key'] = value
        assert cache['key'] == value
        with pytest.raises(TypeError):
            cache['object'] = object()


def test_cyclic_values_still_work(directory):
    value = [1]
    value.append(value)

    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        cache['key'] = value
        result = cache['key']

    assert result[0] == 1
    assert result[1] is result


def test_cycle_with_an_array_is_refused(directory):
    value = [np.arange(2.0)]
    value.append(value)

    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        with pytest.raises(TypeError):
            cache['key'] = value


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


@pytest.mark.parametrize('reader', [dc.Disk, dc.SafeDisk])
def test_another_disk_reads_a_dict(directory, reader):
    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        cache['key'] = np.arange(2.0)

    with dc.Cache(directory, disk=reader) as cache:
        assert list(cache['key']) == [_NPY_KEY]


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
    write_row(directory, Poison(marker))

    with dc.Cache(directory, disk=MissDisk) as cache:
        assert cache.get('key', 'default') == 'default'

    assert not op.exists(marker)


def test_poison_inside_the_array_slot_does_not_run(directory):
    marker = directory + '.executed'
    write_row(directory, {_NPY_KEY: pickle.dumps(Poison(marker))})

    with dc.Cache(directory, disk=MissDisk) as cache:
        assert cache.get('key', 'default') == 'default'

    assert not op.exists(marker)


FORGED = {
    'garbage': b'not an array',
    'empty': b'',
    'pickle': pickle.dumps([1, 2]),
    'zip magic': b'PK\x03\x04' + b'\x00' * 40,
    'npz-like': b'PK\x05\x06' + b'\x00' * 18,
    'str': 'text',
    'int': 1,
    'none': None,
    'list': [1, 2],
    'truncated': npy("'<f8'", '(4,)', b'\x00' * 8),
    'too long': npy("'<f8'", '(1,)', b'\x00' * 16),
    'huge shape': npy("'<f8'", '(%d,)' % 10**15),
    'huge shape v2': npy("'<f8'", '(%d,)' % 10**15, version=2),
    'overflow shape': npy("'<f8'", '(%d, 16)' % 2**62),
    'negative shape': npy("'<f8'", '(-1, -1)', b'\x00' * 8),
    'object': npy("'|O'", '(1,)', pickle.dumps([1])),
    'object field': npy("[('a', '|O')]", '(1,)', b'\x00' * 8),
    'nested object': npy("[('a', [('b', '|O')])]", '(1,)', b'\x00' * 8),
    'subarray object': npy("[('a', '|O', (2,))]", '(1,)', b'\x00' * 16),
    'bad descr': npy("'not a dtype'", '(1,)', b'\x00'),
    'bad header': b'\x93NUMPY\x01\x00\x10\x00' + b'x' * 16,
    'unknown version': b'\x93NUMPY\x09\x00\x10\x00' + b'x' * 16,
    'version 3': b'\x93NUMPY\x03\x00' + npy("'<f8'", '(1,)')[8:],
    'huge header': b'\x93NUMPY\x02\x00' + struct.pack('<I', 2**31),
}


@pytest.mark.parametrize('stored', FORGED.values(), ids=FORGED.keys())
def test_forged_array_is_refused(directory, stored):
    write_row(directory, {_NPY_KEY: stored})

    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        with pytest.raises(Exception) as caught:
            cache['key']

    assert not isinstance(
        caught.value, (MemoryError, RecursionError, SystemError, OSError)
    )


@pytest.mark.parametrize('stored', FORGED.values(), ids=FORGED.keys())
def test_forged_array_is_a_miss(directory, stored):
    write_row(directory, {_NPY_KEY: stored})

    with dc.Cache(directory, disk=MissDisk) as cache:
        assert cache.get('key', 'default') == 'default'
        assert len(cache) == 0
        cache['key'] = np.arange(2.0)
        same(cache['key'], np.arange(2.0))


@pytest.mark.parametrize('name', ['version 3', 'unknown version'])
def test_other_npy_versions_are_refused(directory, name):
    write_row(directory, {_NPY_KEY: FORGED[name]})

    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        with pytest.raises((pickle.UnpicklingError, ValueError)):
            cache['key']


def test_forged_shape_is_refused_by_the_header_check(directory):
    write_row(directory, {_NPY_KEY: FORGED['huge shape']})

    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        with pytest.raises(pickle.UnpicklingError, match='array header'):
            cache['key']


def test_forged_array_nested_in_a_value_is_a_miss(directory):
    write_row(directory, {'a': [{_NPY_KEY: npy("'<f8'", '(%d,)' % 10**15)}]})

    with dc.Cache(directory, disk=MissDisk) as cache:
        assert cache.get('key', 'default') == 'default'


def test_deep_nesting_is_a_miss(directory):
    # Built by hand, because pickling this nesting would itself recurse.
    array = pickle.dumps({_NPY_KEY: npy("'<f8'", '(1,)', b'\x00' * 8)}, 2)
    data = b'\x80\x02' + b'(' * 100000 + array[2:-1] + b'l' * 100000 + b'.'

    with dc.Cache(directory, disk=dc.SafeDisk) as cache:
        cache['key'] = 'value'
    con = sqlite3.connect(op.join(directory, 'cache.db'))
    con.execute(
        'UPDATE Cache SET mode = ?, value = ?',
        (MODE_PICKLE, sqlite3.Binary(data)),
    )
    con.commit()
    con.close()

    with dc.Cache(directory, disk=MissDisk) as cache:
        assert cache.get('key', 'default') == 'default'


def test_array_with_a_wrong_key_count_stays_a_dict(directory):
    value = {_NPY_KEY: b'data', 'other': 1}
    write_row(directory, value)

    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        assert cache['key'] == value


def test_shared_with_a_process_that_has_numpy_unimported(directory):
    with dc.Cache(directory, disk=dc.SafeArrayDisk) as cache:
        cache['key'] = np.arange(2.0)

    code = (
        'import sys\n'
        'import diskcache_community as dc\n'
        'assert "numpy" not in sys.modules\n'
        'with dc.Cache(sys.argv[1], disk=dc.SafeArrayDisk) as cache:\n'
        '    assert cache["key"].tolist() == [0.0, 1.0]\n'
    )
    subprocess.run(
        [sys.executable, '-c', code, directory],
        check=True,
        env=dict(os.environ),
    )
