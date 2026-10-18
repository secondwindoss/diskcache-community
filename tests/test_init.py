"""Test the package identity and coexistence with upstream diskcache."""

import importlib.util
import os.path as op
import subprocess as sp
import sys

import pytest

import diskcache_community as dc

COEXIST_SCRIPT = """
import os.path as op
import sys

import diskcache
import diskcache_community

directory = sys.argv[1]
assert diskcache.__version__ == '5.6.3', diskcache.__version__
assert op.dirname(diskcache.__file__) != op.dirname(diskcache_community.__file__)

with diskcache_community.Cache(op.join(directory, 'by-fork')) as cache:
    cache['key'] = {'written': 'fork'}
with diskcache.Cache(op.join(directory, 'by-fork')) as cache:
    assert cache['key'] == {'written': 'fork'}

with diskcache.Cache(op.join(directory, 'by-upstream')) as cache:
    cache['key'] = {'written': 'upstream'}
with diskcache_community.Cache(op.join(directory, 'by-upstream')) as cache:
    assert cache['key'] == {'written': 'upstream'}

print('coexist ok')
"""


def test_identity():
    assert dc.__name__ == 'diskcache_community'
    assert dc.__title__ == 'diskcache-community'


def test_does_not_provide_the_upstream_package():
    spec = importlib.util.find_spec('diskcache')
    if spec is None:
        return
    ours = op.dirname(op.abspath(dc.__file__))
    assert op.dirname(op.abspath(spec.origin)) != ours


def test_coexists_with_upstream(tmp_path):
    if importlib.util.find_spec('diskcache') is None:
        pytest.skip('the upstream diskcache distribution is not installed')
    result = sp.run(
        [sys.executable, '-c', COEXIST_SCRIPT, str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'coexist ok' in result.stdout
