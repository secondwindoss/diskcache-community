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

# Pickle protocol 0 takes only strings as persistent IDs, and protocols below
# 3 have no opcode for bytes.
_MIN_PROTOCOL = 3


def _check_header(numpy, data):
    """Raise UnpicklingError unless the ``.npy`` bytes `data` are consistent.

    The sizes in the header are checked against the data because a forged
    shape would otherwise raise MemoryError, which ``on_error='miss'`` does
    not treat as an unreadable entry. For the same reason, anything that goes
    wrong while parsing the header, including a MemoryError from the Python
    parser on a crafted one, is reported as UnpicklingError.

    """
    # pylint: disable=broad-except,no-member
    try:
        reader = io.BytesIO(data)
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

    shape, _, dtype = header
    count = math.prod(shape)

    # A zero-width dtype would let any shape match any amount of data.
    if dtype.itemsize * count != len(data) - reader.tell() or (
        count and not dtype.itemsize
    ):
        raise pickle.UnpicklingError('SafeArrayDisk refuses the array header')


def _pack_array(numpy, array):
    """Return the ``.npy`` bytes of `array`, which a reader will accept."""
    buffer = io.BytesIO()
    try:
        numpy.save(buffer, array, allow_pickle=False)
        data = buffer.getvalue()
        _check_header(numpy, data)
    except (ValueError, pickle.UnpicklingError) as error:
        raise TypeError(
            'SafeArrayDisk cannot store an array of dtype %s' % (array.dtype,)
        ) from error
    return data


def _unpack_array(data):
    """Return the array in ``.npy`` bytes that may have been tampered with."""
    # pylint: disable=broad-except,import-error,import-outside-toplevel
    # pylint: disable=no-member
    try:
        import numpy
    except ImportError as error:
        raise _ReaderMissing(
            'SafeArrayDisk needs numpy to read an array'
        ) from error

    _check_header(numpy, data)

    try:
        return numpy.lib.format.read_array(
            io.BytesIO(data), allow_pickle=False
        )
    except MemoryError:
        raise  # The header matched the data, so this is a real shortage.
    except Exception as error:
        raise pickle.UnpicklingError(
            'SafeArrayDisk refuses the array data'
        ) from error


def _item(numpy, scalar):
    """Return the Python value of numpy `scalar`, or raise TypeError."""
    if isinstance(
        scalar, (numpy.bool_, numpy.number, numpy.str_, numpy.bytes_)
    ) and not isinstance(scalar, numpy.timedelta64):
        value = scalar.item()
        if not isinstance(value, numpy.generic):
            return value
    raise TypeError(
        'SafeArrayDisk cannot store a scalar of type numpy.%s'
        % (type(scalar).__name__,)
    )


class _ArrayPickler(pickle.Pickler):
    """Pickler that writes arrays and numpy scalars as persistent IDs."""

    def __init__(self, file, protocol, numpy):
        super().__init__(file, protocol=protocol)
        self._numpy = numpy
        self._arrays = {}

    def persistent_id(self, obj):
        # pylint: disable=unidiomatic-typecheck
        numpy = self._numpy
        if isinstance(obj, numpy.ndarray):
            if type(obj) is not numpy.ndarray:
                raise TypeError(
                    'SafeArrayDisk cannot store a subclass of ndarray: %s.%s'
                    % (type(obj).__module__, type(obj).__qualname__)
                )
            pid = self._arrays.get(id(obj))
            if pid is None:
                pid = ('npy', _pack_array(numpy, obj))
                self._arrays[id(obj)] = pid
            return pid
        if isinstance(obj, numpy.generic):
            return ('item', _item(numpy, obj))
        return None


class _ArrayUnpickler(SafeUnpickler):
    """Unpickler that reads back what _ArrayPickler wrote."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._arrays = {}

    def persistent_load(self, pid):
        # pylint: disable=unidiomatic-typecheck
        if type(pid) is tuple and len(pid) == 2:
            kind, payload = pid
            if kind == 'item':
                return payload
            if kind == 'npy':
                # Decoding each bytes object once keeps what a row can decode
                # to within its own size, and arrays that were shared shared.
                # Holding `payload` keeps its id from being reused.
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
      its header is checked before it is read back with
      ``allow_pickle=False``. That includes the containers :class:`SafeDisk`
      accepts and the classes allowed with :meth:`SafeDisk.with_types`.
    * numpy integers, floats, complex numbers, booleans and strings read back
      as the equivalent Python value.
    * Arrays of objects, subclasses of ``ndarray`` such as masked arrays, and
      other numpy scalars raise :exc:`TypeError` when written.

    Keys and everything else behave as in :class:`SafeDisk`. numpy stays
    optional: it is used only for a value that needs it, and a process without
    it raises :exc:`ImportError` for an entry with an array and keeps the
    entry, even with ``on_error='miss'``.

    A value with no numpy in it is an ordinary pickle. An entry holding numpy
    data cannot be read by any other disk, or by diskcache 5.6.3: they raise
    :exc:`pickle.UnpicklingError` for it, and a disk with ``on_error='miss'``
    deletes it. Every process that shares a directory should select this disk.

    """

    def _unpickler(self, data):
        return _ArrayUnpickler(
            io.BytesIO(data),
            SAFE_PICKLE_NAMES,
            self.safe_types,
            self.safe_modules,
        )

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

        if isinstance(value, numpy.generic):
            item = _item(numpy, value)
            # SQLite stores a raw NaN as NULL, so NaN stays in a pickle below.
            if item == item:  # pylint: disable=comparison-with-itself
                return super().store(item, read, key=key)

        buffer = io.BytesIO()
        protocol = max(self.pickle_protocol, _MIN_PROTOCOL)

        try:
            _ArrayPickler(buffer, protocol, numpy).dump(value)
        except (pickle.PicklingError, AttributeError) as error:
            raise TypeError(
                'SafeArrayDisk cannot store value: %s' % (error,)
            ) from error

        data = buffer.getvalue()
        self._check_pickle(data, value, 'value')
        return self._store_pickle(data, value, key)
