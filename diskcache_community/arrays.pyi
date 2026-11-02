from typing import IO, Any

from diskcache_community.core import SafeDisk, SafeUnpickler

def unpickler(disk: SafeDisk, file: IO[bytes]) -> SafeUnpickler: ...
def store(
    disk: SafeDisk, numpy: Any, value: Any, key: Any
) -> tuple[int, int, str | None, Any]: ...
