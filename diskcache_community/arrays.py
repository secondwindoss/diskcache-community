"""Disk that stores numpy arrays without pickling them."""

import io
import math
import pickle
import warnings

from .core import SAFE_PICKLE_NAMES, Disk, SafeUnpickler, _ReaderMissing

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


def _import_numpy():
    # pylint: disable=import-error,import-outside-toplevel
    try:
        import numpy
    except ImportError as error:
        raise _ReaderMissing(
            'SafeDisk needs numpy to read this entry'
        ) from error
    return numpy


def _read_header(numpy, header, size):
    """Return shape, Fortran order and dtype from the ``.npy`` `header`.

    Raise UnpicklingError unless the header is consistent with `size` bytes
    of data. The sizes are checked because a forged shape must not decide
    what gets read. Anything that goes wrong while parsing, including a
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
        or dtype.itemsize * count != size
        or (count and not dtype.itemsize)
    ):
        raise pickle.UnpicklingError('SafeDisk refuses the array header')

    return shape, fortran, dtype


def _pack_array(numpy, array):
    """Return the ``.npy`` header of `array` and a buffer of its data.

    The buffer is the array's own memory, so pickle copies it once, into
    the row, as a bytearray. An array that is not contiguous or not
    writable is copied first, since pickle stores a read-only buffer as
    bytes, which the reader refuses.

    """
    # pylint: disable=no-member
    flags = array.flags
    if not (flags.writeable and (flags.c_contiguous or flags.f_contiguous)):
        array = array.copy(order='A')

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
        raise TypeError(
            'SafeDisk cannot store an array of dtype %s' % (array.dtype,)
        ) from error

    return header, pickle.PickleBuffer(array)


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
    name = {'U': 'str', 'S': 'bytes'}.get(dtype.kind, dtype.name)
    if name not in _SCALARS:
        raise TypeError(
            'SafeDisk cannot store a scalar of type numpy.%s'
            % (type(scalar).__name__,)
        )
    return name


def _unpack_scalar(name, value):
    """Return the numpy scalar `value` of type `name`, which may be forged.

    The value must be of the Python type the name is built from: numpy
    would otherwise build something else, such as ``bytes_(n)``, which is
    `n` zero bytes.

    """
    # pylint: disable=broad-except,unidiomatic-typecheck
    entry = _SCALARS.get(name) if type(name) is str else None
    if entry is None or type(value) is not entry[1]:
        raise pickle.UnpicklingError('SafeDisk refuses a scalar')

    numpy = _import_numpy()

    try:
        return getattr(numpy, entry[0])(value)
    except Exception as error:
        raise pickle.UnpicklingError('SafeDisk refuses a scalar') from error


class _ArrayPickler(pickle.Pickler):
    """Pickler that writes arrays and numpy scalars as persistent IDs."""

    def __init__(self, file, protocol, numpy):
        super().__init__(file, protocol=protocol)
        self._numpy = numpy
        self._arrays = {}
        self._scalar_names = {}
        self.reduced = False

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
        # pylint: disable=unidiomatic-typecheck
        numpy = self._numpy
        if isinstance(obj, numpy.ndarray):
            if type(obj) is not numpy.ndarray:
                raise TypeError(
                    'SafeDisk cannot store a subclass of ndarray: %s.%s'
                    % (type(obj).__module__, type(obj).__qualname__)
                )
            # pickle's own memo skips persistent IDs, and a value may hand it
            # temporary arrays. The buffer in the ID keeps `obj` alive, so
            # its id is not reused while this memo holds the ID.
            pid = self._arrays.get(id(obj))
            if pid is None:
                pid = self._arrays[id(obj)] = ('npy',) + _pack_array(
                    numpy, obj
                )
            return pid
        if isinstance(obj, numpy.generic):
            kind = type(obj)
            name = self._scalar_names.get(kind)
            if name is None:
                name = self._scalar_names[kind] = _scalar_name(obj)
            value = obj.item()
            if isinstance(value, numpy.generic):
                raise TypeError(
                    'SafeDisk cannot store a scalar of type numpy.%s'
                    % (kind.__name__,)
                )
            return ('scalar', name, value)
        return None


class _ArrayUnpickler(SafeUnpickler):
    """Unpickler that reads back what _ArrayPickler wrote.

    A forged row can follow an array with BUILD, which calls its
    ``__setstate__``. numpy restores an array's internal flags from the dtype
    in that state without checking them, which is why numpy pickles are
    refused. The call is harmless here because the dtype slot accepts only a
    ``numpy.dtype``, and neither the allowlist nor a persistent ID can make
    one; a test pins that.

    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._arrays = {}
        self._strings = {}

    def persistent_load(self, pid):
        # pylint: disable=unidiomatic-typecheck
        if type(pid) is tuple and len(pid) == 3:
            if pid[0] == 'scalar':
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
            if pid[0] == 'npy':
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
        raise pickle.UnpicklingError('SafeDisk refuses a persistent ID')


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

    buffer = io.BytesIO()
    protocol = max(disk.pickle_protocol, _MIN_PROTOCOL)
    pickler = _ArrayPickler(buffer, protocol, numpy)

    try:
        pickler.dump(value)
    except (pickle.PicklingError, AttributeError) as error:
        raise TypeError(
            'SafeDisk cannot store value: %s' % (error,)
        ) from error

    data = buffer.getvalue()

    # Only a reduced object can look up a name, and scanning the pickle
    # would copy every array in it.
    if pickler.reduced:
        disk._check_pickle(data, value, 'value')

    return disk._store_pickle(data, value, key)
