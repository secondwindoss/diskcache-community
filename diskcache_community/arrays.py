"""Disk that stores numpy arrays without pickling them."""

import io
import math
import pickle
import sys

from .core import (
    SAFE_PICKLE_NAMES,
    UNKNOWN,
    Disk,
    SafeDisk,
    SafeUnpickler,
    _ReaderMissing,
)

# Pickle protocol 5 is the first that stores a bytearray in place, so that
# reading a file-backed entry needs no second copy of its array.
_MIN_PROTOCOL = 5

# Bytes of a ``.npy`` file that can hold its header: the prefix, plus the
# longest header that numpy parses by default, plus padding.
_HEADER_LIMIT = 12 + 10000 + 64

# The numpy scalar types that are stored, by the name written to the row. The
# names do not vary by platform or numpy version, unlike the types' own names.
_SCALARS = {
    'bool': 'bool_',
    'int8': 'int8',
    'int16': 'int16',
    'int32': 'int32',
    'int64': 'int64',
    'uint8': 'uint8',
    'uint16': 'uint16',
    'uint32': 'uint32',
    'uint64': 'uint64',
    'float16': 'float16',
    'float32': 'float32',
    'float64': 'float64',
    'complex64': 'complex64',
    'complex128': 'complex128',
    'str': 'str_',
    'bytes': 'bytes_',
}
_SCALAR_VALUES = (bool, int, float, complex, str, bytes)


def _import_numpy():
    # pylint: disable=import-error,import-outside-toplevel
    try:
        import numpy
    except ImportError as error:
        raise _ReaderMissing(
            'SafeArrayDisk needs numpy to read this entry'
        ) from error
    return numpy


def _read_header(numpy, data):
    """Return shape, Fortran order, dtype and offset of ``.npy`` bytes `data`.

    Raise UnpicklingError unless the header is consistent with the data. The
    sizes are checked because a forged shape must not decide what gets read.
    Anything that goes wrong while parsing, including a MemoryError from the
    Python parser on a crafted header, which ``on_error='miss'`` would not
    treat as an unreadable entry, is reported as UnpicklingError.

    """
    # pylint: disable=broad-except,no-member
    try:
        reader = io.BytesIO(bytes(memoryview(data)[:_HEADER_LIMIT]))
        version = numpy.lib.format.read_magic(reader)
        if version == (1, 0):
            header = numpy.lib.format.read_array_header_1_0(reader)
        elif version == (2, 0):
            header = numpy.lib.format.read_array_header_2_0(reader)
        else:
            raise ValueError('unsupported .npy version %r' % (version,))
    except Exception as error:
        raise pickle.UnpicklingError(
            'SafeArrayDisk refuses the array header'
        ) from error

    shape, fortran, dtype = header
    offset = reader.tell()
    count = math.prod(shape)

    # A zero-width dtype would let any shape match any amount of data.
    if (
        dtype.hasobject
        or dtype.itemsize * count != len(data) - offset
        or (count and not dtype.itemsize)
    ):
        raise pickle.UnpicklingError('SafeArrayDisk refuses the array header')

    return shape, fortran, dtype, offset


def _pack_array(numpy, array):
    """Return a buffer of the ``.npy`` bytes of `array`, for pickle to store.

    The buffer is writable, so pickle stores it as a bytearray in place.

    """
    buffer = io.BytesIO()
    try:
        numpy.save(buffer, array, allow_pickle=False)
        view = buffer.getbuffer()
        _read_header(numpy, view)
    except (ValueError, pickle.UnpicklingError) as error:
        raise TypeError(
            'SafeArrayDisk cannot store an array of dtype %s' % (array.dtype,)
        ) from error
    return pickle.PickleBuffer(view)


def _unpack_array(data):
    """Return the array in the bytearray `data`, which it keeps as its data.

    A view takes no second copy of the array, and stays writable because
    `data` is. `data` may have been tampered with.

    """
    # pylint: disable=broad-except
    numpy = _import_numpy()
    shape, fortran, dtype, offset = _read_header(numpy, data)

    try:
        if not math.prod(shape):
            return numpy.empty(shape, dtype)
        array = numpy.frombuffer(data, dtype, offset=offset)
        return array.reshape(shape, order='F' if fortran else 'C')
    except Exception as error:
        raise pickle.UnpicklingError(
            'SafeArrayDisk refuses the array data'
        ) from error


def _scalar_name(scalar):
    """Return the name to store numpy `scalar` under, or raise TypeError."""
    dtype = scalar.dtype
    name = {'U': 'str', 'S': 'bytes'}.get(dtype.kind, dtype.name)
    if name not in _SCALARS:
        raise TypeError(
            'SafeArrayDisk cannot store a scalar of type numpy.%s'
            % (type(scalar).__name__,)
        )
    return name


def _unpack_scalar(name, value):
    """Return the numpy scalar `value` of type `name`, which may be forged."""
    # pylint: disable=broad-except,unidiomatic-typecheck
    if type(value) not in _SCALAR_VALUES:
        raise pickle.UnpicklingError('SafeArrayDisk refuses a scalar')

    numpy = _import_numpy()

    try:
        return getattr(numpy, _SCALARS[name])(value)
    except Exception as error:
        raise pickle.UnpicklingError(
            'SafeArrayDisk refuses a scalar'
        ) from error


class _ArrayPickler(pickle.Pickler):
    """Pickler that writes arrays and numpy scalars as persistent IDs."""

    def __init__(self, file, protocol, numpy):
        super().__init__(file, protocol=protocol)
        self._numpy = numpy
        self._arrays = {}
        self._scalar_names = {}
        self.reduced = False

    def reducer_override(self, obj):
        """Note that an object was reduced, which can look up a name."""
        # pylint: disable=unused-argument
        self.reduced = True
        return NotImplemented

    def persistent_id(self, obj):
        # pylint: disable=unidiomatic-typecheck
        numpy = self._numpy
        if isinstance(obj, numpy.ndarray):
            if type(obj) is not numpy.ndarray:
                raise TypeError(
                    'SafeArrayDisk cannot store a subclass of ndarray: %s.%s'
                    % (type(obj).__module__, type(obj).__qualname__)
                )
            # Holding `obj` keeps its id from being reused: pickle's own memo
            # skips persistent IDs, and a value may hand it temporary arrays.
            entry = self._arrays.get(id(obj))
            if entry is None:
                entry = (obj, ('npy', _pack_array(numpy, obj)))
                self._arrays[id(obj)] = entry
            return entry[1]
        if isinstance(obj, numpy.generic):
            kind = type(obj)
            name = self._scalar_names.get(kind)
            if name is None:
                name = self._scalar_names[kind] = _scalar_name(obj)
            value = obj.item()
            if isinstance(value, numpy.generic):
                raise TypeError(
                    'SafeArrayDisk cannot store a scalar of type numpy.%s'
                    % (kind.__name__,)
                )
            return ('scalar', name, value)
        return None


class _ArrayUnpickler(SafeUnpickler):
    """Unpickler that reads back what _ArrayPickler wrote."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._arrays = {}

    def persistent_load(self, pid):
        # pylint: disable=unidiomatic-typecheck
        if type(pid) is tuple:
            if len(pid) == 3 and pid[0] == 'scalar':
                return _unpack_scalar(pid[1], pid[2])
            if len(pid) == 2 and pid[0] == 'npy':
                payload = pid[1]
                if type(payload) is bytearray:
                    # Decoding each buffer once keeps what a row can decode to
                    # within its own size, and shared arrays shared. Holding
                    # `payload` keeps its id from being reused.
                    entry = self._arrays.get(id(payload))
                    if entry is None:
                        entry = (payload, _unpack_array(payload))
                        self._arrays[id(payload)] = entry
                    return entry[1]
        raise pickle.UnpicklingError('SafeArrayDisk refuses a persistent ID')


class SafeArrayDisk(SafeDisk):
    """Disk that stores numpy arrays as ``.npy`` bytes instead of pickles.

    :class:`SafeDisk` refuses numpy, because unpickling an array is not
    memory-safe (see ``UNSAFE_MODULES``). :class:`SafeArrayDisk` keeps those
    pickles out of the cache by writing arrays through pickle's persistent IDs
    in numpy's own format:

    * An array anywhere in a value is saved with ``allow_pickle=False``, and
      its header is checked before it is read back. That includes the
      containers :class:`SafeDisk` accepts and the classes allowed with
      :meth:`SafeDisk.with_types`.
    * numpy booleans, integers, floats, complex numbers and strings read back
      as the same numpy type.
    * Arrays of objects, subclasses of ``ndarray`` such as masked arrays, and
      other numpy scalars raise :exc:`TypeError` when written.

    Keys and everything else behave as in :class:`SafeDisk`. numpy stays
    optional: it is used only for a value that needs it, and a process without
    it raises :exc:`ImportError` for an entry holding numpy data and keeps the
    entry, even with ``on_error='miss'``.

    A value with no numpy in it is an ordinary pickle. An entry holding numpy
    data cannot be read by any other disk, or by diskcache 5.6.3: they raise
    :exc:`pickle.UnpicklingError` for it, and a disk with ``on_error='miss'``
    deletes it. Every process that shares a directory should select this disk.

    """

    def _unpickler(self, file):
        return _ArrayUnpickler(
            file,
            SAFE_PICKLE_NAMES,
            self.safe_types,
            self.safe_modules,
        )

    def get(self, key, raw):
        if raw:
            return super().get(key, raw)
        # Keys never hold numpy, so a key row gets no persistent IDs.
        return super()._unpickler(io.BytesIO(key)).load()

    def store(self, value, read, key=UNKNOWN):
        # pylint: disable=unidiomatic-typecheck
        numpy = sys.modules.get('numpy')

        if numpy is None or read or type(value) in (bytes, str, int, float):
            return super().store(value, read, key=key)

        try:
            self._check(value, 'value')
        except TypeError:
            pass
        else:
            return Disk.store(self, value, read, key=key)

        buffer = io.BytesIO()
        protocol = max(self.pickle_protocol, _MIN_PROTOCOL)
        pickler = _ArrayPickler(buffer, protocol, numpy)

        try:
            pickler.dump(value)
        except (pickle.PicklingError, AttributeError) as error:
            raise TypeError(
                'SafeArrayDisk cannot store value: %s' % (error,)
            ) from error

        data = buffer.getvalue()

        # Only a reduced object can look up a name, and scanning the pickle
        # would copy every array in it.
        if pickler.reduced:
            self._check_pickle(data, value, 'value')

        return self._store_pickle(data, value, key)
