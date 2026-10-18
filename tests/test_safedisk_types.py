"""Test diskcache_community.SafeDisk.with_types."""

import copyreg
import io
import os.path as op
import pickle
import pickletools
import shutil
import sqlite3
import sys
import tempfile

import pytest

import diskcache_community as dc
from diskcache_community.core import (
    MODE_PICKLE,
    SafeUnpickler,
    _pickle_globals,
)
from tests.safedisk_models import models
from tests.safedisk_models.other import Foreign

pytestmark = pytest.mark.filterwarnings('ignore', category=dc.EmptyDirWarning)

MODULE = 'tests.safedisk_models'


class AppDisk(dc.SafeDisk.with_types(models.Point)):
    """A disk class defined in a module on top of a derived class."""

    marker = 'app'


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


def stack_global(module, name, *args):
    """Return a protocol 4 pickle that looks up module.name and calls it."""

    def string(text):
        data = text.encode('utf-8')
        return b'\x8c' + bytes([len(data)]) + data

    if not args:
        return b'\x80\x04' + string(module) + string(name) + b'\x93.'
    call = string(module) + string(name) + b'\x93' + string(args[0])
    return b'\x80\x04' + call + b'\x85R.'


@pytest.fixture
def directory():
    directory = tempfile.mkdtemp(prefix='diskcache-')
    yield directory
    shutil.rmtree(directory, ignore_errors=True)


def test_with_types_derives_a_safedisk():
    disk = dc.SafeDisk.with_types(models.Point)

    assert issubclass(disk, dc.SafeDisk)
    assert disk is not dc.SafeDisk
    assert disk.__name__ == 'SafeDisk'
    assert disk.safe_types == frozenset({models.Point})
    assert disk.safe_modules == ()
    assert 'safe_types' in repr(disk)
    assert dc.SafeDisk.safe_types == frozenset()


def test_with_types_adds_to_a_derived_class():
    first = dc.SafeDisk.with_types(models.Point, modules='a.b')
    second = first.with_types(models.Pair, modules=['a.b', 'c'])

    assert second.safe_types == frozenset({models.Point, models.Pair})
    assert second.safe_modules == ('a.b', 'c')
    assert second.__bases__ == (dc.SafeDisk,)
    assert first.safe_types == frozenset({models.Point})


def test_with_types_on_a_subclass_keeps_the_subclass():
    class LoggingDisk(dc.SafeDisk):
        pass

    disk = LoggingDisk.with_types(models.Point)

    assert issubclass(disk, LoggingDisk)
    assert disk.__bases__ == (LoggingDisk,)


@pytest.mark.parametrize('entry', [1, 'models.Point', models.Point(1, 2)])
def test_with_types_rejects_non_classes(entry):
    with pytest.raises(TypeError, match='with_types takes classes'):
        dc.SafeDisk.with_types(entry)


@pytest.mark.parametrize('entry', ['', '.', 'a..b', '1abc', 'a.b-c', None])
def test_with_types_rejects_bad_module_names(entry):
    with pytest.raises(ValueError, match='not a module name'):
        dc.SafeDisk.with_types(modules=[entry])


def test_module_prefix_drops_a_trailing_dot():
    disk = dc.SafeDisk.with_types(modules='litellm.types.')
    assert disk.safe_modules == ('litellm.types',)


@pytest.mark.parametrize('protocol', [0, 1, 2, 3, 4, 5])
@pytest.mark.parametrize('min_file_size', [0, 2**15])
def test_exact_types_round_trip(directory, protocol, min_file_size):
    disk = dc.SafeDisk.with_types(
        models.Point, models.Shape, models.Pair, models.Color
    )
    values = [
        models.Point(1, 2),
        models.Shape('square', [models.Point(0, 0), models.Point(1, 1)]),
        models.Pair('left', [1, 2]),
        models.Color.GREEN,
        {'points': [models.Point(3, 4)], 'color': models.Color.RED},
    ]

    with dc.Cache(
        directory,
        disk=disk,
        disk_pickle_protocol=protocol,
        disk_min_file_size=min_file_size,
    ) as cache:
        for number, value in enumerate(values):
            cache[number] = value
            assert cache[number] == value
        cache[models.Pair(1, 2)] = 'pair key'
        assert cache[models.Pair(1, 2)] == 'pair key'

    with dc.Cache(directory) as cache:
        assert cache[0] == values[0]


def test_nested_class(directory):
    disk = dc.SafeDisk.with_types(models.Outer.Inner)

    with dc.Cache(directory, disk=disk) as cache:
        cache['inner'] = models.Outer.Inner(5)
        assert cache['inner'] == models.Outer.Inner(5)


def test_exact_types_refuse_others_at_write(directory):
    disk = dc.SafeDisk.with_types(models.Point)

    with dc.Cache(directory, disk=disk) as cache:
        with pytest.raises(TypeError, match='with_types'):
            cache['shape'] = models.Shape('line', [])
        with pytest.raises(TypeError, match='PointSubclass'):
            cache['subclass'] = models.PointSubclass(1, 2)
        with pytest.raises(TypeError, match='Foreign'):
            cache['nested'] = [models.Point(1, 2), Foreign('x')]
        with pytest.raises(TypeError, match='key'):
            cache[models.Shape('key', [])] = 1
        assert len(cache) == 0


def test_exact_types_refuse_others_at_read(directory):
    with dc.Cache(directory) as cache:
        cache['shape'] = models.Shape('line', [])
        cache['point'] = models.Point(1, 2)

    disk = dc.SafeDisk.with_types(models.Point)

    with dc.Cache(directory, disk=disk) as cache:
        assert cache['point'] == models.Point(1, 2)
        with pytest.raises(pickle.UnpicklingError, match='Shape'):
            cache['shape']  # pylint: disable=pointless-statement


def test_poisoned_value_still_refused(directory):
    path = op.join(directory, 'marker')
    disk = dc.SafeDisk.with_types(models.Point, modules=MODULE)

    with dc.Cache(directory, disk=disk) as cache:
        cache['key'] = models.Point(1, 2)
        cache._sql(
            'UPDATE Cache SET mode = ?, value = ? WHERE key = ?',
            (MODE_PICKLE, sqlite3.Binary(pickle.dumps(Poison(path))), 'key'),
        )
        with pytest.raises(pickle.UnpicklingError, match='refuses'):
            cache['key']  # pylint: disable=pointless-statement

    assert not op.exists(path)


def test_module_prefix_round_trip(directory):
    disk = dc.SafeDisk.with_types(modules=[MODULE])
    values = [
        models.Point(1, 2),
        models.PointSubclass(3, 4),
        models.Outer.Inner('x'),
        models.Color.RED,
        Foreign('defined in a sibling module'),
    ]

    with dc.Cache(directory, disk=disk) as cache:
        for number, value in enumerate(values):
            cache[number] = value
            assert cache[number] == value


def test_module_prefix_matches_whole_names():
    unpickler = SafeUnpickler(io.BytesIO(b''), modules=['tests.safedisk'])

    with pytest.raises(pickle.UnpicklingError, match='refuses'):
        unpickler.find_class('tests.safedisk_models.models', 'Point')


def test_module_prefix_does_not_reach_imported_names():
    disk = dc.SafeDisk.with_types(modules=['tests.safedisk_models.models'])
    module = 'tests.safedisk_models.models'

    with pytest.raises(TypeError, match='Foreign'):
        disk(tempfile.gettempdir()).store(Foreign('x'), False)

    for name in (
        'os.system',
        'os',
        'Foreign',
        'collections.OrderedDict',
        'Point.__subclasses__',
        'Point.__init__',
        'Point.',
        'dataclasses.dataclass',
    ):
        with pytest.raises(pickle.UnpicklingError, match='refuses'):
            SafeUnpickler(
                io.BytesIO(stack_global(module, name)), modules=[module]
            ).load()


def test_module_prefix_blocks_dotted_name_to_os_system(directory):
    path = op.join(directory, 'marker')
    module = 'tests.safedisk_models.models'
    data = stack_global(module, 'os.system', 'touch %s' % path)

    with pytest.raises(pickle.UnpicklingError, match='os.system'):
        SafeUnpickler(io.BytesIO(data), modules=[MODULE]).load()

    assert not op.exists(path)


def test_refused_modules_are_not_imported():
    name = 'tests.safedisk_models.never_imported'
    unpickler = SafeUnpickler(io.BytesIO(b''), classes=[models.Point])

    with pytest.raises(pickle.UnpicklingError, match='refuses'):
        unpickler.find_class(name, 'Anything')

    assert name not in sys.modules


def test_exact_class_must_be_the_same_object():
    unpickler = SafeUnpickler(io.BytesIO(b''), classes=[models.Point])

    assert unpickler.find_class(models.__name__, 'Point') is models.Point
    with pytest.raises(pickle.UnpicklingError, match='refuses'):
        unpickler.find_class(models.__name__, 'PointSubclass')
    with pytest.raises(pickle.UnpicklingError, match='refuses'):
        unpickler.find_class(models.__name__, 'os')


def test_default_allowlist_unchanged(directory):
    with dc.Cache(directory, disk=dc.SafeDisk) as cache:
        with pytest.raises(TypeError, match='SafeDisk cannot store value'):
            cache['point'] = models.Point(1, 2)


def test_typed_memoize_with_types(directory):
    disk = dc.SafeDisk.with_types(models.Point)

    with dc.Cache(directory, disk=disk) as cache:

        @cache.memoize(typed=True)
        def double(value):
            return value * 2

        assert double(2) == 4
        assert double(2) == 4
        assert double(2.0) == 4.0
        assert len(cache) == 2


@pytest.mark.parametrize('protocol', [0, 1, 2, 3, 4, 5])
def test_pickle_globals_matches_pickletools(protocol):
    values = [
        models.Point(1, 2),
        [models.Point(1, 2), models.Point(3, 4), models.Pair(1, 2)],
        {models.Color.RED: models.Outer.Inner(1)},
        int,
        sqlite3.Row,
    ]

    for value in values:
        data = pickle.dumps(value, protocol=protocol)
        expected = set()
        for opcode, arg, _ in pickletools.genops(data):
            if opcode.name in ('GLOBAL', 'INST'):
                expected.add(tuple(arg.split(' ', 1)))
        found = _pickle_globals(data)
        assert found is not None
        assert expected <= found


def test_pickle_globals_gives_up_on_unknown_operands():
    data = b'\x80\x04\x8c\x04name\x8c\x04attr\x86\x94\x93.'
    assert _pickle_globals(data) is None


def test_write_check_falls_back_to_loading(directory, monkeypatch):
    disk = dc.SafeDisk.with_types(models.Point)
    monkeypatch.setattr(
        'diskcache_community.core._pickle_globals', lambda data: None
    )

    with dc.Cache(directory, disk=disk) as cache:
        cache['point'] = models.Point(1, 2)
        assert cache['point'] == models.Point(1, 2)
        with pytest.raises(TypeError, match='SafeDisk cannot store value'):
            cache['shape'] = models.Shape('line', [])


def test_cache_with_derived_disk_pickles(directory):
    disk = dc.SafeDisk.with_types(models.Point, modules=MODULE)

    with dc.Cache(directory, disk=disk) as cache:
        cache['point'] = models.Point(1, 2)
        copy = pickle.loads(pickle.dumps(cache))
        try:
            assert type(copy.disk).safe_types == disk.safe_types
            assert type(copy.disk).safe_modules == disk.safe_modules
            assert copy['point'] == models.Point(1, 2)
        finally:
            copy.close()

    with dc.FanoutCache(directory + '-fanout', disk=disk) as fanout:
        copy = pickle.loads(pickle.dumps(fanout))
        try:
            assert type(copy._shards[0].disk).safe_types == disk.safe_types
        finally:
            copy.close()


def test_containers_take_derived_disks(directory):
    disk = dc.SafeDisk.with_types(models.Point)

    deque = dc.Deque([models.Point(1, 2)], directory=directory, disk=disk)
    assert deque[0] == models.Point(1, 2)
    deque.cache.close()

    index = dc.Index(op.join(directory, 'index'), disk=disk)
    index['point'] = models.Point(3, 4)
    assert index['point'] == models.Point(3, 4)
    index.cache.close()

    with dc.FanoutCache(op.join(directory, 'fanout'), disk=disk) as fanout:
        fanout['point'] = models.Point(5, 6)
        assert fanout['point'] == models.Point(5, 6)
        assert type(fanout.cache('sub').disk) is disk


def test_django_disk_option_with_derived_disk(directory):
    pytest.importorskip('django')
    disk = dc.SafeDisk.with_types(models.Point)

    django_cache = dc.DjangoCache(directory, {'DISK': disk})
    try:
        assert type(django_cache._cache.disk) is disk
        assert django_cache.set('point', models.Point(1, 2))
        assert django_cache.get('point') == models.Point(1, 2)
    finally:
        django_cache.close()


def test_numpy_is_refused(directory):
    np = pytest.importorskip('numpy')

    for entry in (np.ndarray, np.dtype, np.float64):
        with pytest.raises(ValueError, match='refuses the class'):
            dc.SafeDisk.with_types(entry)

    for prefix in ('numpy', 'numpy.', 'numpy._core', 'numpy.core.multiarray'):
        with pytest.raises(ValueError, match='refuses the module'):
            dc.SafeDisk.with_types(modules=prefix)

    disk = dc.SafeDisk.with_types(models.Point, modules=MODULE)

    with dc.Cache(directory, disk=disk) as cache:
        for value in (np.arange(3), np.float64(1.5), np.dtype('f8')):
            with pytest.raises(TypeError, match='numpy'):
                cache['value'] = value


def test_modules_are_never_imported_by_a_read():
    name = 'tests.safedisk_models.side_effect'
    data = stack_global(name, 'Thing')

    with pytest.raises(pickle.UnpicklingError, match='refuses'):
        SafeUnpickler(io.BytesIO(data), modules=[MODULE]).load()

    assert name not in sys.modules


def test_trailing_dot_module_is_refused():
    data = stack_global('tests.safedisk_models.models.', 'Point')

    with pytest.raises(pickle.UnpicklingError, match='refuses'):
        SafeUnpickler(io.BytesIO(data), modules=[MODULE]).load()


def test_subclass_of_a_derived_class_is_its_own_root(directory):
    assert repr(AppDisk) == "<class 'tests.test_safedisk_types.AppDisk'>"
    assert AppDisk.safe_types == frozenset({models.Point})

    more = AppDisk.with_types(models.Pair)
    assert issubclass(more, AppDisk)
    assert more.marker == 'app'
    assert more.safe_types == frozenset({models.Point, models.Pair})

    with dc.Cache(directory, disk=AppDisk) as cache:
        cache['point'] = models.Point(1, 2)
        copy = pickle.loads(pickle.dumps(cache))
        try:
            assert type(copy.disk) is AppDisk
        finally:
            copy.close()

    assert pickle.loads(pickle.dumps(more)).safe_types == more.safe_types


def test_write_check_handles_extension_codes(directory):
    disk = dc.SafeDisk.with_types(models.Point)
    code = 0x7FFF0001
    copyreg.add_extension(models.__name__, 'Shape', code)

    try:
        data = pickle.dumps(models.Shape('line', []), protocol=2)
        assert _pickle_globals(data) is None
        with dc.Cache(directory, disk=disk, disk_pickle_protocol=2) as cache:
            with pytest.raises(TypeError, match='SafeDisk cannot store value'):
                cache['shape'] = models.Shape('line', [])
    finally:
        copyreg.remove_extension(models.__name__, 'Shape', code)


def test_pydantic_models(directory):
    pydantic = pytest.importorskip('pydantic')

    class Message(pydantic.BaseModel):
        role: str
        content: str

    Message.__qualname__ = 'Message'
    setattr(sys.modules[__name__], 'Message', Message)
    disk = dc.SafeDisk.with_types(Message)

    try:
        with dc.Cache(directory, disk=disk) as cache:
            cache['message'] = Message(role='user', content='hi')
            assert cache['message'] == Message(role='user', content='hi')
    finally:
        delattr(sys.modules[__name__], 'Message')


def test_restricted_disk_subclass_pattern(directory):
    # The pattern dspy uses for its own restricted cache: a Disk subclass
    # built with type() that overrides fetch for MODE_PICKLE and is passed
    # to FanoutCache(disk=...). The fork keeps the hooks it relies on.
    class Refused(Exception):
        pass

    class Restricted(pickle.Unpickler):
        allowed = frozenset({(models.__name__, 'Point')})

        def find_class(self, module, name):
            if (module, name) in self.allowed:
                return super().find_class(module, name)
            raise Refused('%s.%s' % (module, name))

    class RestrictedDisk(dc.Disk):
        def fetch(self, mode, filename, value, read):
            if mode == MODE_PICKLE:
                if value is None:
                    with open(op.join(self._directory, filename), 'rb') as f:
                        return Restricted(f).load()
                return Restricted(io.BytesIO(value)).load()
            return super().fetch(mode, filename, value, read)

    disk = type('RestrictedDisk', (RestrictedDisk,), {})

    with dc.FanoutCache(directory, shards=2, disk=disk) as cache:
        cache['point'] = models.Point(1, 2)
        assert cache['point'] == models.Point(1, 2)
        cache['shape'] = models.Shape('line', [])
        with pytest.raises(Refused):
            cache['shape']  # pylint: disable=pointless-statement
