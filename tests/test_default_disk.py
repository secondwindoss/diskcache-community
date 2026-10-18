"""Test diskcache_community.configure and default_disk."""

import os.path as op
import pickle
import shutil
import tempfile

import pytest

import diskcache_community as dc
from diskcache_community import core
from tests.safedisk_models import models

pytestmark = pytest.mark.filterwarnings('ignore', category=dc.EmptyDirWarning)

ENV_NAMES = (
    core.ENV_DISK,
    core.ENV_SAFE_TYPES,
    core.ENV_SAFE_MODULES,
)


@pytest.fixture(autouse=True)
def clean_default(monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    previous = dc.configure(None)
    core._disk_from_environment.cache_clear()
    yield
    dc.configure(previous)
    core._disk_from_environment.cache_clear()


@pytest.fixture
def directory():
    directory = tempfile.mkdtemp(prefix='diskcache-')
    yield directory
    shutil.rmtree(directory, ignore_errors=True)


def disk_types(directory):
    """Return the disk type of every container created without a disk."""
    types = {}

    with dc.Cache(op.join(directory, 'cache')) as cache:
        types['cache'] = type(cache.disk)

    with dc.FanoutCache(op.join(directory, 'fanout'), shards=2) as fanout:
        types['fanout'] = {type(shard.disk) for shard in fanout._shards}
        types['fanout.cache'] = type(fanout.cache('sub').disk)

    deque = dc.Deque(directory=op.join(directory, 'deque'))
    types['deque'] = type(deque.cache.disk)
    deque.cache.close()

    index = dc.Index(op.join(directory, 'index'))
    types['index'] = type(index.cache.disk)
    index.cache.close()

    return types


def assert_all(types, disk):
    assert types['cache'] is disk
    assert types['fanout'] == {disk}
    assert types['fanout.cache'] is disk
    assert types['deque'] is disk
    assert types['index'] is disk


def test_default_is_disk(directory):
    assert dc.default_disk() is dc.Disk
    assert_all(disk_types(directory), dc.Disk)


def test_configure_applies_to_every_container(directory):
    assert dc.configure(dc.SafeDisk) is None
    assert dc.default_disk() is dc.SafeDisk
    assert_all(disk_types(directory), dc.SafeDisk)


def test_configure_returns_the_previous_type_and_resets():
    disk = dc.SafeDisk.with_types(models.Point)

    assert dc.configure(dc.SafeDisk) is None
    assert dc.configure(disk) is dc.SafeDisk
    assert dc.default_disk() is disk
    assert dc.configure(None) is disk
    assert dc.default_disk() is dc.Disk


@pytest.mark.parametrize('value', [int, 'SafeDisk', dc.Disk('/tmp'), object])
def test_configure_rejects_non_disks(value):
    with pytest.raises(ValueError, match='must subclass'):
        dc.configure(value)
    assert dc.default_disk() is dc.Disk


def test_explicit_disk_wins(directory):
    dc.configure(dc.SafeDisk)

    with dc.Cache(op.join(directory, 'cache'), disk=dc.Disk) as cache:
        assert type(cache.disk) is dc.Disk

    with dc.FanoutCache(op.join(directory, 'fanout'), disk=dc.JSONDisk) as f:
        assert type(f.cache('sub').disk) is dc.JSONDisk

    deque = dc.Deque(directory=op.join(directory, 'deque'), disk=dc.Disk)
    assert type(deque.cache.disk) is dc.Disk
    deque.cache.close()

    index = dc.Index(op.join(directory, 'index'), disk=dc.Disk)
    assert type(index.cache.disk) is dc.Disk
    index.cache.close()


def test_existing_caches_keep_their_disk(directory):
    with dc.Cache(directory) as cache:
        dc.configure(dc.SafeDisk)
        assert type(cache.disk) is dc.Disk
        cache['custom'] = models.Point(1, 2)


def test_pickled_cache_keeps_its_disk(directory):
    with dc.Cache(directory) as cache:
        data = pickle.dumps(cache)

    dc.configure(dc.SafeDisk)
    copy = pickle.loads(data)
    try:
        assert type(copy.disk) is dc.Disk
    finally:
        copy.close()


def test_django_uses_the_default(directory):
    pytest.importorskip('django')
    dc.configure(dc.SafeDisk)

    django_cache = dc.DjangoCache(directory, {})
    try:
        assert type(django_cache._cache.disk) is dc.SafeDisk
    finally:
        django_cache.close()

    django_cache = dc.DjangoCache(directory, {'DISK': dc.Disk})
    try:
        assert type(django_cache._cache.disk) is dc.Disk
    finally:
        django_cache.close()


@pytest.mark.parametrize('value', ['safe', 'SAFE', ' Safe '])
def test_environment_safe(monkeypatch, directory, value):
    monkeypatch.setenv(core.ENV_DISK, value)
    assert dc.default_disk() is dc.SafeDisk
    assert_all(disk_types(directory), dc.SafeDisk)


@pytest.mark.parametrize('value', ['', 'default', 'Default'])
def test_environment_default(monkeypatch, value):
    monkeypatch.setenv(core.ENV_DISK, value)
    assert dc.default_disk() is dc.Disk


@pytest.mark.parametrize(
    'value',
    [
        'diskcache_community:JSONDisk',
        'diskcache_community.JSONDisk',
        'diskcache_community.core:JSONDisk',
    ],
)
def test_environment_import_path(monkeypatch, value):
    monkeypatch.setenv(core.ENV_DISK, value)
    assert dc.default_disk() is dc.JSONDisk


@pytest.mark.parametrize(
    'value', ['no.such.module:Disk', 'diskcache_community:NoSuchDisk', 'x']
)
def test_environment_bad_import_path(monkeypatch, value):
    monkeypatch.setenv(core.ENV_DISK, value)
    with pytest.raises(ValueError, match=core.ENV_DISK):
        dc.default_disk()
    with pytest.raises(ValueError, match=core.ENV_DISK):
        dc.Cache()


def test_environment_import_path_must_be_a_disk(monkeypatch):
    monkeypatch.setenv(core.ENV_DISK, 'os.path:join')
    with pytest.raises(ValueError, match='must subclass'):
        dc.default_disk()


def test_environment_safe_types(monkeypatch, directory):
    monkeypatch.setenv(core.ENV_DISK, 'safe')
    monkeypatch.setenv(
        core.ENV_SAFE_TYPES,
        'tests.safedisk_models.models:Point, tests.safedisk_models.models.Pair',
    )
    monkeypatch.setenv(core.ENV_SAFE_MODULES, 'litellm.types,openai.types')

    disk = dc.default_disk()

    assert issubclass(disk, dc.SafeDisk)
    assert disk.safe_types == frozenset({models.Point, models.Pair})
    assert disk.safe_modules == ('litellm.types', 'openai.types')
    assert dc.default_disk() is disk

    with dc.Cache(directory) as cache:
        cache['point'] = models.Point(1, 2)
        assert cache['point'] == models.Point(1, 2)
        with pytest.raises(TypeError, match='Shape'):
            cache['shape'] = models.Shape('line', [])


def test_environment_bad_safe_type(monkeypatch):
    monkeypatch.setenv(core.ENV_DISK, 'safe')
    monkeypatch.setenv(
        core.ENV_SAFE_TYPES, 'tests.safedisk_models.models:Nope'
    )
    with pytest.raises(ValueError, match=core.ENV_SAFE_TYPES):
        dc.default_disk()


@pytest.mark.parametrize('disk', ['', 'default', 'diskcache_community:Disk'])
def test_environment_extras_need_safe(monkeypatch, disk):
    monkeypatch.setenv(core.ENV_DISK, disk)
    monkeypatch.setenv(core.ENV_SAFE_MODULES, 'litellm.types')
    with pytest.raises(ValueError, match='only with DISKCACHE_DISK=safe'):
        dc.default_disk()


def test_environment_is_read_at_each_creation(monkeypatch, directory):
    with dc.Cache(op.join(directory, 'first')) as cache:
        assert type(cache.disk) is dc.Disk

    monkeypatch.setenv(core.ENV_DISK, 'safe')

    with dc.Cache(op.join(directory, 'second')) as cache:
        assert type(cache.disk) is dc.SafeDisk


def test_configure_beats_the_environment(monkeypatch):
    monkeypatch.setenv(core.ENV_DISK, 'safe')
    dc.configure(dc.JSONDisk)
    assert dc.default_disk() is dc.JSONDisk
    dc.configure(None)
    assert dc.default_disk() is dc.SafeDisk


def test_default_disk_not_persisted(directory):
    dc.configure(dc.SafeDisk)

    with dc.Cache(directory) as cache:
        cache['key'] = 'value'
        names = {name for (name,) in cache._sql('SELECT key FROM Settings')}

    assert not any('disk' in name and 'disk_' not in name for name in names)
    dc.configure(None)

    with dc.Cache(directory) as cache:
        assert type(cache.disk) is dc.Disk
        assert cache['key'] == 'value'
