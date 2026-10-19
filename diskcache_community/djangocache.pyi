# pyright: basic
# ruff: noqa
# mypy: ignore-errors
from _typeshed import Incomplete
from django.core.cache.backends.base import (  # pyright: ignore[reportMissingImports]
    BaseCache,
)

class DjangoCache(BaseCache):
    def __init__(self, directory, params) -> None: ...
    @property
    def directory(self): ...
    def cache(self, name): ...
    def deque(self, name, maxlen: Incomplete | None = None): ...
    def index(self, name): ...
    def add(
        self,
        key,
        value,
        timeout=...,
        version: Incomplete | None = None,
        read: bool = False,
        tag: Incomplete | None = None,
        retry: bool = True,
    ): ...
    def get(
        self,
        key,
        default: Incomplete | None = None,
        version: Incomplete | None = None,
        read: bool = False,
        expire_time: bool = False,
        tag: bool = False,
        retry: bool = False,
        store_time: bool = False,
    ): ...
    def read(self, key, version: Incomplete | None = None): ...
    def set(
        self,
        key,
        value,
        timeout=...,
        version: Incomplete | None = None,
        read: bool = False,
        tag: Incomplete | None = None,
        retry: bool = True,
    ): ...
    def touch(
        self,
        key,
        timeout=...,
        version: Incomplete | None = None,
        retry: bool = True,
    ): ...
    def pop(
        self,
        key,
        default: Incomplete | None = None,
        version: Incomplete | None = None,
        expire_time: bool = False,
        tag: bool = False,
        retry: bool = True,
    ): ...
    def delete(
        self, key, version: Incomplete | None = None, retry: bool = True
    ): ...
    def incr(
        self,
        key,
        delta: int = 1,
        version: Incomplete | None = None,
        default: Incomplete | None = None,
        retry: bool = True,
    ): ...
    def decr(
        self,
        key,
        delta: int = 1,
        version: Incomplete | None = None,
        default: Incomplete | None = None,
        retry: bool = True,
    ): ...
    def has_key(self, key, version: Incomplete | None = None): ...
    def expire(self): ...
    def stats(self, enable: bool = True, reset: bool = False): ...
    def create_tag_index(self) -> None: ...
    def drop_tag_index(self) -> None: ...
    def evict(self, tag): ...
    def cull(self): ...
    def clear(self): ...
    def close(self, **kwargs) -> None: ...
    def get_backend_timeout(self, timeout=...): ...
    def memoize(
        self,
        name: Incomplete | None = None,
        timeout=...,
        version: Incomplete | None = None,
        typed: bool = False,
        tag: Incomplete | None = None,
        ignore=(),
    ): ...
