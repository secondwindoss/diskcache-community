"""Golden compatibility tests: open caches written by diskcache 5.6.3.

The fixtures in ``tests/golden/diskcache-5.6.3.tar.gz`` were written by the
upstream 5.6.3 wheel (see ``tests/golden/README.rst``). Every test opens one
of them with the current code and asserts, through ``tests.golden.verify``,
that keys, values, tags, expire times, counters, memoized results, settings,
schema object names and ``check()`` all come back as the recipe says.
"""

import os
import os.path as op
import subprocess as sp
import tarfile
import time

import pytest

from tests.golden import make_fixtures, recipe, verify

ARCHIVE = op.join(op.dirname(__file__), 'golden', recipe.ARCHIVE)
REVERSE_PYTHON = 'DISKCACHE_GOLDEN_563_PYTHON'


def extract(archive, path):
    with tarfile.open(archive) as tar:
        try:
            tar.extractall(path, filter='data')
        except TypeError:
            # Python before 3.10.12 and 3.11.4 has no extraction filters.
            tar.extractall(path)


@pytest.fixture(scope='module')
def golden_root(tmp_path_factory):
    path = tmp_path_factory.mktemp('golden')
    extract(ARCHIVE, path)
    return str(path / recipe.ARCHIVE_ROOT)


def test_provenance(golden_root):
    with open(op.join(golden_root, recipe.PROVENANCE), encoding='utf-8') as f:
        text = f.read()
    assert 'diskcache %s' % recipe.WHEEL_VERSION in text
    assert recipe.WHEEL_SHA256 in text
    assert 'pickle protocol %d' % recipe.WRITER_PICKLE_PROTOCOL in text


def test_cache_default(golden_root):
    verify.verify_cache(op.join(golden_root, recipe.DIR_DEFAULT))


def test_cache_tag_index(golden_root):
    verify.verify_cache(
        op.join(golden_root, recipe.DIR_TAG_INDEX), tag_index=1
    )


@pytest.mark.parametrize('policy', recipe.EVICTION_POLICIES)
def test_cache_eviction_policy(golden_root, policy):
    path = op.join(golden_root, recipe.DIR_POLICY.format(policy))
    verify.verify_cache(path, policy)


def test_cache_statistics(golden_root):
    verify.verify_statistics(op.join(golden_root, recipe.DIR_STATISTICS))


def test_cache_settings(golden_root):
    path = op.join(golden_root, recipe.DIR_SETTINGS)
    verify.verify_cache(path, **recipe.SETTINGS_OVERRIDES)


def test_cache_jsondisk(golden_root):
    verify.verify_jsondisk(op.join(golden_root, recipe.DIR_JSONDISK))


def test_fanout(golden_root):
    verify.verify_fanout(op.join(golden_root, recipe.DIR_FANOUT))


def test_deque(golden_root):
    verify.verify_deque(op.join(golden_root, recipe.DIR_DEQUE))


def test_index(golden_root):
    verify.verify_index(op.join(golden_root, recipe.DIR_INDEX))


def test_memoize_miss_is_visible():
    # The guard that makes the memoize checks meaningful.
    with pytest.raises(RuntimeError):
        recipe.golden_square(3)


def test_current_code_writes_what_563_reads(tmp_path):
    python = os.environ.get(REVERSE_PYTHON)
    if not python:
        pytest.skip('%s is not set' % REVERSE_PYTHON)
    root = tmp_path / 'written-by-current'
    make_fixtures.write_all(root)
    time.sleep(recipe.EXPIRE_SECONDS + 0.5)
    verify.verify_all(root)
    script = op.join(op.dirname(__file__), 'golden', 'verify.py')
    command = [
        python,
        '-I',
        script,
        str(root),
        '--expect-version',
        recipe.WHEEL_VERSION,
    ]
    result = sp.run(
        command,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'diskcache %s' % recipe.WHEEL_VERSION in result.stdout
