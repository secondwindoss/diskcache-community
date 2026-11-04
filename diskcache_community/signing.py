"""Signed entries for SafeDisk.with_signing().

A signing disk stores every value it pickles as a full pickle with an
HMAC-SHA256 tag and checks the tag before it unpickles anything. The tag
covers the cache key the row is stored under, so a value moved to another key
is refused, and a pickled row without a tag is refused too.

The row's mode stays MODE_PICKLE. Its value column starts with a 45-byte
prefix, the magic, a version, the key id and the tag, followed by the pickle
for an inline row; a file row keeps the prefix alone in the value column and
the pickle alone in its value file. The magic starts with ``0xff``, which is
not a pickle opcode, so every reader that unpickles the value column, from
diskcache 5.6.3 on, raises before reading anything else.
"""

import errno
import hashlib
import hmac
import inspect
import os
import os.path as op
import pickle
import secrets
import sqlite3
import stat
import struct
import sys
import time

from .core import (
    MODE_PICKLE,
    UNKNOWN,
    SafeDisk,
    _makedirs_private,
    native_filename,
)

ENV_KEY_FILE = 'DISKCACHE_SIGNING_KEY_FILE'

MAGIC = b'\xffDCS'
VERSION = 1
HEADER_SIZE = 13  # magic, version and key id
PREFIX_SIZE = HEADER_SIZE + 32  # header and tag
MIN_KEY_SIZE = 32

_MAX_KEY_FILE_SIZE = 4096
_CHUNK_SIZE = 2**20
_KEY_ID_LABEL = b'diskcache-community key id'
_MAC_LABEL = b'diskcache-community signed entry v1'
_INT64 = 2**63

NUMPY_REFUSED = (
    'with_signing() and with_numpy() do not combine: a signing disk pickles'
    ' every value in full, numpy arrays included'
)


def _key_too_short(size):
    """Raise ValueError for a key of `size` bytes.

    Only the size is passed, so a traceback that records the locals of the
    raising frame holds no key bytes.

    """
    raise ValueError(
        'a signing key must be at least %d bytes, not %d'
        % (MIN_KEY_SIZE, size)
    )


class _Key:
    """A signing key, reduced to its key id and a keyed HMAC object.

    The key's bytes are not kept. The derived MAC key lives in the HMAC
    object's C state, which ``vars()``, ``repr()`` and pickle do not show. That
    is hygiene against accidental exposure, not protection: anything that can
    read the process's memory can reach it.

    """

    __slots__ = ('key_id', '_hmac')

    def __init__(self, key):
        self.key_id = hmac.new(key, _KEY_ID_LABEL, hashlib.sha256).digest()[:8]
        self._hmac = hmac.new(
            hmac.new(key, _MAC_LABEL, hashlib.sha256).digest(),
            digestmod=hashlib.sha256,
        )

    def __repr__(self):
        return '<signing key %s>' % self.key_id.hex()

    def __reduce__(self):
        raise TypeError('a signing key cannot be pickled')

    def mac(self):
        """Return a fresh HMAC object keyed with the derived MAC key."""
        return self._hmac.copy()


class KeyFile:
    """Key source of a signing disk: a key file, or the default one."""

    __slots__ = ('path',)

    def __init__(self, path):
        self.path = path

    def __repr__(self):
        if self.path is None:
            return '<default key file>'
        return '<key file %r>' % (self.path,)

    def __reduce__(self):
        return KeyFile, (self.path,)

    def load(self, directory):
        """Return the key and the key file's real path for a cache in
        `directory`, creating the file if it is missing."""
        path = default_key_file() if self.path is None else self.path
        return load_key_file(path, directory)


class InMemoryKey:
    """Key source of a signing disk: a key held only in this process."""

    __slots__ = ('key',)

    def __init__(self, key):
        self.key = _Key(key)

    def __repr__(self):
        return '<in-memory key %s>' % self.key.key_id.hex()

    def __reduce__(self):
        raise TypeError(
            'a disk with an in-memory signing key cannot be pickled; use'
            ' key_file= to share the key with other processes'
        )

    def load(self, directory):
        """Return the key; it has no file."""
        # pylint: disable=unused-argument
        return self.key, None


def source(cls, key_file, key):
    """Return the key source of `cls`.with_signing(), or raise."""
    if cls.safe_numpy:
        raise TypeError(NUMPY_REFUSED)
    check_fetch(cls)

    if key is not None:
        if key_file is not None:
            raise TypeError('with_signing takes key_file or key, not both')
        if not isinstance(key, bytes):
            raise TypeError('key must be bytes, not %s' % type(key).__name__)
        if len(key) < MIN_KEY_SIZE:
            _key_too_short(len(key))
        return InMemoryKey(key)

    if key_file is None:
        return KeyFile(None)
    return KeyFile(op.abspath(op.expanduser(os.fsdecode(key_file))))


def check_fetch(cls):
    """Raise TypeError unless the `fetch` of `cls` accepts ``key=``."""
    method = cls.fetch
    if method is SafeDisk.fetch:
        return

    try:
        parameters = inspect.signature(method).parameters
    except (TypeError, ValueError):
        parameters = {}

    if 'key' in parameters or any(
        parameter.kind is parameter.VAR_KEYWORD
        for parameter in parameters.values()
    ):
        return

    raise TypeError(
        '%s.fetch does not accept the keyword argument key, which a signing'
        ' disk is passed' % cls.__qualname__
    )


def default_key_file():
    """Return the path of the default key file.

    It is ``$DISKCACHE_SIGNING_KEY_FILE`` when that is set, and otherwise a
    file named ``signing.key`` in a folder ``diskcache-community`` of the
    user's local data directory.

    """
    path = os.environ.get(ENV_KEY_FILE)
    if path:
        return op.abspath(op.expanduser(path))

    base = data_directory(os.environ, sys.platform, op.expanduser('~'))
    if base is None:
        raise OSError(
            errno.ENOENT,
            'there is no home directory for the default signing key file;'
            ' set %s, or pass key_file= or key= to with_signing()'
            % ENV_KEY_FILE,
        )
    return op.join(base, 'diskcache-community', 'signing.key')


def data_directory(environ, platform, home):
    """Return the user's local data directory, or None if there is none."""
    if platform == 'win32':
        base = environ.get('LOCALAPPDATA')
    elif platform == 'darwin':
        base = op.join(home, 'Library', 'Application Support')
    else:
        base = environ.get('XDG_DATA_HOME')
        if not base or not op.isabs(base):
            base = op.join(home, '.local', 'share')
    if not base or not op.isabs(base):
        return None
    return base


def load_key_file(path, directory):
    """Return the key in the file `path` and the file's real path.

    The file is created with a new random key if it is missing. It is refused
    when it lies inside the cache `directory`, and on POSIX when its
    permissions let other users replace or read it.

    """
    _refuse_inside(path, directory)

    try:
        reader = open(path, 'rb')  # pylint: disable=consider-using-with
    except FileNotFoundError:
        _create_key_file(path)
        reader = open(path, 'rb')  # pylint: disable=consider-using-with

    with reader:
        real_path = op.realpath(path)
        check_permissions(os.fstat(reader.fileno()), real_path)
        return _Key(_read_key(reader)), real_path


def _create_key_file(path):
    """Create the key file `path` with a new key, unless it now exists.

    The key is written to a temporary file in the same folder and hard-linked
    into place, so a process that starts at the same time ends up with the
    same key and never reads a half-written file.

    """
    folder = op.dirname(path)
    try:
        _makedirs_private(folder)
        temporary = op.join(folder, '.signing-%s.tmp' % secrets.token_hex(8))
        _write_new(temporary, secrets.token_hex(32).encode('ascii') + b'\n')
    except OSError as error:
        raise OSError(
            error.errno,
            'cannot create the signing key file %r (%s); set %s, or pass'
            ' key_file= or key= to with_signing()'
            % (path, error.strerror, ENV_KEY_FILE),
        ) from error

    try:
        os.link(temporary, path)
    except FileExistsError:
        pass
    except OSError:
        # A file system without hard links: create the file in place, which
        # a concurrent reader may see before the key is written.
        try:
            with open(temporary, 'rb') as reader:
                _write_new(path, reader.read())
        except FileExistsError:
            pass
    finally:
        os.remove(temporary)


def _write_new(path, data):
    """Write `data` to the new file `path` with mode ``0o600``."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0)
    descriptor = os.open(path, flags, 0o600)
    with open(descriptor, 'wb') as writer:
        writer.write(data)
        writer.flush()
        os.fsync(writer.fileno())


def _read_key(reader):
    """Return the key in the open key file `reader`."""
    for _ in range(10):
        reader.seek(0)
        data = reader.read(_MAX_KEY_FILE_SIZE + 1)
        if data.endswith(b'\r\n'):
            data = data[:-2]
        elif data.endswith(b'\n'):
            data = data[:-1]
        if len(data) >= MIN_KEY_SIZE:
            break
        # The file may be in the middle of being created in place.
        time.sleep(0.01)

    size = len(data)
    if size > _MAX_KEY_FILE_SIZE:
        del data
        raise ValueError(
            'a signing key file must be at most %d bytes' % _MAX_KEY_FILE_SIZE
        )
    if size < MIN_KEY_SIZE:
        del data
        _key_too_short(size)
    return data


def check_permissions(status, path):
    """Raise ValueError unless the key file `path`, whose ``os.stat`` result
    is `status`, is safe from other users. Windows is not checked."""
    if os.name == 'nt':
        return

    mode = status.st_mode
    uid = os.geteuid()

    if not stat.S_ISREG(mode):
        raise ValueError('the signing key file %r is not a file' % path)
    if mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise ValueError(
            'the signing key file %r can be written by other users' % path
        )
    if status.st_uid not in (uid, 0):
        raise ValueError(
            'the signing key file %r belongs to uid %d, not to this user'
            ' (uid %d) or root' % (path, status.st_uid, uid)
        )
    # A file owned by root that others can read is accepted, since container
    # platforms mount secrets that way.
    if status.st_uid == uid != 0 and mode & (stat.S_IRGRP | stat.S_IROTH):
        raise ValueError(
            'the signing key file %r can be read by other users; run'
            ' chmod 600 on it' % path
        )

    folder = os.stat(op.dirname(path)).st_mode
    if folder & (stat.S_IWGRP | stat.S_IWOTH) and not folder & stat.S_ISVTX:
        raise ValueError(
            'the folder of the signing key file %r can be written by other'
            ' users' % path
        )


def _inside(path, directory):
    """Return True when the real path `path` lies inside `directory`.

    Folders are compared by device and inode, which also matches spellings
    that ``realpath`` leaves alone, such as another letter case on a
    case-insensitive volume. A file system that reports inode 0 is compared
    by normalized real path instead. Folders that do not exist yet are
    skipped.

    """
    target = os.stat(directory)
    real_directory = op.normcase(op.realpath(directory))
    folder = op.dirname(path)

    while True:
        try:
            status = os.stat(folder)
        except FileNotFoundError:
            status = None

        if status is None:
            pass
        elif target.st_ino and status.st_ino:
            if (status.st_dev, status.st_ino) == (
                target.st_dev,
                target.st_ino,
            ):
                return True
        elif op.normcase(folder) == real_directory:
            return True

        parent = op.dirname(folder)
        if parent == folder:
            return False
        folder = parent


def check_key_location(disk, directory):
    """Raise ValueError if the key file `disk` reads is inside `directory`.

    FanoutCache calls this for its own directory before it creates any
    shard: each shard's disk sees only the shard's directory, and would
    create a missing key file in the fanout directory before a later check
    could refuse it. A missing `directory` is skipped.

    """
    source = getattr(disk, 'signing', None)
    if not isinstance(source, KeyFile) or not op.isdir(directory):
        return
    path = default_key_file() if source.path is None else source.path
    _refuse_inside(path, directory)


def _refuse_inside(path, directory):
    if _inside(op.realpath(path), directory):
        raise ValueError(
            'the signing key file %r is inside the cache directory %r'
            % (path, directory)
        )


def stored_raw(value):
    """Return True when Disk.store stores `value` without pickling it."""
    # pylint: disable=unidiomatic-typecheck,comparison-with-itself
    kind = type(value)
    if kind is bytes or kind is str:
        return True
    if kind is int:
        return -_INT64 <= value < _INT64
    return kind is float and value == value


def _key_bytes(db_key, raw):
    """Return the canonical encoding of the stored key `db_key`.

    SQLite matches an integer and a real of equal value, so an integral float
    in the 64-bit range is encoded as the integer, and ``1.0`` and ``1``,
    ``0.0`` and ``-0.0``, encode alike. Values of different storage classes
    never match, so their type bytes keep them apart.

    """
    # pylint: disable=unidiomatic-typecheck
    if not raw:
        return b'p' + bytes(db_key)
    if db_key is None:
        raise pickle.UnpicklingError(
            'SafeDisk.with_signing() refuses a row whose key is NULL'
        )

    kind = type(db_key)
    if kind is float:
        if db_key.is_integer() and -_INT64 <= db_key < _INT64:
            return b'i%d' % int(db_key)
        return b'f' + struct.pack('!d', db_key)
    if kind is int:
        return b'i%d' % db_key
    if kind is str:
        return b's' + db_key.encode('utf-8', 'surrogatepass')
    return b'b' + bytes(db_key)


def _finish(mac, key):
    """Add the cache `key`, a ``(db_key, raw)`` pair, and return the tag."""
    encoded = _key_bytes(*key)
    mac.update(encoded)
    mac.update(struct.pack('>Q', len(encoded)))
    return mac.digest()


class _Pending:  # pylint: disable=too-few-public-methods
    """The value column of a signed row, waiting for the key it is stored
    under. The header and pickle are already hashed."""

    __slots__ = ('_header', '_mac', '_data')

    def __init__(self, header, mac, data):
        self._header = header
        self._mac = mac
        self._data = data

    def sign(self, key):
        """Return the value column for the cache `key`."""
        prefix = self._header + _finish(self._mac.copy(), key)
        if self._data is None:
            return sqlite3.Binary(prefix)
        return sqlite3.Binary(prefix + self._data)


def store(disk, value, key):
    """Return the Cache table fields of `value`, pickled and signed.

    Without a `key`, as from ``Cache.push``, the value column is left pending
    and :func:`finish` signs it once the key is chosen. The header and the
    pickle are hashed here in either case, so only the key is added later.

    """
    try:
        data = pickle.dumps(value, protocol=disk.pickle_protocol)
    except (pickle.PicklingError, AttributeError) as error:
        raise TypeError(
            'SafeDisk cannot store value: %s' % (error,)
        ) from error

    signing_key = disk._signing_key  # pylint: disable=protected-access
    header = MAGIC + bytes((VERSION,)) + signing_key.key_id
    mac = signing_key.mac()
    mac.update(header)
    mac.update(data)

    if PREFIX_SIZE + len(data) < disk.min_file_size:
        size, filename = 0, None
    else:
        filename, full_path = disk.filename(key, value)
        disk._write(full_path, data, 'xb')  # pylint: disable=protected-access
        size, data = len(data), None

    pending = _Pending(header, mac, data)
    if key is UNKNOWN:
        return size, MODE_PICKLE, filename, pending
    return size, MODE_PICKLE, filename, pending.sign(disk.put(key))


def finish(db_value, key):
    """Return the value column `db_value` signed for `key` if it is pending."""
    if isinstance(db_value, _Pending):
        return db_value.sign(key)
    return db_value


def _refuse(message):
    raise pickle.UnpicklingError('SafeDisk.with_signing() refuses ' + message)


def fetch(disk, filename, value, key):
    """Return the value of the signed row with columns `filename` and
    `value`, stored under `key`, after checking its tag."""
    view = None if value is None else memoryview(value)

    if view is None or view[:4] != MAGIC:
        _refuse('an unsigned pickled value')
    if (filename is None) == (len(view) == PREFIX_SIZE) or len(view) < (
        PREFIX_SIZE
    ):
        _refuse('a signed row of the wrong shape')
    if view[4] != VERSION:
        _refuse('a signed row of unknown version %d' % view[4])

    signing_key = disk._signing_key  # pylint: disable=protected-access
    key_id = bytes(view[5:HEADER_SIZE])
    if key_id != signing_key.key_id:
        _refuse('a row signed with another key (key id %s)' % key_id.hex())
    if key is None:
        _refuse('to read a signed row without its cache key')

    header = bytes(view[:HEADER_SIZE])
    tag = bytes(view[HEADER_SIZE:PREFIX_SIZE])

    if filename is None:
        data = view[PREFIX_SIZE:]
    else:
        full_path = op.join(
            disk._directory,  # pylint: disable=protected-access
            native_filename(filename),
        )
        with open(full_path, 'rb') as reader:
            # The streaming pass needs no memory for a planted large file,
            # and the second read is capped at what the first pass hashed.
            mac = signing_key.mac()
            mac.update(header)
            size = 0
            for chunk in iter(lambda: reader.read(_CHUNK_SIZE), b''):
                mac.update(chunk)
                size += len(chunk)
            _check_tag(_finish(mac, key), tag)
            reader.seek(0)
            data = reader.read(size)

    mac = signing_key.mac()
    mac.update(header)
    mac.update(data)
    _check_tag(_finish(mac, key), tag)
    return pickle.loads(data)


def _check_tag(expected, tag):
    if not hmac.compare_digest(expected, tag):
        _refuse(
            'a signed row whose tag does not match: the row was changed, or'
            ' moved from another key'
        )


def refuse_signed(value):
    """Raise a clear UnpicklingError if `value` is a signed row's value
    column; a disk without signing calls this when its unpickler fails."""
    if value is not None and bytes(value[:4]) == MAGIC:
        raise pickle.UnpicklingError(
            'this row is a signed entry; read it with SafeDisk.with_signing()'
            ' and the key that wrote it'
        )
