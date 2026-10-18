import doctest

import diskcache_community.core
import diskcache_community.djangocache
import diskcache_community.fanout
import diskcache_community.persistent
import diskcache_community.recipes


def test_core():
    failures, _ = doctest.testmod(diskcache_community.core)
    assert failures == 0


def test_djangocache():
    failures, _ = doctest.testmod(diskcache_community.djangocache)
    assert failures == 0


def test_fanout():
    failures, _ = doctest.testmod(diskcache_community.fanout)
    assert failures == 0


def test_persistent():
    failures, _ = doctest.testmod(diskcache_community.persistent)
    assert failures == 0


def test_recipes():
    failures, _ = doctest.testmod(diskcache_community.recipes)
    assert failures == 0


def test_tutorial():
    failures, _ = doctest.testfile('../docs/tutorial.rst')
    assert failures == 0
