"""Disk that stores numpy arrays without pickling them."""

import io
import math
import pickle
import sys

from .core import UNKNOWN, SafeDisk

_NPY_KEY = '__diskcache_community_npy__'


def _contains(value, match):
    """Return True if `match` holds for `value` or anything nested in it."""
    seen = set()
    stack = [value]

    while stack:
        item = stack.pop()
        if match(item):
            return True
        type_item = type(item)
        if type_item in (dict, list, tuple):
            if id(item) in seen:
                continue
            seen.add(id(item))
            if type_item is dict:
                stack.extend(item.keys())
                stack.extend(item.values())
            else:
                stack.extend(item)

    return False


def _rebuild(value, convert):
    """Return `value` with `convert` applied through dicts, lists and tuples.

    `convert` returns its argument unchanged for anything it leaves alone.

    """
    converted = convert(value)
    if converted is not value:
        return converted
    type_value = type(value)
    if type_value is dict:
        return {
            _rebuild(key, convert): _rebuild(item, convert)
            for key, item in value.items()
        }
    if type_value is list:
        return [_rebuild(item, convert) for item in value]
    if type_value is tuple:
        return tuple(_rebuild(item, convert) for item in value)
    return value


def _encoded_array(item):
    # pylint: disable=unidiomatic-typecheck
    return type(item) is dict and len(item) == 1 and _NPY_KEY in item


def _pack_array(numpy, array):
    """Return `array` as a dict that holds its ``.npy`` bytes."""
    if array.dtype.hasobject:
        raise TypeError(
            'SafeArrayDisk cannot store an array of dtype %s' % (array.dtype,)
        )
    buffer = io.BytesIO()
    numpy.save(buffer, array, allow_pickle=False)
    data = buffer.getvalue()
    if data[6:8] not in (b'\x01\x00', b'\x02\x00'):
        raise TypeError(
            'SafeArrayDisk cannot store an array of dtype %s' % (array.dtype,)
        )
    return {_NPY_KEY: data}


def _unpack_array(data):
    """Return the array in ``.npy`` bytes that may have been tampered with.

    The sizes in the header are checked against the data first, because a
    forged shape would otherwise raise :exc:`MemoryError`, which
    ``on_error='miss'`` does not treat as an unreadable entry.

    """
    # pylint: disable=import-error,import-outside-toplevel,no-member
    import numpy

    reader = io.BytesIO(data)
    version = numpy.lib.format.read_magic(reader)
    if version == (1, 0):
        header = numpy.lib.format.read_array_header_1_0(reader)
    elif version == (2, 0):
        header = numpy.lib.format.read_array_header_2_0(reader)
    else:
        raise pickle.UnpicklingError('SafeArrayDisk found no array data')

    shape, _, dtype = header
    size = dtype.itemsize * math.prod(shape)

    if size != len(data) - reader.tell():
        raise pickle.UnpicklingError('SafeArrayDisk refuses the array header')

    reader.seek(0)
    return numpy.lib.format.read_array(reader, allow_pickle=False)


class SafeArrayDisk(SafeDisk):
    """Disk that stores numpy arrays as ``.npy`` bytes instead of pickles.

    :class:`SafeDisk` refuses numpy, because unpickling an array is not
    memory-safe (see ``UNSAFE_MODULES``). :class:`SafeArrayDisk` keeps those
    pickles out of the cache and stores arrays in numpy's own format:

    * An array on its own or inside a ``dict``, ``list`` or ``tuple`` is saved
      with ``allow_pickle=False``, and its header is checked before it is
      read back with ``allow_pickle=False``.
    * numpy integers, floats, complex numbers, booleans and strings are stored
      as the equivalent Python value, so they read back as that value.
    * Arrays of objects, subclasses of ``ndarray`` such as masked arrays, and
      arrays inside any other type raise :exc:`TypeError` when written.

    Everything else behaves as in :class:`SafeDisk`, including
    :meth:`SafeDisk.with_types`. numpy stays optional: it is imported only to
    read an array back. An encoded array is an ordinary pickled ``dict``, so
    a process that uses another disk, or diskcache 5.6.3, reads that ``dict``
    instead of the array, and every process that shares a directory should
    select this disk.

    """

    def store(self, value, read, key=UNKNOWN):
        numpy = sys.modules.get('numpy')
        kinds = (numpy.ndarray, numpy.generic) if numpy else ()

        def needs_encoding(item):
            # pylint: disable=unidiomatic-typecheck
            if type(item) is dict and _NPY_KEY in item:
                raise TypeError(
                    'SafeArrayDisk cannot store a dict with the key %r'
                    % (_NPY_KEY,)
                )
            return isinstance(item, kinds)

        def encode(item):
            # pylint: disable=unidiomatic-typecheck
            if type(item) is numpy.ndarray:
                return _pack_array(numpy, item)
            if isinstance(
                item,
                (numpy.bool_, numpy.number, numpy.str_, numpy.bytes_),
            ) and not isinstance(item, numpy.timedelta64):
                return item.item()
            return item

        if _contains(value, needs_encoding):
            try:
                value = _rebuild(value, encode)
            except RecursionError:
                raise TypeError(
                    'SafeArrayDisk cannot store a nested value this deep'
                ) from None

        return super().store(value, read, key=key)

    def fetch(self, mode, filename, value, read):
        result = super().fetch(mode, filename, value, read)

        if not _contains(result, _encoded_array):
            return result

        def decode(item):
            if _encoded_array(item):
                return _unpack_array(item[_NPY_KEY])
            return item

        try:
            return _rebuild(result, decode)
        except RecursionError:
            raise pickle.UnpicklingError(
                'SafeArrayDisk refuses a value nested this deep'
            ) from None
