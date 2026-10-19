import pickle
import sqlite3
from typing import (
    IO,
    Any,
    BinaryIO,
    Callable,
    Final,
    Generator,
    Generic,
    Literal,
    overload,
)

from _typeshed import StrOrBytesPath
from typing_extensions import Self, TypeVar, Unpack

from ._types import (
    BaseCache,
    DbName,
    DefaultMetadata,
    DefaultSettings,
    EnovalType,
    EvictionPolicyItem,
    EvictionPolicyKey,
    ExpireTime,
    Ignore,
    InitSettings,
    KeyValuePair,
    ModeBinary,
    ModeLiteral,
    ModeNone,
    ModePickle,
    ModeRaw,
    ModeText,
    NullablePair,
    ServerSide,
    Tag,
    UnknownType,
)

_T = TypeVar('_T')
_BoundStrT = TypeVar('_BoundStrT', bound=str)
_PutT1 = TypeVar('_PutT1', bound=str | int | float)
_PutT2 = TypeVar('_PutT2', bound=int | float)

def full_name(func: Callable[..., Any]) -> str: ...
def native_filename(filename: str) -> str: ...

class Constant(tuple[_BoundStrT], Generic[_BoundStrT]):  # noqa: SLOT001
    def __new__(cls, name: _BoundStrT) -> Self: ...

DBNAME: Final[DbName]
ENOVAL: Final[Constant[EnovalType]]
UNKNOWN: Final[Constant[UnknownType]]
MODE_NONE: Final[ModeNone]
MODE_RAW: Final[ModeRaw]
MODE_BINARY: Final[ModeBinary]
MODE_TEXT: Final[ModeText]
MODE_PICKLE: Final[ModePickle]
DEFAULT_SETTINGS: Final[DefaultSettings]
METADATA: Final[DefaultMetadata]
EVICTION_POLICY: Final[dict[EvictionPolicyKey, EvictionPolicyItem]]
SETTINGS_TRIGGERS: Final[tuple[tuple[str, str], ...]]
SAFE_TYPES: Final[frozenset[type]]
SAFE_PICKLE_NAMES: Final[dict[str, frozenset[str]]]
UNSAFE_MODULES: Final[tuple[str, ...]]
ENV_DISK: Final[str]
ENV_SAFE_TYPES: Final[str]
ENV_SAFE_MODULES: Final[str]

class Disk:
    min_file_size: int
    pickle_protocol: int
    on_error: Literal['raise', 'miss']
    @classmethod
    def with_options(
        cls, *, on_error: Literal['raise', 'miss']
    ) -> type[Self]: ...
    def __init__(
        self,
        directory: StrOrBytesPath,
        min_file_size: int = ...,
        pickle_protocol: int = ...,
    ) -> None: ...
    def hash(self, key: Any) -> int: ...
    @overload
    def put(self, key: bytes) -> tuple[sqlite3.Binary, Literal[True]]: ...
    @overload
    def put(self, key: _PutT1) -> tuple[_PutT1, Literal[True]]: ...
    @overload
    def put(self, key: Any) -> tuple[sqlite3.Binary, Literal[False]]: ...
    @overload
    def get(self, key: sqlite3.Binary, raw: Literal[True]) -> bytes: ...
    @overload
    def get(self, key: _T, raw: Literal[True]) -> bytes | _T: ...
    @overload
    def get(self, key: Any, raw: Literal[False]) -> Any: ...
    @overload
    def get(self, key: Any, raw: bool) -> Any: ...
    @overload
    def store(
        self, value: _PutT2, read: bool, key: Any = ...
    ) -> tuple[Literal[0], ModeRaw, None, _PutT2]: ...
    @overload
    def store(
        self, value: bytes, read: bool, key: Any = ...
    ) -> (
        tuple[Literal[0], ModeRaw, None, sqlite3.Binary]
        | tuple[int, ModeBinary, str, None]
    ): ...
    @overload
    def store(
        self, value: str, read: bool, key: Any = ...
    ) -> tuple[Literal[0], ModeRaw, None, str] | tuple[
        int, ModeText, str, None
    ]: ...
    @overload
    def store(
        self, value: Any, read: Literal[True], key: Any = ...
    ) -> tuple[int, ModeBinary, str, None]: ...
    @overload
    def store(
        self, value: Any, read: bool, key: Any = ...
    ) -> (
        tuple[Literal[0], ModePickle, None, sqlite3.Binary]
        | tuple[int, ModePickle, str, None]
    ): ...
    @overload
    def fetch(
        self, mode: ModeRaw, filename: str, value: sqlite3.Binary, read: bool
    ) -> bytes: ...
    @overload
    def fetch(
        self, mode: ModeRaw, filename: str, value: _T, read: bool
    ) -> _T: ...
    @overload
    def fetch(
        self, mode: ModeBinary, filename: str, value: Any, read: Literal[True]
    ) -> BinaryIO: ...
    @overload
    def fetch(
        self, mode: ModeBinary, filename: str, value: Any, read: Literal[False]
    ) -> BinaryIO: ...
    @overload
    def fetch(
        self, mode: ModeBinary, filename: str, value: Any, read: bool
    ) -> BinaryIO | bytes: ...
    @overload
    def fetch(
        self, mode: ModeText, filename: str, value: Any, read: bool
    ) -> str: ...
    @overload
    def fetch(
        self, mode: ModePickle, filename: str, value: Any, read: bool
    ) -> Any: ...
    @overload
    def fetch(
        self, mode: ModeLiteral, filename: str, value: Any, read: bool
    ) -> Any: ...
    def filename(
        self, key: Any = ..., value: Any = ...
    ) -> tuple[str, str]: ...
    def remove(self, file_path: StrOrBytesPath) -> None: ...

class JSONDisk(Disk):
    compress_level: int
    def __init__(
        self,
        directory: StrOrBytesPath,
        compress_level: int = ...,
        *,
        # Disk init args
        min_file_size: int = ...,
        pickle_protocol: int = ...,
    ) -> None: ...

class SafeUnpickler(pickle.Unpickler):
    def __init__(
        self,
        file: IO[bytes],
        names: dict[str, frozenset[str]] | None = ...,
        classes: tuple[type, ...] = ...,
        modules: tuple[str, ...] = ...,
    ) -> None: ...
    def find_class(self, module: str, name: str) -> Any: ...

class SafeDisk(Disk):
    safe_types: frozenset[type]
    safe_modules: tuple[str, ...]
    @classmethod
    def with_types(
        cls, *types: type, modules: tuple[str, ...] = ...
    ) -> type[Self]: ...

def configure(disk: type[Disk] | None) -> None: ...
def default_disk() -> type[Disk]: ...

class Timeout(Exception): ...  # noqa: N818
class ReadOnlyError(sqlite3.OperationalError): ...
class UnknownFileWarning(UserWarning): ...
class EmptyDirWarning(UserWarning): ...

def args_to_key(
    base: tuple[Any, ...],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    typed: bool,
    ignore: Ignore,
) -> tuple[Any, ...]: ...
def resolve_ignore(func: Callable[..., Any], ignore: Ignore) -> Ignore: ...

class Cache(BaseCache):
    @overload
    def __init__(
        self,
        directory: StrOrBytesPath | None = ...,
        timeout: int = ...,
        disk: type[Disk] | None = ...,
        *,
        read_only: bool = ...,
        **settings: Unpack[InitSettings],
    ) -> None: ...
    @overload
    def __init__(
        self,
        directory: StrOrBytesPath | None = ...,
        timeout: int = ...,
        disk: type[Disk] | None = ...,
        *,
        read_only: bool = ...,
        # FIXME
        # https://peps.python.org/pep-0728/
        # diskcache allow "disk_*" args
        **settings: Any,
    ) -> None: ...
    @property
    def read_only(self) -> bool: ...
    @property
    def _con(self) -> sqlite3.Connection: ...
    @property
    def _sql(self) -> Callable[..., sqlite3.Cursor]: ...
    def __delitem__(self, key: Any, retry: bool = ...) -> Literal[True]: ...
    @overload
    def reset(self, key: str, value: _T, update: bool = ...) -> _T: ...
    @overload
    def reset(self, key: str, value: Any = ..., update: bool = ...) -> Any: ...
    def read(self, key: Any, retry: bool = ...) -> Any: ...
    @overload
    def push(
        self,
        value: Any,
        prefix: None = ...,
        side: ServerSide = ...,
        expire: ExpireTime = ...,
        read: bool = ...,
        tag: Tag = ...,
        retry: bool = ...,
    ) -> int: ...
    @overload
    def push(
        self,
        value: Any,
        prefix: str = ...,
        side: ServerSide = ...,
        expire: ExpireTime = ...,
        read: bool = ...,
        tag: Tag = ...,
        retry: bool = ...,
    ) -> str: ...
    @overload
    def push(
        self,
        value: Any,
        prefix: str | None = ...,
        side: ServerSide = ...,
        expire: ExpireTime = ...,
        read: bool = ...,
        tag: Tag = ...,
        retry: bool = ...,
    ) -> str | int: ...
    def pull(  # noqa: PLR0913
        self,
        prefix: str | None = ...,
        default: Any = ...,
        side: ServerSide = ...,
        expire_time: bool = ...,
        tag: bool = ...,
        retry: bool = ...,
    ) -> (
        NullablePair[Any]
        | tuple[NullablePair[Any], Tag]
        | tuple[NullablePair[Any], ExpireTime]
        | tuple[NullablePair[Any], ExpireTime, Tag]
    ): ...
    def peek(  # noqa: PLR0913
        self,
        prefix: str | None = ...,
        default: Any = ...,
        side: ServerSide = ...,
        expire_time: bool = ...,
        tag: bool = ...,
        retry: bool = ...,
    ) -> (
        NullablePair[Any]
        | tuple[NullablePair[Any], Tag]
        | tuple[NullablePair[Any], ExpireTime]
        | tuple[NullablePair[Any], ExpireTime, Tag]
    ): ...
    def peekitem(
        self,
        last: bool = ...,
        expire_time: bool = ...,
        tag: bool = ...,
        retry: bool = ...,
    ) -> (
        KeyValuePair[Any]
        | tuple[KeyValuePair[Any], Tag]
        | tuple[KeyValuePair[Any], ExpireTime]
        | tuple[KeyValuePair[Any], ExpireTime, Tag]
    ): ...
    def expire(self, now: ExpireTime = ..., retry: bool = ...) -> int: ...
    def iterkeys(
        self, reverse: bool = ..., tag: Tag | Constant[EnovalType] = ...
    ) -> Generator[Any, None, None]: ...
    def __getstate__(self) -> tuple[str, int, type[Disk]]: ...
    def __setstate__(self, state: tuple[str, int, type[Disk]]) -> None: ...
