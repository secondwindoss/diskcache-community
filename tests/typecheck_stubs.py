"""Calls that must type-check against the shipped stubs.

``tox -e mypy`` checks this file; pytest does not collect it.
"""

import diskcache_community as dc


def incr_without_default(cache: dc.Cache, key: str) -> int:
    return cache.incr(key, 1, default=None)


def decr_without_default(cache: dc.Cache, key: str) -> int:
    return cache.decr(key, 1, default=None)


def fanout_incr_without_default(cache: dc.FanoutCache, key: str) -> int:
    return cache.incr(key, 1, default=None)


def fanout_decr_without_default(cache: dc.FanoutCache, key: str) -> int:
    return cache.decr(key, 1, default=None)


def with_types_one_module() -> type[dc.SafeDisk]:
    return dc.SafeDisk.with_types(modules='myapp.models')


def with_types_module_list() -> type[dc.SafeDisk]:
    return dc.SafeDisk.with_types(int, modules=['myapp.models', 'myapp.api'])


def with_signing_default_key() -> type[dc.SafeDisk]:
    return dc.SafeDisk.with_signing().with_options(on_error='miss')


def with_signing_key_file(path: str) -> dc.Cache:
    return dc.Cache(disk=dc.SafeDisk.with_signing(path))


def with_signing_in_memory_key(key: bytes) -> type[dc.SafeDisk]:
    return dc.SafeDisk.with_types(int).with_signing(key=key)
