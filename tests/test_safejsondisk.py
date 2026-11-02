"""Test diskcache_community.SafeJSONDisk."""

import io
import os
import os.path as op
import pickle
import shutil
import sqlite3
import tempfile

import pytest

import diskcache_community as dc
from diskcache_community import core
from diskcache_community.core import MODE_BINARY, MODE_PICKLE

pytestmark = pytest.mark.filterwarnings('ignore', category=dc.EmptyDirWarning)

MissDisk = dc.SafeJSONDisk.with_options(on_error='miss')


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


@pytest.fixture
def directory():
    directory = tempfile.mkdtemp(prefix='diskcache-')
    yield directory
    shutil.rmtree(directory, ignore_errors=True)


@pytest.fixture
def marker(directory):
    """Path that exists only if a crafted pickle ran."""
    path = directory + '.executed'
    yield path
    if op.exists(path):
        os.remove(path)


@pytest.fixture
def victim():
    """File outside every cache directory."""
    outside = tempfile.mkdtemp(prefix='diskcache-outside-')
    path = op.join(outside, 'victim.txt')
    with open(path, 'w', encoding='utf-8') as writer:
        writer.write('precious')
    yield path
    shutil.rmtree(outside, ignore_errors=True)


def tamper(directory, statement, *parameters):
    """Run `statement` on cache.db behind the cache's back."""
    con = sqlite3.connect(op.join(directory, 'cache.db'))
    con.execute(statement, parameters)
    con.commit()
    con.close()


def write_entry(directory):
    """Store one entry the way a JSONDisk cache would."""
    with dc.Cache(directory, disk=dc.JSONDisk) as cache:
        cache['key'] = {'value': 1}


def pickled(obj):
    return sqlite3.Binary(pickle.dumps(obj, protocol=2))


@pytest.mark.parametrize(
    'value',
    [None, True, 1, 1.5, 'text', [1, 'two', None], {'a': [1, {'b': None}]}],
)
def test_round_trip(directory, value):
    with dc.Cache(directory, disk=dc.SafeJSONDisk) as cache:
        cache['key'] = value
        assert cache['key'] == value


def test_keys_are_json(directory):
    with dc.Cache(directory, disk=dc.SafeJSONDisk) as cache:
        cache['text'] = 1
        cache[2] = 2
        cache[['a', 1]] = 3
        assert cache[['a', 1]] == 3
        assert cache.peekitem(last=False) == ('text', 1)
        assert sorted(map(str, cache)) == ['2', "['a', 1]", 'text']


def test_refuses_what_json_cannot_hold(directory):
    with dc.Cache(directory, disk=dc.SafeJSONDisk) as cache:
        with pytest.raises(TypeError):
            cache['key'] = {1, 2}


def test_file_backed_value(directory):
    with dc.Cache(
        directory, disk=dc.SafeJSONDisk, disk_min_file_size=0
    ) as cache:
        cache['key'] = {'value': 'x' * 1000}
        assert cache['key'] == {'value': 'x' * 1000}
        assert cache.check() == []
        del cache['key']
        assert cache.check() == []


def test_read_returns_a_file(directory):
    with dc.Cache(directory, disk=dc.SafeJSONDisk) as cache:
        cache.set('key', io.BytesIO(b'raw bytes'), read=True)
        with cache.get('key', read=True) as reader:
            assert reader.read() == b'raw bytes'


def test_compress_level(directory):
    with dc.Cache(
        directory, disk=dc.SafeJSONDisk, disk_compress_level=6
    ) as cache:
        assert cache.disk.compress_level == 6


@pytest.mark.parametrize(
    ('writer', 'reader'),
    [(dc.JSONDisk, dc.SafeJSONDisk), (dc.SafeJSONDisk, dc.JSONDisk)],
)
def test_same_files_as_jsondisk(directory, writer, reader):
    with dc.Cache(directory, disk=writer) as cache:
        cache['small'] = {'value': 1}
        cache['large'] = 'x' * 100000
        cache.set('bytes', io.BytesIO(b'raw'), read=True)

    with dc.Cache(directory, disk=reader) as cache:
        assert cache['small'] == {'value': 1}
        assert cache['large'] == 'x' * 100000
        assert cache.get('bytes', read=True).read() == b'raw'
        assert sorted(cache) == ['bytes', 'large', 'small']
        assert cache.check() == []


def test_fanout_shards_match_jsondisk(directory):
    keys = ['key-%d' % number for number in range(20)]

    with dc.FanoutCache(directory, shards=4, disk=dc.JSONDisk) as cache:
        for key in keys:
            cache[key] = key

    with dc.FanoutCache(directory, shards=4, disk=dc.SafeJSONDisk) as cache:
        assert [cache[key] for key in keys] == keys


@pytest.mark.parametrize('disk', [dc.SafeJSONDisk, MissDisk])
def test_cache_pickles_with_its_disk(directory, disk):
    with dc.Cache(directory, disk=disk) as cache:
        copy = pickle.loads(pickle.dumps(cache))
        assert isinstance(copy.disk, dc.SafeJSONDisk)
        assert copy.disk.on_error == disk.on_error
        copy.close()


def test_selected_by_import_path(monkeypatch):
    monkeypatch.setenv(core.ENV_DISK, 'diskcache_community:SafeJSONDisk')
    core._disk_from_environment.cache_clear()
    assert dc.default_disk() is dc.SafeJSONDisk
    monkeypatch.undo()
    core._disk_from_environment.cache_clear()


def test_payload_runs_on_jsondisk(directory, marker):
    """Control: the crafted row of the next tests does run on JSONDisk."""
    write_entry(directory)
    tamper(
        directory,
        'UPDATE Cache SET mode = ?, value = ?',
        MODE_PICKLE,
        pickled(Poison(marker)),
    )

    with dc.Cache(directory, disk=dc.JSONDisk) as cache:
        with pytest.raises(TypeError):
            cache['key']

    assert op.exists(marker)


def test_pickled_value_is_refused(directory, marker):
    write_entry(directory)
    tamper(
        directory,
        'UPDATE Cache SET mode = ?, value = ?',
        MODE_PICKLE,
        pickled(Poison(marker)),
    )

    with dc.Cache(directory, disk=dc.SafeJSONDisk) as cache:
        with pytest.raises(pickle.UnpicklingError):
            cache['key']

    assert not op.exists(marker)


def test_pickled_value_is_a_miss(directory, marker):
    write_entry(directory)
    tamper(
        directory,
        'UPDATE Cache SET mode = ?, value = ?',
        MODE_PICKLE,
        pickled(Poison(marker)),
    )

    with dc.Cache(directory, disk=MissDisk) as cache:
        assert cache.get('key', 'default') == 'default'
        assert len(cache) == 0

    assert not op.exists(marker)


def test_pickled_value_in_a_file_is_refused(directory, marker):
    write_entry(directory)
    with open(op.join(directory, 'planted.val'), 'wb') as writer:
        writer.write(pickle.dumps(Poison(marker), protocol=2))
    tamper(
        directory,
        'UPDATE Cache SET mode = ?, value = NULL, filename = ?',
        MODE_PICKLE,
        'planted.val',
    )

    with dc.Cache(directory, disk=dc.SafeJSONDisk) as cache:
        with pytest.raises(pickle.UnpicklingError):
            cache['key']

    assert not op.exists(marker)


def test_allowlisted_pickle_is_refused_too(directory):
    """SafeDisk would return the str; this disk reads no pickle at all."""
    write_entry(directory)
    tamper(
        directory,
        'UPDATE Cache SET mode = ?, value = ?',
        MODE_PICKLE,
        pickled('a plain string'),
    )

    with dc.Cache(directory, disk=dc.SafeJSONDisk) as cache:
        with pytest.raises(pickle.UnpicklingError):
            cache.get('key', read=True)


def test_read_of_a_pickled_row_is_a_miss(directory):
    write_entry(directory)
    tamper(
        directory,
        'UPDATE Cache SET mode = ?, value = ?',
        MODE_PICKLE,
        pickled('a plain string'),
    )

    with dc.Cache(directory, disk=MissDisk) as cache:
        assert cache.get('key', 'default', read=True) == 'default'


def test_pickled_key_is_refused(directory, marker):
    write_entry(directory)
    tamper(
        directory,
        'UPDATE Cache SET raw = 0, key = ?',
        pickled(Poison(marker)),
    )

    with dc.Cache(directory, disk=dc.SafeJSONDisk) as cache:
        with pytest.raises(pickle.UnpicklingError):
            list(cache)

    assert not op.exists(marker)


def test_pickled_key_is_refused_with_miss(directory, marker):
    write_entry(directory)
    tamper(
        directory,
        'UPDATE Cache SET raw = 0, key = ?',
        pickled(Poison(marker)),
    )

    with dc.Cache(directory, disk=MissDisk) as cache:
        assert list(cache) == []

    assert not op.exists(marker)


def test_allowlisted_pickled_key_is_refused_too(directory):
    """SafeDisk would unpickle the str; this disk reads no pickle at all."""
    write_entry(directory)
    tamper(
        directory,
        'UPDATE Cache SET raw = 0, key = ?',
        pickled('a plain string'),
    )

    with dc.Cache(directory, disk=dc.SafeJSONDisk) as cache:
        with pytest.raises(pickle.UnpicklingError, match='pickled key'):
            list(cache)


def test_filename_outside_the_cache_is_not_read(directory, victim):
    write_entry(directory)
    tamper(
        directory,
        'UPDATE Cache SET mode = ?, value = NULL, filename = ?',
        MODE_BINARY,
        op.relpath(victim, directory),
    )

    with dc.Cache(directory, disk=dc.SafeJSONDisk) as cache:
        with pytest.raises(ValueError):
            cache['key']


def test_delete_keeps_a_file_outside_the_cache(directory, victim):
    write_entry(directory)
    tamper(
        directory,
        'UPDATE Cache SET mode = ?, value = NULL, filename = ?',
        MODE_BINARY,
        op.relpath(victim, directory),
    )

    with dc.Cache(directory, disk=dc.SafeJSONDisk) as cache:
        with pytest.raises(ValueError):
            cache.delete('key')

    assert op.exists(victim)


def test_delete_with_jsondisk_removes_a_file_outside_the_cache(
    directory, victim
):
    """Control: the crafted path of the test above does work on JSONDisk."""
    write_entry(directory)
    tamper(
        directory,
        'UPDATE Cache SET mode = ?, value = NULL, filename = ?',
        MODE_BINARY,
        op.relpath(victim, directory),
    )

    with dc.Cache(directory, disk=dc.JSONDisk) as cache:
        cache.delete('key')

    assert not op.exists(victim)


def test_pickled_row_outside_the_cache_is_a_miss(directory, victim):
    write_entry(directory)
    tamper(
        directory,
        'UPDATE Cache SET mode = ?, value = NULL, filename = ?',
        MODE_PICKLE,
        op.relpath(victim, directory),
    )

    with dc.Cache(directory, disk=MissDisk) as cache:
        assert cache.get('key', 'default') == 'default'

    assert op.exists(victim)


@pytest.mark.parametrize(
    'value', [b'not compressed', b'x\x9c\x03\x00\x00\x00\x00\x01']
)
def test_corrupt_value_is_a_miss(directory, value):
    write_entry(directory)
    tamper(directory, 'UPDATE Cache SET value = ?', sqlite3.Binary(value))

    with dc.Cache(directory, disk=MissDisk) as cache:
        assert cache.get('key', 'default') == 'default'
