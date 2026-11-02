"""Disk that stores numpy arrays without pickling them."""

import io
import math
import pickle

from .core import SAFE_PICKLE_NAMES, Disk, SafeUnpickler, _ReaderMissing

# Pickle protocol 5 is the first that stores a bytearray in place, so that
# reading a file-backed entry needs no second copy of its array.
_MIN_PROTOCOL = 5

# Bytes of a ``.npy`` file that can hold its header: the prefix, plus the
# longest header that numpy parses by default, plus padding.
_HEADER_LIMIT = 12 + 10000 + 64

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
            'SafeDisk refuses the array header'
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
        raise pickle.UnpicklingError('SafeDisk refuses the array header')

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
            'SafeDisk cannot store an array of dtype %s' % (array.dtype,)
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
                    'SafeDisk cannot store a subclass of ndarray: %s.%s'
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
                    'SafeDisk cannot store a scalar of type numpy.%s'
                    % (kind.__name__,)
                )
            return ('scalar', name, value)
        return None


class _ArrayUnpickler(SafeUnpickler):
    """Unpickler that reads back what _ArrayPickler wrote."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._arrays = {}
        self._strings = {}

    def persistent_load(self, pid):
        # pylint: disable=unidiomatic-typecheck
        if type(pid) is tuple:
            if len(pid) == 3 and pid[0] == 'scalar':
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
