"""Disk that stores numpy arrays without pickling them."""

import io
import math
import pickle
import pickletools
import re
import sqlite3
import sys
import warnings

from .core import (
    SAFE_PICKLE_NAMES,
    Disk,
    SafeUnpickler,
    _in_modules,
    _pickle_globals,
    _ReaderMissing,
)

# Pickle protocol 5 is the first that stores a buffer in place, so that
# writing an array copies it once, into the row, and reading a file-backed
# entry needs no second copy of it.
_MIN_PROTOCOL = 5

# The numpy scalar types that are stored, by the name written to the row, with
# the Python type that ``item()`` gives for each and the reader insists on. The
# names do not vary by platform or numpy version, unlike the types' own names.
_SCALARS = {
    'bool': ('bool_', bool),
    'int8': ('int8', int),
    'int16': ('int16', int),
    'int32': ('int32', int),
    'int64': ('int64', int),
    'uint8': ('uint8', int),
    'uint16': ('uint16', int),
    'uint32': ('uint32', int),
    'uint64': ('uint64', int),
    'float16': ('float16', float),
    'float32': ('float32', float),
    'float64': ('float64', float),
    'complex64': ('complex64', complex),
    'complex128': ('complex128', complex),
    'str': ('str_', str),
    'bytes': ('bytes_', bytes),
}

# The names of datetime64 and timedelta64 scalars, as dtype.name gives them:
# the type, then an optional unit with an optional multiple. The value stored
# is the scalar's int64 count of units, NaT included.
_TIME_NAME = re.compile(
    r'(?:datetime64|timedelta64)'
    r'(?:\[(?:[1-9][0-9]{0,8})?(?:Y|M|W|D|h|m|s|ms|us|ns|ps|fs|as)\])?\Z'
)


def _import_numpy():
    # pylint: disable=import-error,import-outside-toplevel
    try:
        import numpy
    except ImportError as error:
        raise _ReaderMissing(
            'SafeDisk needs numpy to read this entry'
        ) from error
    return numpy


# Headers already parsed, by their bytes, and headers already written, by
# dtype, shape and order. The arrays in a cache mostly share a few of each,
# such as one embedding size, and numpy's header parser, which evaluates the
# header as a Python literal, took most of the time of reading an array. Only
# headers that parse and pass the format checks are kept, only short ones,
# and only for dtypes without fields, since a caller can rename the fields of
# the dtype an array was read with. The size of the data is checked against
# the header on every read. Each table is emptied when full.
_HEADERS_KEPT = 256
_HEADER_SIZE_KEPT = 256
_parsed_headers = {}
_written_headers = {}


def _keep(table, key, value):
    if len(table) >= _HEADERS_KEPT:
        table.clear()
    table[key] = value


def _parse_header(numpy, header):
    """Return shape, Fortran order and dtype from the ``.npy`` `header`.

    Raise UnpicklingError unless the header holds one array of a dtype
    without objects. Anything that goes wrong while parsing, including a
    MemoryError from the Python parser on a crafted header, which
    ``on_error='miss'`` would not treat as an unreadable entry, is reported
    as UnpicklingError.

    """
    # pylint: disable=broad-except,no-member
    try:
        reader = io.BytesIO(header)
        version = numpy.lib.format.read_magic(reader)
        if version == (1, 0):
            fields = numpy.lib.format.read_array_header_1_0(reader)
        elif version == (2, 0):
            fields = numpy.lib.format.read_array_header_2_0(reader)
        else:
            raise ValueError('unsupported .npy version %r' % (version,))
    except Exception as error:
        raise pickle.UnpicklingError(
            'SafeDisk refuses the array header'
        ) from error

    shape, fortran, dtype = fields
    count = math.prod(shape)

    # A zero-width dtype would let any shape match any amount of data.
    if (
        dtype.hasobject
        or reader.tell() != len(header)
        or (count and not dtype.itemsize)
    ):
        raise pickle.UnpicklingError('SafeDisk refuses the array header')

    return shape, fortran, dtype, count * dtype.itemsize


def _read_header(numpy, header, size):
    """Return shape, Fortran order and dtype from the ``.npy`` `header`.

    Raise UnpicklingError unless the header is consistent with `size` bytes
    of data. The sizes are checked because a forged shape must not decide
    what gets read.

    """
    fields = _parsed_headers.get(header)
    if fields is None:
        fields = _parse_header(numpy, header)
        if len(header) <= _HEADER_SIZE_KEPT and fields[2].names is None:
            _keep(_parsed_headers, header, fields)

    shape, fortran, dtype, nbytes = fields
    if nbytes != size:
        raise pickle.UnpicklingError('SafeDisk refuses the array header')

    return shape, fortran, dtype


def _pack_array(numpy, array):
    """Return the ``.npy`` header of `array` and a buffer of its data.

    The buffer is the array's own memory, so pickle copies it once, into
    the row, as a bytearray. An array that is not contiguous or not
    writable is copied first, since pickle stores a read-only buffer as
    bytes, which the reader refuses. The buffer is a flat view of bytes,
    since numpy exports no buffer for ``datetime64`` and ``timedelta64``
    data; the dtype is in the header.

    """
    # pylint: disable=no-member
    flags = array.flags
    if not (flags.writeable and (flags.c_contiguous or flags.f_contiguous)):
        array = array.copy(order='A')

    dtype = array.dtype
    key = (dtype, array.shape, not array.flags.c_contiguous)
    header = _written_headers.get(key)
    if header is None:
        header = _write_header(numpy, array)
        if len(header) <= _HEADER_SIZE_KEPT and dtype.names is None:
            _keep(_written_headers, key, header)

    data = array.reshape(-1, order='A').view(numpy.uint8)
    return header, pickle.PickleBuffer(data)


def _write_header(numpy, array):
    """Return the ``.npy`` header of `array`, or raise TypeError."""
    # pylint: disable=no-member
    buffer = io.BytesIO()
    try:
        with warnings.catch_warnings():
            # numpy warns about dtypes it would save as pickles or in a
            # format the reader refuses; both are refused below.
            warnings.simplefilter('ignore')
            # Version 1 holds every header the reader accepts: numpy refuses
            # a header over 10000 bytes, and version 1 holds 65535.
            fields = numpy.lib.format.header_data_from_array_1_0(array)
            numpy.lib.format.write_array_header_1_0(buffer, fields)
        header = buffer.getvalue()
        _read_header(numpy, header, array.nbytes)
    except (ValueError, pickle.UnpicklingError) as error:
        message = 'SafeDisk cannot store an array of dtype %s' % (array.dtype,)
        if array.dtype.hasobject:
            message += (
                '; arrays of objects are stored, but not arrays with object'
                ' fields, such as DataFrame.to_records() of a frame with text'
                ' columns, so store its columns instead'
            )
        raise TypeError(message) from error

    return header


def _unpack_array(header, data):
    """Return the array in the bytearray `data`, which it keeps as its data.

    A view takes no second copy of the array, and stays writable because
    `data` is. `header` and `data` may have been tampered with.

    """
    # pylint: disable=broad-except
    numpy = _import_numpy()
    shape, fortran, dtype = _read_header(numpy, header, len(data))

    try:
        if not math.prod(shape):
            return numpy.empty(shape, dtype)
        array = numpy.frombuffer(data, dtype)
        return array.reshape(shape, order='F' if fortran else 'C')
    except Exception as error:
        raise pickle.UnpicklingError(
            'SafeDisk refuses the array data'
        ) from error


def _scalar_name(scalar):
    """Return the name to store numpy `scalar` under, or raise TypeError."""
    dtype = scalar.dtype
    if dtype.kind in 'Mm':
        # The reader accepts only the units _TIME_NAME matches.
        if not _TIME_NAME.match(dtype.name):
            raise TypeError(
                'SafeDisk cannot store a scalar of type numpy.%s with the'
                ' unit of %s' % (type(scalar).__name__, dtype.name)
            )
        return dtype.name
    name = {'U': 'str', 'S': 'bytes'}.get(dtype.kind, dtype.name)
    if name not in _SCALARS:
        raise TypeError(
            'SafeDisk cannot store a scalar of type numpy.%s'
            % (type(scalar).__name__,)
        )
    return name


def _scalar_value(numpy, scalar):
    """Return the Python value to store numpy `scalar` as."""
    if scalar.dtype.kind in 'Mm':
        return int(scalar.view(numpy.int64))
    value = scalar.item()
    if isinstance(value, numpy.generic):
        raise TypeError(
            'SafeDisk cannot store a scalar of type numpy.%s'
            % (type(scalar).__name__,)
        )
    return value


def _unpack_scalar(name, value):
    """Return the numpy scalar `value` of type `name`, which may be forged.

    The value must be of the Python type the name is built from: numpy
    would otherwise build something else, such as ``bytes_(n)``, which is
    `n` zero bytes. A datetime64 or timedelta64 name must match _TIME_NAME
    and its value be an int64 count.

    """
    # pylint: disable=broad-except,unidiomatic-typecheck
    if type(name) is str and _TIME_NAME.match(name):
        if type(value) is not int or not -(2**63) <= value < 2**63:
            raise pickle.UnpicklingError('SafeDisk refuses a scalar')
        numpy = _import_numpy()
        # Every name _TIME_NAME matches builds; the guard is for numpy
        # versions that refuse some unit.
        try:
            count = numpy.array(value, dtype=numpy.int64)
            return count.view(numpy.dtype(name))[()]
        except Exception as error:  # pragma: no cover
            raise pickle.UnpicklingError(
                'SafeDisk refuses a scalar'
            ) from error

    entry = _SCALARS.get(name) if type(name) is str else None
    if entry is None or type(value) is not entry[1]:
        raise pickle.UnpicklingError('SafeDisk refuses a scalar')

    numpy = _import_numpy()

    try:
        return getattr(numpy, entry[0])(value)
    except Exception as error:
        raise pickle.UnpicklingError('SafeDisk refuses a scalar') from error


def _shape(shape):
    """Return `shape` if it is a tuple of at most 64 sizes, else None."""
    # pylint: disable=unidiomatic-typecheck
    if (
        type(shape) is tuple
        and len(shape) <= 64
        and all(type(size) is int and size >= 0 for size in shape)
    ):
        return shape
    return None


# The persistent IDs that a row can hold, by kind:
#
#   ('npy', header, data)                     a plain array
#   ('scalar', name, value)                   a numpy scalar
#   ('objects', shape, items)                 an array of objects, in C order
#   ('records', array)                        a numpy.recarray of `array`
#   ('masked', data, mask, fill_value, hard)  a numpy.ma.MaskedArray
#
# The fields of the last three are pickled as any value is, so the arrays in
# them are persistent IDs of their own and the items are checked like any
# value. The functions below build those three from fields a row chose.


def _object_array(shape, items):
    """Return the array of objects of `shape` holding `items` in C order."""
    # pylint: disable=broad-except,unidiomatic-typecheck
    if _shape(shape) is None or type(items) is not list:
        raise pickle.UnpicklingError('SafeDisk refuses an array of objects')
    if math.prod(shape) != len(items):
        raise pickle.UnpicklingError('SafeDisk refuses an array of objects')

    numpy = _import_numpy()

    try:
        array = numpy.empty(shape, dtype=object)
        flat = array.reshape(-1)
        for index, item in enumerate(items):
            flat[index] = item
    except Exception as error:
        raise pickle.UnpicklingError(
            'SafeDisk refuses an array of objects'
        ) from error
    return array


def _record_array(array):
    """Return `array`, a plain array, as a numpy.recarray."""
    numpy = _import_numpy()
    # pylint: disable=unidiomatic-typecheck
    if type(array) is not numpy.ndarray:
        raise pickle.UnpicklingError('SafeDisk refuses a record array')
    return array.view(numpy.recarray)


def _masked_array(data, mask, fill_value, hard_mask):
    """Return the masked array of `data`, `mask` and `fill_value`.

    `mask` is None for no mask and `fill_value` None for numpy's default,
    otherwise a 0-d array that numpy checks against the data.

    """
    # pylint: disable=broad-except,unidiomatic-typecheck
    numpy = _import_numpy()
    ma = numpy.ma

    if (
        type(data) not in (numpy.ndarray, numpy.recarray)
        or not (
            fill_value is None
            or (type(fill_value) is numpy.ndarray and fill_value.shape == ())
        )
        or type(hard_mask) is not bool
    ):
        raise pickle.UnpicklingError('SafeDisk refuses a masked array')

    if mask is None:
        mask = ma.nomask
    elif (
        type(mask) is not numpy.ndarray
        or mask.shape != data.shape
        or mask.dtype != ma.make_mask_descr(data.dtype)
    ):
        raise pickle.UnpicklingError('SafeDisk refuses a masked array')

    try:
        return ma.MaskedArray(
            data,
            mask=mask,
            fill_value=fill_value,
            hard_mask=hard_mask,
            copy=False,
        )
    except Exception as error:
        raise pickle.UnpicklingError(
            'SafeDisk refuses a masked array'
        ) from error


# The kinds built from fields, with the number of items in their IDs.
_BUILT_KINDS = {
    'objects': (_object_array, 3),
    'records': (_record_array, 2),
    'masked': (_masked_array, 5),
}


class _ArrayPickler(pickle.Pickler):
    """Pickler that writes numpy arrays and scalars as persistent IDs.

    With `c_order` set, as for keys, every array is written in C order, so
    arrays equal in dtype, shape and data give equal bytes.

    """

    def __init__(self, file, protocol, numpy, c_order=False):
        super().__init__(file, protocol=protocol)
        self._numpy = numpy
        self._ma = sys.modules.get('numpy.ma')
        self._c_order = c_order
        self._ids = {}
        self._scalar_names = {}
        self.reduced = False
        self.wrote_numpy = False
        self.wrote_objects = False

    def reducer_override(self, obj):
        """Note that an object was reduced, which can look up a name.

        CPython skips this hook only for None, booleans and exact ints,
        floats, bytes, strings, dicts, sets, frozensets, lists and tuples,
        none of which pickle a name, so every pickle that looks one up is
        noted here and scanned.

        """
        # pylint: disable=unused-argument
        self.reduced = True
        return NotImplemented

    def persistent_id(self, obj):
        numpy = self._numpy
        if isinstance(obj, numpy.ndarray):
            # pickle's own memo skips persistent IDs, and a value may hand it
            # temporary arrays, views among them. The memo holds `obj`, so
            # its id is not reused while the memo holds its ID: the buffer in
            # an ID keeps alive the base of a view, not the view.
            entry = self._ids.get(id(obj))
            if entry is None:
                entry = self._ids[id(obj)] = (obj, self._array_id(obj))
            self.wrote_numpy = True
            return entry[1]
        if isinstance(obj, numpy.generic):
            dtype = obj.dtype
            name = self._scalar_names.get(dtype)
            if name is None:
                name = self._scalar_names[dtype] = _scalar_name(obj)
            self.wrote_numpy = True
            return ('scalar', name, _scalar_value(numpy, obj))
        return None

    def _array_id(self, obj):
        """Return the persistent ID of the array `obj`, or raise TypeError."""
        # pylint: disable=protected-access,unidiomatic-typecheck
        numpy, ma = self._numpy, self._ma
        kind = type(obj)

        if kind is numpy.memmap:
            # A memory map is stored as the plain array of its data.
            obj, kind = obj.view(numpy.ndarray), numpy.ndarray

        if kind is numpy.ndarray:
            if obj.dtype.kind == 'O':
                self.wrote_objects = True
                shape = tuple(int(size) for size in obj.shape)
                return ('objects', shape, list(obj.flat))
            if self._c_order and not obj.flags.c_contiguous:
                obj = obj.copy(order='C')
            return ('npy',) + _pack_array(numpy, obj)

        if kind is numpy.recarray:
            return ('records', obj.view(numpy.ndarray))

        if ma is not None and kind is ma.MaskedArray:
            mask = ma.getmask(obj)
            # numpy keeps None until a fill value is set, and its default
            # depends on the dtype, so None is stored as None. Checked on
            # numpy 1.26 and 2.5.
            fill = obj._fill_value
            return (
                'masked',
                obj.data,
                None if mask is ma.nomask else numpy.asarray(mask),
                None if fill is None else numpy.asarray(obj.fill_value),
                bool(obj.hardmask),
            )

        name = '%s.%s' % (kind.__module__, kind.__qualname__)
        if ma is not None and isinstance(obj, ma.MaskedArray):
            raise TypeError(
                'SafeDisk cannot store %s, a subclass of'
                ' numpy.ma.MaskedArray; store a plain masked array instead'
                % (name,)
            )
        raise TypeError(
            'SafeDisk cannot store a subclass of ndarray: %s; store'
            ' numpy.asarray() of it instead' % (name,)
        )


class _ArrayUnpickler(SafeUnpickler):
    """Unpickler that reads back what _ArrayPickler wrote.

    Array state is rebuilt from the checked ``.npy`` header alone: the dtype
    slot of a trailing ``BUILD`` accepts only a ``numpy.dtype``, which
    neither the allowlist nor a persistent ID can produce.

    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._arrays = {}
        self._strings = {}
        self._built = {}

    def persistent_load(self, pid):
        # pylint: disable=unidiomatic-typecheck
        kind = pid[0] if type(pid) is tuple and pid else None
        if type(kind) is not str:
            kind = None

        if kind == 'scalar' and len(pid) == 3:
            value = pid[2]
            if type(value) not in (str, bytes):
                return _unpack_scalar(pid[1], value)
            # A string the pickle memoized is copied into a numpy scalar
            # once, however many IDs name it, as an array buffer is.
            entry = self._strings.get(id(value))
            if entry is None:
                entry = (value, _unpack_scalar(pid[1], value))
                self._strings[id(value)] = entry
            return entry[1]

        if kind == 'npy' and len(pid) == 3:
            header, payload = pid[1], pid[2]
            if type(header) is bytes and type(payload) is bytearray:
                # Decoding each buffer once keeps what a row can decode to
                # within its own size, and shared arrays shared. Holding
                # the pair keeps their ids from being reused.
                key = (id(header), id(payload))
                entry = self._arrays.get(key)
                if entry is None:
                    array = _unpack_array(header, payload)
                    entry = (header, payload, array)
                    self._arrays[key] = entry
                return entry[2]

        build = _BUILT_KINDS.get(kind)
        if build is not None and len(pid) == build[1]:
            # The pickle memoizes an ID, so an object named twice is built
            # once and stays shared. Holding the ID keeps its id in use.
            entry = self._built.get(id(pid))
            if entry is None:
                entry = self._built[id(pid)] = (pid, build[0](*pid[1:]))
            return entry[1]

        raise pickle.UnpicklingError('SafeDisk refuses a persistent ID')


def plain_key(numpy, key):
    """Return `key` with numpy scalars in it turned into Python ones.

    numpy booleans, integers, floats, complex numbers, strings and bytes
    become the Python value ``item()`` gives, also inside tuples, lists,
    dicts, sets and frozensets, so ``int64(1)`` and ``1``, which compare
    equal, name the same entry. Other keys are returned unchanged.

    """
    # pylint: disable=unidiomatic-typecheck
    kind = type(key)

    if kind in _PLAIN_TYPES:
        return key
    if isinstance(key, numpy.generic):
        return key.item() if key.dtype.kind in 'biufcUS' else key

    if kind is tuple or kind is list:
        if all(type(item) in _PLAIN_TYPES for item in key):
            return key
        items = [plain_key(numpy, item) for item in key]
        changed = any(new is not old for new, old in zip(items, key))
    elif kind is dict:
        items = [
            (plain_key(numpy, name), plain_key(numpy, value))
            for name, value in key.items()
        ]
        changed = any(
            new[0] is not old[0] or new[1] is not old[1]
            for new, old in zip(items, key.items())
        )
    elif kind is set or kind is frozenset:
        items = [plain_key(numpy, item) for item in key]
        changed = any(new is not old for new, old in zip(items, key))
    else:
        return key

    return kind(items) if changed else key


_PLAIN_TYPES = frozenset((bytes, str, int, float, bool, type(None)))


def _dump(disk, numpy, obj, what, c_order=False):
    """Return the pickle of `obj` and whether it holds numpy data.

    Raise TypeError unless the reader of `disk` would accept the pickle.

    """
    # pylint: disable=protected-access
    buffer = io.BytesIO()
    protocol = max(disk.pickle_protocol, _MIN_PROTOCOL)
    pickler = _ArrayPickler(buffer, protocol, numpy, c_order)

    try:
        pickler.dump(obj)
    except (pickle.PicklingError, AttributeError, RecursionError) as error:
        raise TypeError(
            'SafeDisk cannot store %s: %s' % (what, error)
        ) from error

    data = buffer.getvalue()

    # Only a reduced object can look up a name, and scanning the pickle
    # would copy every array in it.
    if pickler.reduced:
        disk._check_pickle(data, obj, what)

    # An array of objects can hold itself, which pickles but cannot be
    # built back, so a pickle with one is read back once before it is kept.
    if pickler.wrote_objects:
        try:
            disk._unpickler(io.BytesIO(data)).load()
        except pickle.UnpicklingError as error:
            raise TypeError(
                'SafeDisk cannot store %s: %s' % (what, error)
            ) from None

    return data, pickler.wrote_numpy


def put_key(disk, numpy, key):
    """Return the Cache table key fields of `key`, or None to store it as
    a plain SafeDisk does, which `key` then passes.

    A key without numpy is pickled as a plain SafeDisk pickles it, so it
    keeps the bytes earlier versions wrote. A key holding numpy data is
    pickled as a value is, with every array in C order.

    """
    # pylint: disable=protected-access
    try:
        disk._check(key, 'key')
    except TypeError:
        pass
    else:
        return None

    if not _holds_numpy(numpy, key):
        try:
            data = pickle.dumps(key, protocol=disk.pickle_protocol)
        except (pickle.PicklingError, AttributeError, RecursionError):
            data = None
        if data is not None:
            names = _pickle_globals(data)
            if names is not None and not any(
                _in_modules(module, ('numpy',)) for module, _ in names
            ):
                disk._check_pickle(data, key, 'key', names)
                return sqlite3.Binary(pickletools.optimize(data)), False

    data, _ = _dump(disk, numpy, key, 'key', c_order=True)
    return sqlite3.Binary(pickletools.optimize(data)), False


def _holds_numpy(numpy, key):
    """Return whether `key`, or an item of it if it is a tuple or a list,
    is a numpy array or scalar, which spares pickling it twice."""
    # pylint: disable=unidiomatic-typecheck
    types = (numpy.ndarray, numpy.generic)
    if isinstance(key, types):
        return True
    return type(key) in (tuple, list) and any(
        isinstance(item, types) for item in key
    )


def unpickler(disk, file):
    """Return the unpickler of `disk`, a SafeDisk with ``safe_numpy`` set."""
    return _ArrayUnpickler(
        file,
        SAFE_PICKLE_NAMES,
        disk.safe_types,
        disk.safe_modules,
    )


def store(disk, numpy, value, key):
    """Return the Cache table fields of `value`, which may hold numpy data.

    `disk` is a SafeDisk with ``safe_numpy`` set and `numpy` the imported
    module. A value with no numpy in it is stored as an ordinary pickle.

    """
    # pylint: disable=protected-access
    try:
        disk._check(value, 'value')
    except TypeError:
        pass
    else:
        return Disk.store(disk, value, False, key=key)

    data, _ = _dump(disk, numpy, value, 'value')
    return disk._store_pickle(data, value, key)
