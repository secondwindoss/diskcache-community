from typing import Any, overload

from _typeshed import StrOrBytesPath
from typing_extensions import Unpack

from diskcache_community.core import DEFAULT_SETTINGS as DEFAULT_SETTINGS
from diskcache_community.core import ENOVAL as ENOVAL
from diskcache_community.core import Cache as Cache
from diskcache_community.core import Disk as Disk
from diskcache_community.core import Timeout as Timeout
from diskcache_community.persistent import Deque as Deque
from diskcache_community.persistent import Index as Index

from ._types import BaseCache, InitSettings

class FanoutCache(BaseCache):
    @overload
    def __init__(
        self,
        directory: StrOrBytesPath | None = ...,
        shards: int = ...,
        timeout: float = ...,
        disk: type[Disk] | None = ...,
        **settings: Unpack[InitSettings],
    ) -> None: ...
    @overload
    def __init__(
        self,
        directory: StrOrBytesPath | None = ...,
        shards: int = ...,
        timeout: float = ...,
        disk: type[Disk] | None = ...,
        # FIXME
        # https://peps.python.org/pep-0728/
        # diskcache allow "disk_*" args
        **settings: Any,
    ) -> None: ...
    def __getattr__(self, name: str) -> Any: ...
    def read(self, key: Any) -> Any: ...
    def expire(self, retry: bool = ...) -> int: ...
    @overload
    def cache(
        self,
        name: str,
        timeout: int = ...,
        disk: type[Disk] | None = ...,
        **settings: Unpack[InitSettings],
    ) -> Cache: ...
    @overload
    def cache(
        self,
        name: str,
        timeout: int = ...,
        disk: type[Disk] | None = ...,
        # FIXME
        # https://peps.python.org/pep-0728/
        # diskcache allow "disk_*" args
        **settings: Any,
    ) -> Cache: ...
    def deque(
        self,
        name: str,
        maxlen: int | None = ...,
        disk: type[Disk] | None = ...,
    ) -> Deque[Any]: ...
    def index(
        self, name: str, disk: type[Disk] | None = ...
    ) -> Index[Any, Any]: ...
    def __delitem__(self, key: Any) -> None: ...
    def reset(self, key: str, value: Any = ...) -> Any: ...
