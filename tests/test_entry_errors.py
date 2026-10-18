"""Test Disk.with_options(on_error='miss')."""

import logging
import os
import os.path as op
import pickle
import shutil
import sqlite3
import tempfile

import pytest

import diskcache_community as dc
from diskcache_community.core import MODE_PICKLE, MODE_TEXT
from tests.safedisk_models import models

pytestmark = pytest.mark.filterwarnings('ignore', category=dc.EmptyDirWarning)

MissDisk = dc.Disk.with_options(on_error='miss')
CORRUPT = b'\x80\x05\x95garbage'
STALE = b'\x80\x04\x8c\x0cno_such_mod1\x8c\x03Cls\x93)\x81.'


def _execute(path):
    with open(path, 'w', encoding='utf-8') as writer:
        writer.write('executed')
    return 'executed'


class Poison:
    def __init__(self, path):
        self.path = path

    def __reduce__(self):
        return (_execute, (self.path,))


@pytest.fixture
def directory():
    directory = tempfile.mkdtemp(prefix='diskcache-')
    yield directory
    shutil.rmtree(directory, ignore_errors=True)


def corrupt(cache, key, data=CORRUPT):
    """Replace the value of `key` with the pickle bytes `data`, inline."""
    cache._sql(
        'UPDATE Cache SET mode = ?, value = ?, filename = NULL'
        ' WHERE key = ? AND raw = 1',
        (MODE_PICKLE, sqlite3.Binary(data), key),
    )


def count(cache):
    ((rows,),) = cache._sql('SELECT COUNT(*) FROM Cache').fetchall()
    return rows


def test_with_options_derives_a_subclass():
    assert issubclass(MissDisk, dc.Disk)
    assert MissDisk.on_error == 'miss'
    assert dc.Disk.on_error == 'raise'
    assert 'on_error' in repr(MissDisk)
    assert MissDisk.__bases__ == (dc.Disk,)


@pytest.mark.parametrize('value', ['ignore', None, True, 'MISS'])
def test_with_options_rejects_unknown_values(value):
    with pytest.raises(ValueError, match='on_error'):
        dc.Disk.with_options(on_error=value)


def test_with_options_combines_with_with_types():
    first = dc.SafeDisk.with_types(models.Point).with_options(on_error='miss')
    second = dc.SafeDisk.with_options(on_error='miss').with_types(models.Pair)

    assert first.on_error == 'miss'
    assert first.safe_types == frozenset({models.Point})
    assert second.on_error == 'miss'
    assert second.safe_types == frozenset({models.Pair})
    assert first.__bases__ == second.__bases__ == (dc.SafeDisk,)


def test_default_still_raises(directory):
    with dc.Cache(directory) as cache:
        cache['key'] = {'a': 1}
        corrupt(cache, 'key')
        with pytest.raises(pickle.UnpicklingError):
            cache.get('key')
        assert count(cache) == 1


@pytest.mark.parametrize('data', [CORRUPT, STALE])
def test_get_treats_unreadable_value_as_missing(directory, data):
    with dc.Cache(directory, disk=MissDisk) as cache:
        cache['key'] = {'a': 1}
        cache['other'] = {'b': 2}
        corrupt(cache, 'key', data)

        assert cache.get('key', default='missing') == 'missing'
        assert count(cache) == 1
        assert 'key' not in cache
        with pytest.raises(KeyError):
            cache['key']  # pylint: disable=pointless-statement
        assert cache['other'] == {'b': 2}

        cache['key'] = {'a': 3}
        assert cache['key'] == {'a': 3}


def test_get_metadata_default(directory):
    with dc.Cache(directory, disk=MissDisk) as cache:
        cache.set('key', {'a': 1}, tag='t')
        corrupt(cache, 'key')
        assert cache.get('key', 'd', expire_time=True, tag=True) == (
            'd',
            None,
            None,
        )


def test_unreadable_file_value(directory):
    with dc.Cache(directory, disk=MissDisk, disk_min_file_size=0) as cache:
        cache['key'] = {'a': 1}
        ((filename,),) = cache._sql(
            'SELECT filename FROM Cache WHERE key = ?', ('key',)
        ).fetchall()
        full_path = op.join(directory, filename)
        with open(full_path, 'wb') as writer:
            writer.write(CORRUPT)

        assert cache.get('key') is None
        assert count(cache) == 0
        assert not op.exists(full_path)


def test_unreadable_text_file(directory):
    with dc.Cache(directory, disk=MissDisk, disk_min_file_size=0) as cache:
        cache['key'] = 'text'
        ((mode, filename),) = cache._sql(
            'SELECT mode, filename FROM Cache WHERE key = ?', ('key',)
        ).fetchall()
        assert mode == MODE_TEXT
        with open(op.join(directory, filename), 'wb') as writer:
            writer.write(b'\xff\xfe\xfa')

        assert cache.get('key') is None
        assert count(cache) == 0


def test_missing_file_unchanged(directory):
    with dc.Cache(directory, disk=MissDisk, disk_min_file_size=0) as cache:
        cache['key'] = {'a': 1}
        ((filename,),) = cache._sql(
            'SELECT filename FROM Cache WHERE key = ?', ('key',)
        ).fetchall()
        os.remove(op.join(directory, filename))

        assert cache.get('key') is None
        assert count(cache) == 1


def test_statistics_and_eviction_policy_paths(directory):
    with dc.Cache(
        directory,
        disk=MissDisk,
        statistics=True,
        eviction_policy='least-recently-used',
    ) as cache:
        cache['key'] = {'a': 1}
        corrupt(cache, 'key')

        assert cache.get('key') is None
        assert cache.stats() == (0, 1)
        assert count(cache) == 0


def test_safedisk_refusal_is_a_miss(directory):
    path = op.join(directory, 'marker')
    disk = dc.SafeDisk.with_types(models.Point).with_options(on_error='miss')

    with dc.Cache(directory) as cache:
        cache['shape'] = models.Shape('line', [])
        cache['point'] = models.Point(1, 2)
        cache['poison'] = 'value'
        corrupt(cache, 'poison', pickle.dumps(Poison(path)))

    with dc.Cache(directory, disk=disk) as cache:
        assert cache.get('shape') is None
        assert cache.get('poison') is None
        assert cache['point'] == models.Point(1, 2)
        assert count(cache) == 1

    assert not op.exists(path)


def test_safedisk_path_escape_is_a_miss_and_keeps_the_file(directory):
    outside = op.join(directory, 'outside.val')
    with open(outside, 'wb') as writer:
        writer.write(pickle.dumps({'secret': 1}))

    cache_dir = op.join(directory, 'cache')
    disk = dc.SafeDisk.with_options(on_error='miss')

    with dc.Cache(cache_dir) as cache:
        cache['key'] = {'a': 1}
        cache._sql(
            'UPDATE Cache SET mode = ?, value = NULL, filename = ?'
            ' WHERE key = ?',
            (MODE_PICKLE, outside, 'key'),
        )

    with dc.Cache(cache_dir, disk=disk) as cache:
        assert cache.get('key') is None
        assert count(cache) == 0

    assert op.exists(outside)


def test_pop(directory):
    with dc.Cache(directory, disk=MissDisk, disk_min_file_size=0) as cache:
        cache['key'] = {'a': 1}
        ((filename,),) = cache._sql(
            'SELECT filename FROM Cache WHERE key = ?', ('key',)
        ).fetchall()
        with open(op.join(directory, filename), 'wb') as writer:
            writer.write(CORRUPT)

        assert cache.pop('key', default='gone') == 'gone'
        assert count(cache) == 0
        assert not op.exists(op.join(directory, filename))


def test_pull_skips_unreadable_items(directory):
    with dc.Cache(directory, disk=MissDisk) as cache:
        first = cache.push({'n': 1})
        cache.push({'n': 2})
        cache._sql(
            'UPDATE Cache SET value = ? WHERE key = ?',
            (sqlite3.Binary(CORRUPT), first),
        )

        assert cache.pull()[1] == {'n': 2}
        assert cache.pull() == (None, None)
        assert count(cache) == 0


def test_peek_skips_and_deletes_unreadable_items(directory):
    with dc.Cache(directory, disk=MissDisk) as cache:
        first = cache.push({'n': 1})
        cache.push({'n': 2})
        cache._sql(
            'UPDATE Cache SET value = ? WHERE key = ?',
            (sqlite3.Binary(CORRUPT), first),
        )

        assert cache.peek()[1] == {'n': 2}
        assert count(cache) == 1


def test_peekitem_skips_unreadable_values_and_keys(directory):
    with dc.Cache(directory, disk=MissDisk) as cache:
        cache['first'] = {'n': 1}
        cache[('tuple', 'key')] = {'n': 2}
        cache['last'] = {'n': 3}
        corrupt(cache, 'last')

        assert cache.peekitem() == (('tuple', 'key'), {'n': 2})
        cache._sql(
            'UPDATE Cache SET key = ? WHERE raw = 0', (sqlite3.Binary(STALE),)
        )
        assert cache.peekitem() == ('first', {'n': 1})
        assert count(cache) == 1


def test_iteration_skips_unreadable_keys(directory):
    with dc.Cache(directory, disk=MissDisk) as cache:
        cache['a'] = 1
        cache[('b',)] = 2
        cache['c'] = 3
        cache._sql(
            'UPDATE Cache SET key = ? WHERE raw = 0', (sqlite3.Binary(STALE),)
        )

        assert list(cache) == ['a', 'c']
        assert list(reversed(cache)) == ['c', 'a']
        assert sorted(cache.iterkeys()) == ['a', 'c']
        assert len(cache) == 3


def test_iteration_raises_by_default(directory):
    with dc.Cache(directory) as cache:
        cache[('b',)] = 2
        cache._sql(
            'UPDATE Cache SET key = ? WHERE raw = 0', (sqlite3.Binary(STALE),)
        )
        with pytest.raises(ModuleNotFoundError):
            list(cache)


def test_read_only_cache_does_not_delete(directory):
    with dc.Cache(directory) as cache:
        cache['key'] = {'a': 1}
        cache.push({'n': 1})
        corrupt(cache, 'key')
        cache._sql(
            'UPDATE Cache SET value = ? WHERE raw = 1 AND key != ?',
            (sqlite3.Binary(CORRUPT), 'key'),
        )

    with dc.Cache(directory, disk=MissDisk, read_only=True) as cache:
        assert cache.get('key') is None
        assert count(cache) == 2
        with pytest.raises(pickle.UnpicklingError):
            cache.peek()
        with pytest.raises(pickle.UnpicklingError):
            cache.peekitem()


def test_logged_once_as_warning(directory, caplog):
    with dc.Cache(directory, disk=MissDisk) as cache:
        cache['a'] = {'a': 1}
        cache['b'] = {'b': 2}
        corrupt(cache, 'a')
        corrupt(cache, 'b')

        with caplog.at_level(logging.DEBUG, logger='diskcache_community'):
            cache.get('a')
            cache.get('b')

    levels = [record.levelno for record in caplog.records]
    assert levels == [logging.WARNING, logging.DEBUG]
    assert 'UnpicklingError' in caplog.records[0].getMessage()


def test_memoize_recomputes(directory):
    calls = []

    with dc.Cache(directory, disk=MissDisk) as cache:

        @cache.memoize()
        def square(number):
            calls.append(number)
            return {'value': number * number}

        assert square(3) == {'value': 9}
        cache._sql('UPDATE Cache SET value = ?', (sqlite3.Binary(CORRUPT),))
        assert square(3) == {'value': 9}
        assert calls == [3, 3]


def test_containers(directory):
    with dc.FanoutCache(op.join(directory, 'fanout'), disk=MissDisk) as f:
        f['key'] = {'a': 1}
        shard = f._shards[f._hash('key') % f._count]
        corrupt(shard, 'key')
        assert f.get('key', 'missing') == 'missing'

    index = dc.Index(op.join(directory, 'index'), disk=MissDisk)
    index['key'] = {'a': 1}
    corrupt(index.cache, 'key')
    assert index.get('key') is None
    index.cache.close()


def test_django(directory):
    pytest.importorskip('django')
    django_cache = dc.DjangoCache(directory, {'DISK': MissDisk, 'SHARDS': 1})
    try:
        django_cache.set('key', {'a': 1})
        shard = django_cache._cache._shards[0]
        ((key,),) = shard._sql('SELECT key FROM Cache').fetchall()
        corrupt(shard, key)
        assert django_cache.get('key', 'missing') == 'missing'
    finally:
        django_cache.close()


def test_custom_disk_errors_are_misses(directory):
    class Refused(Exception):
        pass

    class StrictDisk(dc.Disk):
        def fetch(self, mode, filename, value, read):
            if mode == MODE_PICKLE:
                raise Refused('no pickles here')
            return super().fetch(mode, filename, value, read)

    with dc.Cache(directory, disk=StrictDisk) as cache:
        cache['key'] = {'a': 1}
        with pytest.raises(Refused):
            cache['key']  # pylint: disable=pointless-statement

    disk = StrictDisk.with_options(on_error='miss')

    with dc.Cache(directory, disk=disk) as cache:
        assert cache.get('key') is None
        assert count(cache) == 0


def test_cache_with_options_pickles(directory):
    with dc.Cache(directory, disk=MissDisk) as cache:
        copy = pickle.loads(pickle.dumps(cache))
        try:
            assert type(copy.disk).on_error == 'miss'
        finally:
            copy.close()


def test_option_not_persisted(directory):
    with dc.Cache(directory, disk=MissDisk) as cache:
        cache['key'] = 1
        names = {name for (name,) in cache._sql('SELECT key FROM Settings')}

    assert not any('error' in name for name in names)


def test_default_raises_on_every_path(directory):
    with dc.Cache(directory, statistics=True) as cache:
        cache['key'] = {'a': 1}
        corrupt(cache, 'key')
        with pytest.raises(pickle.UnpicklingError):
            cache.get('key')
        with pytest.raises(pickle.UnpicklingError):
            cache.pop('key')

    with dc.Cache(directory + '-queue') as cache:
        first = cache.push({'n': 1})
        cache._sql(
            'UPDATE Cache SET value = ? WHERE key = ?',
            (sqlite3.Binary(CORRUPT), first),
        )
        with pytest.raises(pickle.UnpicklingError):
            cache.pull()


def test_eviction_policy_path_without_statistics(directory):
    with dc.Cache(
        directory, disk=MissDisk, eviction_policy='least-frequently-used'
    ) as cache:
        cache['key'] = {'a': 1}
        corrupt(cache, 'key')
        assert cache.get('key') is None
        assert count(cache) == 0


def test_changed_entry_is_not_deleted(directory):
    with dc.Cache(directory, disk=MissDisk) as cache:
        cache['key'] = {'a': 1}
        ((rowid, mode, filename, value),) = cache._sql(
            'SELECT rowid, mode, filename, value FROM Cache'
        ).fetchall()

        cache._drop_unreadable(rowid, mode, filename, b'something else', False)

        assert count(cache) == 1
        assert cache['key'] == {'a': 1}


def test_index_views_skip_unreadable_values(directory):
    index = dc.Index(directory, disk=MissDisk)
    index.update({'a': {'n': 1}, 'b': {'n': 2}, 'c': {'n': 3}})
    corrupt(index.cache, 'b')

    assert list(index.items()) == [('a', {'n': 1}), ('c', {'n': 3})]
    assert ('a', {'n': 1}) in index.items()
    assert ('b', {'n': 2}) not in index.items()
    index['b'] = {'n': 2}
    corrupt(index.cache, 'b')
    assert list(index.values()) == [{'n': 1}, {'n': 3}]
    assert {'n': 3} in index.values()
    assert {'n': 2} not in index.values()
    index.cache.close()


def test_memory_and_recursion_errors_are_not_misses(directory):
    class FailingDisk(dc.Disk):
        error = MemoryError

        def fetch(self, mode, filename, value, read):
            raise self.error('not about the entry')

    for error in (MemoryError, RecursionError):
        disk = type(
            'FailingDisk', (FailingDisk,), {'error': error}
        ).with_options(on_error='miss')
        with dc.Cache(op.join(directory, error.__name__), disk=disk) as c:
            c['key'] = {'a': 1}
            with pytest.raises(error):
                c.get('key')
            assert count(c) == 1
