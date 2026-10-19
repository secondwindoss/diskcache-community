from typing import Any, Callable, Protocol

from typing_extensions import ParamSpec, TypeVar, override

from ._types import BaseCache, ExpireTime, Ignore, Tag

_T = TypeVar('_T')
_P = ParamSpec('_P')

class Averager:
    def __init__(
        self,
        cache: BaseCache,
        key: Any,
        expire: ExpireTime = ...,
        tag: Tag = ...,
    ) -> None: ...
    def add(self, value: float) -> None: ...
    def get(self) -> float | None: ...
    def pop(self) -> float | None: ...

class _Lock(Protocol):
    def acquire(self) -> Any: ...
    def release(self) -> Any: ...
    def __enter__(self) -> Any: ...
    def __exit__(self, *exc_info: object) -> Any: ...

class Lock(_Lock):
    def __init__(
        self,
        cache: BaseCache,
        key: Any,
        expire: ExpireTime = ...,
        tag: Tag = ...,
    ) -> None: ...
    def locked(self) -> bool: ...
    @override
    def acquire(self) -> None: ...
    @override
    def release(self) -> None: ...
    @override
    def __enter__(self) -> None: ...
    @override
    def __exit__(self, *exc_info: object) -> None: ...

class RLock(_Lock):
    def __init__(
        self,
        cache: BaseCache,
        key: Any,
        expire: ExpireTime = ...,
        tag: Tag = ...,
    ) -> None: ...
    @override
    def acquire(self) -> None: ...
    @override
    def release(self) -> None: ...
    @override
    def __enter__(self) -> None: ...
    @override
    def __exit__(self, *exc_info: object) -> None: ...

class BoundedSemaphore:
    def __init__(
        self,
        cache: BaseCache,
        key: Any,
        value: int = ...,
        expire: ExpireTime = ...,
        tag: Tag = ...,
    ) -> None: ...
    def acquire(self) -> None: ...
    def release(self) -> None: ...
    def __enter__(self) -> None: ...
    def __exit__(self, *exc_info: object) -> None: ...

def throttle(  # noqa: PLR0913
    cache: BaseCache,
    count: int,
    seconds: float,
    name: str | None = ...,
    expire: ExpireTime = ...,
    tag: Tag = ...,
    time_func: Callable[[], float] = ...,
    sleep_func: Callable[[float], Any] = ...,
) -> Callable[[Callable[_P, _T]], Callable[_P, _T]]: ...
def barrier(
    cache: BaseCache,
    lock_factory: Callable[[BaseCache, Any, ExpireTime, Tag], _Lock],
    name: str | None = ...,
    expire: ExpireTime = ...,
    tag: Tag = ...,
) -> Callable[[Callable[_P, _T]], Callable[_P, _T]]: ...
def memoize_stampede(  # noqa: PLR0913
    cache: BaseCache,
    expire: float,
    name: str | None = ...,
    typed: bool = ...,
    tag: Tag = ...,
    beta: float = ...,
    ignore: Ignore = ...,
) -> Callable[[Callable[_P, _T]], Callable[_P, _T]]: ...
