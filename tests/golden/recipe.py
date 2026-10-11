"""Dataset shared by the golden fixture writer and the golden tests.

Everything the writer stores and the tests expect to read back is derived
from the constants in this module, so the two sides cannot drift apart. This
module must not import diskcache: it is imported both by the upstream 5.6.3
wheel (when the fixtures are written) and by the current code (when they are
read).
"""

import datetime

# Provenance of the archive in this directory.

WHEEL_VERSION = '5.6.3'
WHEEL_FILENAME = 'diskcache-5.6.3-py3-none-any.whl'
WHEEL_SHA256 = (
    '5e31b2d5fbad117cc363ebaf6b689474db18a1f6438bc82358b024abd4c2ca19'
)
WRITER_PICKLE_PROTOCOL = 5  # pickle.HIGHEST_PROTOCOL of the writer
ARCHIVE = 'diskcache-5.6.3.tar.gz'
ARCHIVE_ROOT = 'diskcache-5.6.3'
PROVENANCE = 'PROVENANCE.txt'

# Directory of each fixture cache below ARCHIVE_ROOT.

DIR_DEFAULT = 'cache-default'
DIR_TAG_INDEX = 'cache-tag-index'
DIR_POLICY = 'cache-policy-{}'
DIR_STATISTICS = 'cache-statistics'
DIR_SETTINGS = 'cache-settings'
DIR_JSONDISK = 'cache-jsondisk'
DIR_FANOUT = 'fanout'
DIR_DEQUE = 'deque'
DIR_INDEX = 'index'

# Expiry. Entries marked FUTURE are stored with an absolute expire time of
# 2100-01-01T00:00:00Z; entries marked EXPIRED are stored with a short expiry
# that the writer outlives before closing the cache, so the rows stay in the
# database with an expire time in the past.

FUTURE = 4102444800.0
EXPIRED = 'expired'
EXPIRE_SECONDS = 1.0
EXPIRE_TOLERANCE = 60.0

# Values above the default ``disk_min_file_size`` of 32 KiB go to .val files.

LARGE_SIZE = 33_000


def large_bytes(seed):
    """Return LARGE_SIZE deterministic bytes: a 4 KiB noise block repeated.

    The block looks like binary data to diskcache; the repetition keeps the
    archive small.
    """
    state = seed & 0x7FFFFFFF
    block = bytearray()
    for _ in range(4096):
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        block.append((state >> 16) & 0xFF)
    repeats = LARGE_SIZE // len(block) + 1
    return bytes(block * repeats)[:LARGE_SIZE]


def large_text(seed):
    """Return LARGE_SIZE deterministic characters, including non-ASCII."""
    words = ('cache', 'disk', 'sqlite', 'ключ', 'värde', 'value', '✓')
    parts = []
    size = 0
    index = seed
    while size < LARGE_SIZE:
        word = words[index % len(words)]
        parts.append(word)
        size += len(word) + 1
        index += 1
    return ' '.join(parts)[:LARGE_SIZE]


def json_large():
    """Return a JSON list whose compressed form is well above 1 KiB."""
    return [(index * 7919 + 104729) % 1000003 for index in range(2000)]


# The standard dataset: (key, value, tag, expire). Keys cover the str, int,
# float and bytes paths that are stored raw and the tuple path that is
# pickled. Values cover raw text, raw bytes, int, float, pickled objects, and
# large text, bytes and pickles that live in .val files. Expired entries come
# last because every write culls rows that are already expired.

ENTRIES = (
    ('text', 'small text value', 'alpha', None),
    ('text-ключ', 'юникод ✓', None, FUTURE),
    (42, b'small bytes', None, None),
    (-7, 'negative int key', 'beta', None),
    (3.5, 123456789, None, FUTURE),
    (b'bytes-key', 2.75, 'beta', None),
    (
        ('tuple', 1, 2.0, None),
        {'nested': [1, 2, 3], 'when': datetime.datetime(2026, 10, 10, 12)},
        None,
        None,
    ),
    ('none-value', None, 'gamma', None),
    ('bool-value', True, None, None),
    ('big-int', 2**70, None, None),
    ('large-bytes', large_bytes(1), 'gamma', FUTURE),
    ('large-text', large_text(2), None, None),
    ('large-pickle', [index % 251 for index in range(20000)], 'delta', None),
    ('expired-text', 'gone', 'alpha', EXPIRED),
    (99, b'gone', None, EXPIRED),
)

# Counters: (key, delta, default, times) incremented with Cache.incr.

COUNTERS = (
    ('counter', 1, 0, 5),
    ('counter-delta', 10, 100, 1),
)

# Memoized calls of golden_square stored through Cache.memoize.

MEMOIZE_ARGS = (3, 4)
ALLOW_COMPUTE = False

ROW_COUNT = len(ENTRIES) + len(COUNTERS) + len(MEMOIZE_ARGS)


def golden_square(number):
    """Return number squared, unless computing is not allowed.

    The writer allows computing while it fills the caches. The tests leave
    ALLOW_COMPUTE False, so a cache miss raises instead of hiding behind a
    recomputed value.
    """
    if not ALLOW_COMPUTE:
        raise RuntimeError('memoize miss: golden_square(%r)' % (number,))
    return number * number


def memoize_key(number):
    """Return the cache key diskcache builds for golden_square(number)."""
    name = golden_square.__module__ + '.' + golden_square.__qualname__
    return (name, number, None)


def counter_value(delta, default, times):
    """Return the value of a counter after `times` increments."""
    return default + delta * times


def live_entries():
    """Return the entries that are readable after writing."""
    return tuple(entry for entry in ENTRIES if entry[3] != EXPIRED)


def expired_entries():
    """Return the entries written with a short expiry."""
    return tuple(entry for entry in ENTRIES if entry[3] == EXPIRED)


def all_keys():
    """Return every key stored in a dataset cache, expired rows included."""
    keys = [entry[0] for entry in ENTRIES]
    keys.extend(counter[0] for counter in COUNTERS)
    keys.extend(memoize_key(number) for number in MEMOIZE_ARGS)
    return keys


# Statistics cache: known hits and misses with statistics enabled.

STATS_ITEMS = (('stat-a', 1), ('stat-b', 2), ('stat-c', 3))
STATS_MISSES = ('nope-1', 'nope-2')

# Settings cache: non-default persisted settings for the round-trip check.

SETTINGS_OVERRIDES = {
    'size_limit': 2**20,
    'cull_limit': 5,
    'disk_min_file_size': 1024,
    'disk_pickle_protocol': 4,
}

# JSONDisk cache: JSON-only keys and values, with a small file threshold so
# the large list is stored in a .val file.

JSON_SETTINGS = {'disk_min_file_size': 1024}
JSON_ENTRIES = (
    ('json-text', 'value'),
    ('json-list', [1, 2.5, 'x', None, True]),
    ('json-dict', {'a': 1, 'b': [1, 2], 'c': {'d': None}}),
    ('json-large', json_large()),
)

# Eviction policies and the index each one creates.

EVICTION_POLICIES = (
    'least-recently-stored',
    'least-recently-used',
    'least-frequently-used',
    'none',
)
POLICY_INDEXES = {
    'least-recently-stored': 'Cache_store_time',
    'least-recently-used': 'Cache_access_time',
    'least-frequently-used': 'Cache_access_count',
    'none': None,
}

# Schema object names that the compatibility contract keeps fixed.

TABLES = {'Settings', 'Cache'}
BASE_INDEXES = {'Cache_key_raw', 'Cache_expire_time'}
TAG_INDEX = 'Cache_tag_rowid'
TRIGGERS = {
    'Settings_count_insert',
    'Settings_count_delete',
    'Settings_size_insert',
    'Settings_size_update',
    'Settings_size_delete',
}

# FanoutCache with its sub-containers, and standalone Deque and Index.

FANOUT_SHARDS = 4
SUB_CACHE_ITEMS = (('sub-key', 'sub-value'), (1, [1, 2]))
DEQUE_ITEMS = ('first', 'a', 1, 2.5, b'b', ('t', 1), None)
INDEX_ITEMS = (
    ('a', 1),
    ('b', 'two'),
    (3, [3]),
    (('t',), {'k': 'v'}),
    (b'bk', None),
)
