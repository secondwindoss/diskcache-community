DiskCache Tutorial
==================

.. contents::
   :depth: 1
   :local:

Installation
------------

This part of the documentation covers the installation of :doc:`DiskCache
<index>`. The first step to using any software package is getting it properly
installed.

Pip & PyPI
..........

Installing :doc:`DiskCache <index>` is simple with `pip
<https://pip.pypa.io/en/stable/>`_::

    $ pip install --upgrade diskcache

The versioning scheme uses `major.minor.micro` with `micro` intended for bug
fixes, `minor` intended for small features or improvements, and `major`
intended for significant new features and breaking changes. While it is
intended that only `major` version changes are backwards incompatible, it is
not always guaranteed. When running in production, it is recommended to pin at
least the `major` version.

Get the Code
............

:doc:`DiskCache <index>` is actively developed on GitHub, where the code is
always available.

You can either clone the `DiskCache repository <https://github.com/secondwindoss/diskcache-community>`_::

    $ git clone https://github.com/secondwindoss/diskcache-community.git

Download the `tarball <https://github.com/secondwindoss/diskcache-community/tarball/master>`_::

    $ curl -OL https://github.com/secondwindoss/diskcache-community/tarball/master

Or, download the `zipball <https://github.com/secondwindoss/diskcache-community/zipball/master>`_::

    $ curl -OL https://github.com/secondwindoss/diskcache-community/zipball/master

Once you have a copy of the source, you can embed it in your Python package,
or install it into your site-packages easily::

    $ pip install .

:doc:`DiskCache <index>` is looking for a Debian package maintainer. If you can
help, please open an issue in the `DiskCache Issue Tracker`_.

:doc:`DiskCache <index>` is looking for a CentOS/RPM package maintainer. If you
can help, please open an issue in the `DiskCache Issue Tracker`_.

.. _`DiskCache Issue Tracker`: https://github.com/secondwindoss/diskcache-community/issues/

.. _tutorial-cache:

Cache
-----

The core of :doc:`DiskCache <index>` is :class:`diskcache_community.Cache`
which represents a disk and file backed cache. As a Cache, it supports a
familiar Python mapping interface with additional cache and performance
parameters.

    >>> from diskcache_community import Cache
    >>> cache = Cache()

Initialization expects a directory path reference. If the directory path does
not exist, it will be created. Every directory the cache creates, the cache
directory itself, missing parents and the subdirectories that hold large
values, gets mode ``0o700`` so that only the owner can read it; a directory
that already exists keeps its permissions, and Windows ignores the mode bits.
When not specified, a temporary directory is automatically created. Additional
keyword parameters are discussed below. Cache objects are thread-safe and may
be shared between threads. Two Cache objects may also reference the same
directory from separate threads or processes. In this way, they are also
process-safe and support cross-process communication.

Cache objects open and maintain one or more file handles: one SQLite
connection per thread that uses the cache. But unlike files, all Cache
operations are atomic and Cache objects may be serialized using Pickle.
Calling :meth:`close <.Cache.close>` closes the calling thread's connection
and the connections of threads that have exited; connections that other
running threads use stay open until those threads call ``close`` or the Cache
object is garbage collected. Cache objects can be used in a `with` statement
to safeguard calling :meth:`close <diskcache_community.Cache.close>`.

Cache objects also support process forking. Before a fork, the forking
thread's connections are closed in the parent, where they reopen on the next
use, and the child process opens connections of its own; connections that
other threads hold at the time of the fork are left untouched in the child.
Forking inside a :meth:`transact <.Cache.transact>` block is not supported.
On macOS, a Python that links the system SQLite library cannot open any
database in a forked child once the parent has used SQLite; that limitation
is not specific to DiskCache, and the ``spawn`` start method of
:mod:`multiprocessing`, the default on macOS, avoids it.

    >>> cache.close()
    >>> with Cache(cache.directory) as reference:
    ...     reference.set('key', 'value')
    True

Closed Cache objects will automatically re-open when accessed. But opening
Cache objects is relatively slow, and since all operations are atomic, may be
safely left open.

    >>> cache.close()
    >>> cache.get('key')  # Automatically opens, but slower.
    'value'

Set an item, get a value, and delete a key using the usual operators:

    >>> cache['key'] = 'value'
    >>> cache['key']
    'value'
    >>> 'key' in cache
    True
    >>> del cache['key']

There's also a :meth:`set <diskcache_community.Cache.set>` method with
additional keyword parameters: `expire`, `read`, and `tag`.

    >>> from io import BytesIO
    >>> cache.set('key', BytesIO(b'value'), expire=5, read=True, tag='data')
    True

In the example above: the key expires in 5 seconds, the value is read as a
file-like object, and tag metadata is stored with the key. Another method,
:meth:`get <diskcache_community.Cache.get>` supports querying extra information
with `default`, `read`, `expire_time`, and `tag` keyword parameters.

    >>> result = cache.get('key', read=True, expire_time=True, tag=True)
    >>> reader, timestamp, tag = result
    >>> print(reader.read().decode())
    value
    >>> type(timestamp).__name__
    'float'
    >>> print(tag)
    data

The return value is a tuple containing the value, expire time (seconds from
epoch), and tag. Because we passed ``read=True`` the value is returned as a
file-like object. A fourth keyword parameter, `store_time`, appends the time
the item was stored (seconds from epoch) as the last element of the tuple, so
the age of a cached item can be logged when it is used.

    >>> value, store_time = cache.get('key', store_time=True)
    >>> type(store_time).__name__
    'float'

Use :meth:`touch <.Cache.touch>` to update the expiration time of an item in
the cache.

    >>> cache.touch('key', expire=None)
    True
    >>> cache.touch('does-not-exist', expire=1)
    False

Like :meth:`set <diskcache_community.Cache.set>`, the method :meth:`add
<diskcache_community.Cache.add>` can be used to insert an item in the cache.
The item is inserted only if the key is not already present.

    >>> cache.add(b'test', 123)
    True
    >>> cache[b'test']
    123
    >>> cache.add(b'test', 456)
    False
    >>> cache[b'test']
    123

Item values can also be incremented and decremented using :meth:`incr
<diskcache_community.Cache.incr>` and :meth:`decr
<diskcache_community.Cache.decr>` methods.

    >>> cache.incr(b'test')
    124
    >>> cache.decr(b'test', 24)
    100

Increment and decrement methods also support a keyword parameter, `default`,
which will be used for missing keys. When ``None``, incrementing or
decrementing a missing key will raise a :exc:`KeyError`.

    >>> cache.incr('alice')
    1
    >>> cache.decr('bob', default=-9)
    -10
    >>> cache.incr('carol', default=None)
    Traceback (most recent call last):
        ...
    KeyError: 'carol'

Increment and decrement operations are atomic and assume the value may be
stored in a SQLite integer column. SQLite supports 64-bit signed integers.

Like :meth:`delete <diskcache_community.Cache.delete>` and :meth:`get
<diskcache_community.Cache.get>`, the method :meth:`pop
<diskcache_community.Cache.pop>` can be used to delete an item in the cache and
return its value.

    >>> cache.pop('alice')
    1
    >>> cache.pop('dave', default='does not exist')
    'does not exist'
    >>> cache.set('dave', 0, expire=None, tag='admin')
    True
    >>> result = cache.pop('dave', expire_time=True, tag=True)
    >>> value, timestamp, tag = result
    >>> value
    0
    >>> print(timestamp)
    None
    >>> print(tag)
    admin

The :meth:`pop <diskcache_community.Cache.pop>` operation is atomic and using
:meth:`incr <diskcache_community.Cache.incr>` together is an accurate method
for counting and dumping statistics in long-running systems. Unlike :meth:`get
<diskcache_community.Cache.get>` the `read` argument is not supported.

.. _tutorial-culling:

Another four methods remove items from the cache::

    >>> cache.clear()
    3
    >>> cache.reset('cull_limit', 0)       # Disable automatic evictions.
    0
    >>> for num in range(10):
    ...     _ = cache.set(num, num, expire=1e-9)  # Expire immediately.
    >>> len(cache)
    10
    >>> list(cache)
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
    >>> import time
    >>> time.sleep(1)
    >>> cache.expire()
    10

:meth:`Expire <diskcache_community.Cache.expire>` removes all expired keys from
the cache. Resetting the :ref:`cull_limit <tutorial-settings>` to zero will
disable culling during :meth:`set <diskcache_community.Cache.set>` and
:meth:`add <diskcache_community.Cache.add>` operations. Because culling is
performed lazily, the reported length of the cache includes expired items.
Iteration likewise includes expired items because it is a read-only operation.
To exclude expired items you must explicitly call :meth:`expire
<diskcache_community.Cache.expire>` which works regardless of the
:ref:`cull_limit <tutorial-settings>`.

    >>> for num in range(100):
    ...     _ = cache.set(num, num, tag='odd' if num % 2 else 'even')
    >>> cache.evict('even')
    50

.. _tutorial-tag-index:

:meth:`Evict <diskcache_community.Cache.evict>` removes all the keys with a
matching tag. The default tag is ``None``. Tag values may be any of integer,
float, string, bytes and None. To accelerate the eviction of items by tag, an
index can be created. To do so, initialize the cache with ``tag_index=True``.

    >>> cache.clear()
    50
    >>> for num in range(100):
    ...     _ = cache.set(num, num, tag=(num % 2))
    >>> cache.evict(0)
    50

Likewise, the tag index may be created or dropped using methods::

    >>> cache.drop_tag_index()
    >>> cache.tag_index
    0
    >>> cache.create_tag_index()
    >>> cache.tag_index
    1

But prefer initializing the cache with a tag index rather than explicitly
creating or dropping the tag index.

To manually enforce the cache's size limit, use the :meth:`cull
<diskcache_community.Cache.cull>` method. :meth:`Cull
<diskcache_community.Cache.cull>` begins by removing expired items from the
cache and then uses the eviction policy to remove items until the cache volume
is less than the size limit.

    >>> cache.clear()
    50
    >>> cache.reset('size_limit', int(1e6))
    1000000
    >>> cache.reset('cull_limit', 0)
    0
    >>> for count in range(1000):
    ...     cache[count] = b'A' * 1000
    >>> cache.volume() > int(1e6)
    True
    >>> cache.cull() > 0
    True
    >>> cache.volume() < int(1e6)
    True

Some users may defer all culling to a cron-like process by setting the
:ref:`cull_limit <tutorial-settings>` to zero and manually calling :meth:`cull
<diskcache_community.Cache.cull>` to remove items. Like :meth:`evict
<diskcache_community.Cache.evict>` and :meth:`expire
<diskcache_community.Cache.expire>`, calls to :meth:`cull
<diskache.Cache.cull>` will work regardless of the :ref:`cull_limit
<tutorial-settings>`.

:meth:`Clear <diskcache_community.Cache.clear>` simply removes all items from
the cache.

    >>> cache.clear() > 0
    True

Each of these methods is designed to work concurrent to others. None of them
block readers or writers in other threads or processes.

Caches may be iterated by either insertion order or sorted order. The default
ordering uses insertion order. To iterate by sorted order, use :meth:`iterkeys
<.Cache.iterkeys>`. The sort order is determined by the database which makes it
valid only for `str`, `bytes`, `int`, and `float` data types. Other types of
keys will be serialized which is likely to have a meaningless sorted order.

    >>> for key in 'cab':
    ...     cache[key] = None
    >>> list(cache)
    ['c', 'a', 'b']
    >>> list(cache.iterkeys())
    ['a', 'b', 'c']
    >>> cache.peekitem()
    ('b', None)
    >>> cache.peekitem(last=False)
    ('c', None)

To iterate keys with a matching tag, pass `tag` to :meth:`iterkeys
<.Cache.iterkeys>`. Filtering happens in the database without reading cached
values. Omitting `tag` includes all keys; ``tag=None`` selects untagged keys.
As with other iteration methods, expired items are included.

    >>> _ = cache.set('a', None, tag='letter')
    >>> _ = cache.set('c', None, tag='letter')
    >>> list(cache.iterkeys(tag='letter'))
    ['a', 'c']
    >>> list(cache.iterkeys(reverse=True, tag='letter'))
    ['c', 'a']
    >>> list(cache.iterkeys(tag=None))
    ['b']

If only the first or last item in insertion order is desired then
:meth:`peekitem <.Cache.peekitem>` is more efficient than using iteration.

Three additional methods use the sorted ordering of keys to maintain a
queue-like data structure within the cache. The :meth:`push <.Cache.push>`,
:meth:`pull <.Cache.pull>`, and :meth:`peek <.Cache.peek>` methods
automatically assign the key within the cache.

    >>> key = cache.push('first')
    >>> print(key)
    500000000000000
    >>> cache[key]
    'first'
    >>> _ = cache.push('second')
    >>> _ = cache.push('zeroth', side='front')
    >>> _, value = cache.peek()
    >>> value
    'zeroth'
    >>> key, value = cache.pull()
    >>> print(key)
    499999999999999
    >>> value
    'zeroth'

The `side` parameter supports access to either the ``'front'`` or ``'back'`` of
the cache. In addition, the `prefix` parameter can be used to maintain multiple
queue-like data structures within a single cache. When prefix is ``None``,
integer keys are used. Otherwise, string keys are used in the format
“prefix-integer”. Integer starts at 500 trillion. Like :meth:`set <.Cache.set>`
and :meth:`get <.Cache.get>`, methods :meth:`push <.Cache.push>`, :meth:`pull
<.Cache.pull>`, and :meth:`peek <.Cache.peek>` support cache metadata like the
expiration time and tag.

Lastly, three methods support metadata about the cache. The first is
:meth:`volume <diskcache_community.Cache.volume>` which returns the estimated
total size in bytes of the cache directory on disk.

    >>> cache.volume() < int(1e5)
    True

.. _tutorial-statistics:

The second is :meth:`stats <diskcache_community.Cache.stats>` which returns
cache hits and misses. Cache statistics must first be enabled.

    >>> cache.stats(enable=True)
    (0, 0)
    >>> for num in range(100):
    ...     _ = cache.set(num, num)
    >>> for num in range(150):
    ...     _ = cache.get(num)
    >>> hits, misses = cache.stats(enable=False, reset=True)
    >>> (hits, misses)
    (100, 50)

Cache statistics are useful when evaluating different :ref:`eviction policies
<tutorial-eviction-policies>`. By default, statistics are disabled as they
incur an extra overhead on cache lookups. Increment and decrement operations
are not counted in cache statistics.

The third is :meth:`check <diskcache_community.Cache.check>` which verifies
cache consistency. It can also fix inconsistencies and reclaim unused space.
The return value is a list of warnings.

    >>> warnings = cache.check()

Caches do not automatically remove the underlying directory where keys and
values are stored. The cache is intended to be persistent and so must be
deleted manually.

    >>> cache.close()
    >>> import shutil
    >>> try:
    ...     shutil.rmtree(cache.directory)
    ... except OSError:  # Windows wonkiness
    ...     pass

To permanently delete the cache, recursively remove the cache's directory.

.. _tutorial-fanoutcache:

FanoutCache
-----------

Built atop :class:`Cache <diskcache_community.Cache>` is
:class:`diskcache_community.FanoutCache` which automatically `shards` the
underlying database. `Sharding`_ is the practice of horizontally partitioning
data. Here it is used to decrease blocking writes. While readers and writers do
not block each other, writers block other writers. Therefore a shard for every
concurrent writer is suggested. This will depend on your scenario. The default
value is 8.

Another parameter, `timeout`, sets a limit on how long to wait for database
transactions. Transactions are used for every operation that writes to the
database. When the timeout expires, a :exc:`diskcache_community.Timeout` error
is raised internally. This `timeout` parameter is also present on
:class:`diskcache_community.Cache`. When a :exc:`Timeout
<diskcache_community.Timeout>` error occurs in :class:`Cache
<diskcache_community.Cache>` methods, the exception may be raised to the
caller. In contrast, :class:`FanoutCache <diskcache_community.FanoutCache>`
catches all timeout errors and aborts the operation. As a result, :meth:`set
<diskcache_community.FanoutCache.set>` and :meth:`delete
<diskcache_community.FanoutCache.delete>` methods may silently fail.

Most methods that handle :exc:`Timeout <diskcache_community.Timeout>`
exceptions also include a `retry` keyword parameter (default ``False``) to
automatically repeat attempts that timeout. The mapping interface operators:
:meth:`cache[key] <diskcache_community.FanoutCache.__getitem__>`,
:meth:`cache[key] = value <diskcache_community.FanoutCache.__setitem__>`, and
:meth:`del cache[key] <diskcache_community.FanoutCache.__delitem__>`
automatically retry operations when :exc:`Timeout
<diskcache_community.Timeout>` errors occur. :class:`FanoutCache
<diskcache_community.FanoutCache>` will never raise a :exc:`Timeout
<diskcache_community.Timeout>` exception. The default `timeout` is 0.010 (10
milliseconds).

    >>> from diskcache_community import FanoutCache
    >>> cache = FanoutCache(shards=4, timeout=1)

The example above creates a cache in a temporary directory with four shards and
a one second timeout. Operations will attempt to abort if they take longer than
one second. The remaining API of :class:`FanoutCache
<diskcache_community.FanoutCache>` matches :class:`Cache
<diskcache_community.Cache>` as described above.

The :class:`.FanoutCache` :ref:`size_limit <constants>` is used as the total
size of the cache. The size limit of individual cache shards is the total size
divided by the number of shards. In the example above, the default total size
is one gigabyte and there are four shards so each cache shard has a size limit
of 256 megabytes. Items that are larger than the size limit are immediately
culled.

Caches have an additional feature: :meth:`memoizing
<diskcache_community.FanoutCache.memoize>` decorator. The decorator wraps a
callable and caches arguments and return values.

    >>> from diskcache_community import FanoutCache
    >>> cache = FanoutCache()
    >>> @cache.memoize(typed=True, expire=1, tag='fib')
    ... def fibonacci(number):
    ...     if number == 0:
    ...         return 0
    ...     elif number == 1:
    ...         return 1
    ...     else:
    ...         return fibonacci(number - 1) + fibonacci(number - 2)
    >>> print(sum(fibonacci(value) for value in range(100)))
    573147844013817084100

The arguments to memoize are like those for `functools.lru_cache
<https://docs.python.org/3/library/functools.html#functools.lru_cache>`_ and
:meth:`Cache.set <.Cache.set>`. Remember to call :meth:`memoize
<.FanoutCache.memoize>` when decorating a callable. If you forget, then a
TypeError will occur::

    >>> @cache.memoize
    ... def test():
    ...     pass
    Traceback (most recent call last):
        ...
    TypeError: name cannot be callable

Observe the lack of parenthenses after :meth:`memoize
<diskcache_community.FanoutCache.memoize>` above.

The ``ignore`` argument leaves arguments out of the cache key. An integer
ignores the argument at that position and a string ignores the parameter with
that name, whether it is passed positionally or by keyword. Use it for
arguments that do not affect the result, like a database session:

    >>> @cache.memoize(ignore={'session'})
    ... def lookup(entity_id, session):
    ...     return entity_id
    >>> lookup(1, object()) == lookup(1, session=object())
    True

.. _`Sharding`: https://en.wikipedia.org/wiki/Shard_(database_architecture)

.. _tutorial-djangocache:

DjangoCache
-----------

:class:`diskcache_community.DjangoCache` uses :class:`FanoutCache
<diskcache_community.FanoutCache>` to provide a Django-compatible cache
interface. With :doc:`DiskCache <index>` installed, you can use
:class:`DjangoCache <diskcache_community.DjangoCache>` in your settings file.

.. code-block:: python

    CACHES = {
        'default': {
            'BACKEND': 'diskcache_community.DjangoCache',
            'LOCATION': '/path/to/cache/directory',
            'TIMEOUT': 300,
            # ^-- Django setting for default timeout of each key.
            'SHARDS': 8,
            'DATABASE_TIMEOUT': 0.010,  # 10 milliseconds
            # ^-- Timeout for each DjangoCache database transaction.
            'DISK': 'diskcache_community.Disk',
            # ^-- Disk type for serialization, see SafeDisk below.
            'OPTIONS': {
                'size_limit': 2 ** 30   # 1 gigabyte
            },
        },
    }

As with :class:`FanoutCache <diskcache_community.FanoutCache>` above, these
settings create a Django-compatible cache with eight shards and a 10ms timeout.
You can pass further settings via the ``OPTIONS`` mapping as shown in the
Django documentation. ``DISK`` names the :class:`Disk
<diskcache_community.Disk>` type or subclass used for serialization, as a class
or a dotted import path; see :ref:`SafeDisk <tutorial-safedisk>` for the
restricted alternative. Only the ``BACKEND`` and ``LOCATION`` keys are
necessary in the above example. The other keys simply display their default
value. :class:`DjangoCache <diskcache_community.DjangoCache>` will never raise
a :exc:`Timeout <diskcache_community.Timeout>` exception. But unlike
:class:`FanoutCache <diskcache_community.FanoutCache>`, the keyword parameter
`retry` defaults to ``True`` for :class:`DjangoCache
<diskcache_community.DjangoCache>` methods.

The API of :class:`DjangoCache <diskcache_community.DjangoCache>` is a superset
of the functionality described in the `Django documentation on caching`_ and
includes many :class:`FanoutCache <diskcache_community.FanoutCache>` features.

:class:`DjangoCache <diskcache_community.DjangoCache>` also works well with
`X-Sendfile` and `X-Accel-Redirect` headers.

.. code-block:: python

    from django.core.cache import cache

    def media(request, path):
        try:
            with cache.read(path) as reader:
                response = HttpResponse()
                response['X-Accel-Redirect'] = reader.name
                return response
        except KeyError:
            # Handle cache miss.

When values are :meth:`set <diskcache_community.DjangoCache.set>` using
``read=True`` they are guaranteed to be stored in files. The full path is
available on the file handle in the `name` attribute. Remember to also include
the `Content-Type` header if known.

.. _`Django documentation on caching`: https://docs.djangoproject.com/en/3.2/topics/cache/#the-low-level-cache-api

Deque
-----

:class:`diskcache_community.Deque` (pronounced "deck") uses a :class:`Cache
<diskcache_community.Cache>` to provide a `collections.deque
<https://docs.python.org/3/library/collections.html#collections.deque>`_-compatible
double-ended queue. Deques are a generalization of stacks and queues with fast
access and editing at both front and back sides. :class:`Deque
<diskcache_community.Deque>` objects use the :meth:`push <.Cache.push>`,
:meth:`pull <.Cache.pull>`, and :meth:`peek <.Cache.peek>` methods of
:class:`Cache <.Cache>` objects but never evict or expire items.

    >>> from diskcache_community import Deque
    >>> deque = Deque(range(5, 10))
    >>> deque.pop()
    9
    >>> deque.popleft()
    5
    >>> deque.appendleft('foo')
    >>> len(deque)
    4
    >>> type(deque.directory).__name__
    'str'
    >>> other = Deque(directory=deque.directory)
    >>> len(other)
    4
    >>> other.popleft()
    'foo'
    >>> thing = Deque('abcde', maxlen=3)
    >>> list(thing)
    ['c', 'd', 'e']

:class:`Deque <diskcache_community.Deque>` objects provide an efficient and
safe means of cross-thread and cross-process communication. :class:`Deque
<diskcache_community.Deque>` objects are also useful in scenarios where
contents should remain persistent or limitations prohibit holding all items in
memory at the same time. The deque uses a fixed amount of memory regardless of
the size or number of items stored inside it.

Index
-----

:class:`diskcache_community.Index` uses a :class:`Cache
<diskcache_community.Cache>` to provide a `mutable mapping
<https://docs.python.org/3/library/collections.abc.html#collections-abstract-base-classes>`_
and `ordered dictionary
<https://docs.python.org/3/library/collections.html#collections.OrderedDict>`_
interface. :class:`Index <diskcache_community.Index>` objects inherit all the
benefits of :class:`Cache <diskcache_community.Cache>` objects but never evict
or expire items.

    >>> from diskcache_community import Index
    >>> index = Index([('a', 1), ('b', 2), ('c', 3)])
    >>> 'b' in index
    True
    >>> index['c']
    3
    >>> del index['a']
    >>> len(index)
    2
    >>> other = Index(index.directory)
    >>> len(other)
    2
    >>> other.popitem(last=False)
    ('b', 2)

:class:`Index <diskcache_community.Index>` objects provide an efficient and
safe means of cross-thread and cross-process communication. :class:`Index
<diskcache_community.Index>` objects are also useful in scenarios where
contents should remain persistent or limitations prohibit holding all items in
memory at the same time. The index uses a fixed amount of memory regardless of
the size or number of items stored inside it.

.. _tutorial-transactions:

Transactions
------------

Transactions are implemented by the :class:`.Cache`, :class:`.Deque`, and
:class:`.Index` data types and support consistency and improved
performance. Use transactions to guarantee a group of operations occur
atomically. For example, to calculate a running average, the total and count
could be incremented together::

    >>> with cache.transact():
    ...     total = cache.incr('total', 123.45)
    ...     count = cache.incr('count')
    >>> total
    123.45
    >>> count
    1

And to calculate the average, the values could be retrieved together:

    >>> with cache.transact():
    ...     total = cache.get('total')
    ...     count = cache.get('count')
    >>> average = None if count == 0 else total / count
    >>> average
    123.45

Keep transactions as short as possible because within a transaction, no other
writes may occur to the cache. Every write operation uses a transaction and
transactions may be nested to improve performance. For example, a possible
implementation to set many items within the cache::

    >>> def set_many(cache, mapping):
    ...     with cache.transact():
    ...         for key, value in mapping.items():
    ...             cache[key] = value

By grouping all operations in a single transaction, performance may improve two
to five times. But be careful, a large mapping will block other concurrent
writers.

Transactions are not implemented by :class:`.FanoutCache` and
:class:`.DjangoCache` due to key sharding. Instead, a cache shard with
transaction support may be requested.

    >>> fanout_cache = FanoutCache()
    >>> tutorial_cache = fanout_cache.cache('tutorial')
    >>> username_queue = fanout_cache.deque('usernames')
    >>> url_to_response = fanout_cache.index('responses')

The cache shard exists in a subdirectory of the fanout-cache with the given
name.

.. _tutorial-recipes:

Recipes
-------

:doc:`DiskCache <index>` includes a few synchronization recipes for
cross-thread and cross-process communication:

* :class:`.Averager` -- maintains a running average like that shown above.
* :class:`.Lock`, :class:`.RLock`, and :class:`.BoundedSemaphore` -- recipes
  for synchronization around critical sections like those found in Python's
  `threading`_ and `multiprocessing`_ modules.
* :func:`throttle <.throttle>` -- function decorator to rate-limit calls to a
  function.
* :func:`barrier <.barrier>` -- function decorator to synchronize calls to a
  function.
* :func:`memoize_stampede <.memoize_stampede>` -- memoizing function decorator
  with cache stampede protection. Read :doc:`case-study-landing-page-caching`
  for a comparison of memoization strategies.

.. _threading: https://docs.python.org/3/library/threading.html
.. _multiprocessing: https://docs.python.org/3/library/multiprocessing.html

.. _tutorial-settings:

Settings
--------

A variety of settings are available to improve performance. These values are
stored in the database for durability and to communicate between processes.
Each value is cached in an attribute with matching name. Attributes are updated
using :meth:`reset <diskcache_community.Cache.reset>`. Attributes are set
during initialization when passed as keyword arguments.

* `size_limit`, default one gigabyte. The maximum on-disk size of the cache.
* `cull_limit`, default ten. The maximum number of keys to cull when adding a
  new item. Set to zero to disable automatic culling. Some systems may disable
  automatic culling in exchange for a cron-like job that regularly calls
  :meth:`cull <diskcache_community.Cache.cull>` in a separate process.
* `statistics`, default False, disabled. The setting to collect :ref:`cache
  statistics <tutorial-statistics>`.
* `tag_index`, default False, disabled. The setting to create a database
  :ref:`tag index <tutorial-tag-index>` for :meth:`evict
  <diskcache_community.Cache.evict>`.
* `eviction_policy`, default "least-recently-stored". The setting to determine
  :ref:`eviction policy <tutorial-eviction-policies>`.

The :meth:`reset <diskcache_community.FanoutCache.reset>` method accepts an
optional second argument that updates the corresponding value in the database.
The return value is the latest retrieved from the database. Notice that
attributes are updated lazily. Prefer idioms like :meth:`len
<diskcache_community.FanoutCache.__len__>`, :meth:`volume
<diskcache_community.FanoutCache.volume>`, and :meth:`keyword arguments
<diskcache_community.FanoutCache.__init__>` rather than using :meth:`reset
<diskcache_community.FanoutCache.reset>` directly.

    >>> cache = Cache(size_limit=int(4e9))
    >>> print(cache.size_limit)
    4000000000
    >>> cache.disk_min_file_size
    32768
    >>> cache.reset('cull_limit', 0)  # Disable automatic evictions.
    0
    >>> cache.set(b'key', 1.234)
    True
    >>> cache.count           # Stale attribute.
    0
    >>> cache.reset('count')  # Prefer: len(cache)
    1

More settings correspond to :ref:`Disk <tutorial-disk>` attributes. Each of
these may be specified when initializing the :ref:`Cache
<tutorial-cache>`. Changing these values will update the unprefixed attribute
on the :class:`Disk <diskcache_community.Disk>` object.

* `disk_min_file_size`, default 32 kilobytes. The minimum size to store a value
  in a file.
* `disk_pickle_protocol`, default highest Pickle protocol. The Pickle protocol
  to use for data types that are not natively supported.

An additional set of attributes correspond to SQLite pragmas. Changing these
values will also execute the appropriate ``PRAGMA`` statement. See the `SQLite
pragma documentation`_ for more details.

* `sqlite_auto_vacuum`, default 1, "FULL".
* `sqlite_cache_size`, default 8,192 pages.
* `sqlite_journal_mode`, default "wal".
* `sqlite_mmap_size`, default 64 megabytes.
* `sqlite_synchronous`, default 1, "NORMAL".

Each of these settings can passed to :class:`DjangoCache
<diskcache_community.DjangoCache>` via the ``OPTIONS`` key mapping. Always
measure before and after changing the default values. Default settings are
programmatically accessible at :data:`diskcache_community.DEFAULT_SETTINGS`.

.. _`SQLite pragma documentation`: https://www.sqlite.org/pragma.html

.. _tutorial-eviction-policies:

Eviction Policies
-----------------

:doc:`DiskCache <index>` supports four eviction policies each with different
tradeoffs for accessing and storing items.

* ``"least-recently-stored"`` is the default. Every cache item records the time
  it was stored in the cache. This policy adds an index to that field. On
  access, no update is required. Keys are evicted starting with the oldest
  stored keys. As :doc:`DiskCache <index>` was intended for large caches
  (gigabytes) this policy usually works well enough in practice.
* ``"least-recently-used"`` is the most commonly used policy. An index is added
  to the access time field stored in the cache database. On every access, the
  field is updated. This makes every access into a read and write which slows
  accesses.
* ``"least-frequently-used"`` works well in some cases. An index is added to
  the access count field stored in the cache database. On every access, the
  field is incremented. Every access therefore requires writing the database
  which slows accesses.
* ``"none"`` disables cache evictions. Caches will grow without bound. Cache
  items will still be lazily removed if they expire. The persistent data types,
  :class:`.Deque` and :class:`.Index`, use the ``"none"`` eviction policy. For
  :ref:`lazy culling <tutorial-culling>` use the :ref:`cull_limit <constants>`
  setting instead.

All clients accessing the cache are expected to use the same eviction
policy. The policy can be set during initialization using a keyword argument.

    >>> cache = Cache()
    >>> print(cache.eviction_policy)
    least-recently-stored
    >>> cache = Cache(eviction_policy='least-frequently-used')
    >>> print(cache.eviction_policy)
    least-frequently-used
    >>> print(cache.reset('eviction_policy', 'least-recently-used'))
    least-recently-used

Though the eviction policy is changed, the previously created indexes will not
be dropped. Prefer to always specify the eviction policy as a keyword argument
to initialize the cache.

.. _tutorial-disk:

Disk
----

:class:`diskcache_community.Disk` objects are responsible for serializing and
deserializing data stored in the cache. Serialization behavior differs between
keys and values. In particular, keys are always stored in the cache metadata
database while values are sometimes stored separately in files.

To customize serialization, you may pass in a :class:`Disk
<diskcache_community.Disk>` subclass to initialize the cache. All clients
accessing the cache are expected to use the same serialization. The default
implementation uses Pickle and the example below uses compressed JSON,
available for convenience as :class:`JSONDisk <diskcache_community.JSONDisk>`.

.. code-block:: python

    class JSONDisk(diskcache.Disk):
        def __init__(self, directory, compress_level=1, **kwargs):
            self.compress_level = compress_level
            super().__init__(directory, **kwargs)

        def put(self, key):
            json_bytes = json.dumps(key).encode('utf-8')
            data = zlib.compress(json_bytes, self.compress_level)
            return super().put(data)

        def get(self, key, raw):
            data = super().get(key, raw)
            return json.loads(zlib.decompress(data).decode('utf-8'))

        def store(self, value, read, key=UNKNOWN):
            if not read:
                json_bytes = json.dumps(value).encode('utf-8')
                value = zlib.compress(json_bytes, self.compress_level)
            return super().store(value, read, key=key)

        def fetch(self, mode, filename, value, read):
            data = super().fetch(mode, filename, value, read)
            if not read:
                data = json.loads(zlib.decompress(data).decode('utf-8'))
            return data

    with Cache(disk=JSONDisk, disk_compress_level=6) as cache:
        pass

Four data types can be stored natively in the cache metadata database:
integers, floats, strings, and bytes. Other datatypes are converted to bytes
via the Pickle protocol. Beware that integers and floats like ``1`` and ``1.0``
will compare equal as keys just as in Python. All other equality comparisons
will require identical types.

.. _tutorial-safedisk:

SafeDisk
........

The default :class:`Disk <diskcache_community.Disk>` reads pickled keys and
values back with :func:`pickle.load`, which runs whatever code a pickle asks
for. Anyone who can write into the cache directory can therefore run code in
every process that reads from it (CVE-2025-69872). :class:`SafeDisk
<diskcache_community.SafeDisk>` keeps the same on-disk format but closes that
path:

* Pickles are read with an unpickler that resolves only an allowlist of
  standard-library constructors: ``None``, ``bool``, ``int``, ``float``,
  ``complex``, ``str``, ``bytes``, ``bytearray``, ``list``, ``tuple``,
  ``dict``, ``set``, ``frozenset``, ``range``, ``slice``, ``OrderedDict``,
  ``defaultdict``, ``deque``, ``Counter``, ``date``, ``datetime``, ``time``,
  ``timedelta``, ``timezone``, ``Decimal``, ``Fraction`` and ``UUID``.
  Anything else raises :exc:`pickle.UnpicklingError` instead of running.
* A key or value outside the allowlist raises :exc:`TypeError` when it is
  written, so an application finds out immediately rather than at read time.
* File paths read from the database are confined to the cache directory and a
  path that escapes it raises :exc:`ValueError`.

Select it with the ``disk`` argument, which is not persisted, so every process
that opens the directory chooses for itself:

.. code-block:: python

    from diskcache_community import Cache, Deque, FanoutCache, Index, SafeDisk

    cache = Cache('/tmp/mycache', disk=SafeDisk)
    fanout = FanoutCache('/tmp/myfanout', disk=SafeDisk)
    deque = Deque(directory='/tmp/mydeque', disk=SafeDisk)
    index = Index('/tmp/myindex', disk=SafeDisk)

For :class:`DjangoCache <diskcache_community.DjangoCache>`, set ``'DISK':
'diskcache_community.SafeDisk'`` next to ``SHARDS`` and ``DATABASE_TIMEOUT`` in
the ``CACHES`` setting. Sub-containers created through :meth:`FanoutCache.cache
<diskcache_community.FanoutCache.cache>`, :meth:`deque
<diskcache_community.FanoutCache.deque>` and :meth:`index
<diskcache_community.FanoutCache.index>` use the fanout cache's disk unless
given their own.

A directory written with :class:`SafeDisk <diskcache_community.SafeDisk>` opens
with the default :class:`Disk <diskcache_community.Disk>` and the reverse, as
long as the values are within the allowlist. Some uses need the default
:class:`Disk <diskcache_community.Disk>` because their objects are outside it:
instances of your own classes, Django model instances and ``HttpResponse``
objects, datetimes whose ``tzinfo`` is a ``zoneinfo.ZoneInfo`` rather than a
``datetime.timezone``, and :meth:`memoize <diskcache_community.Cache.memoize>`
with ``typed=True``, which puts ``type`` objects into the cache key. Every
process that writes to a shared directory with the default :class:`Disk
<diskcache_community.Disk>` must be trusted, and a reader using
:class:`SafeDisk <diskcache_community.SafeDisk>` raises
:exc:`pickle.UnpicklingError` on those rows.

Instead of falling back to the default :class:`Disk
<diskcache_community.Disk>`, :meth:`SafeDisk.with_types
<diskcache_community.SafeDisk.with_types>` returns a :class:`SafeDisk
<diskcache_community.SafeDisk>` subclass that also allows your own classes
and every class defined in the modules you name. Everything else stays
refused, both when reading and when writing:

.. code-block:: python

    from diskcache_community import Cache, SafeDisk

    from myapp.models import Message, Point

    AppDisk = SafeDisk.with_types(
        Message,
        Point,
        modules=('litellm.types', 'openai.types'),
    )
    cache = Cache('/tmp/mycache', disk=AppDisk)

Classes given by name are matched by identity, so a subclass is refused
unless it is listed too. A module prefix allows only classes defined in that
module or below it: a pickle cannot reach a function, a module, or a class
that the trusted module merely imports, such as ``os.system`` through a module
that imports ``os``. Reading looks classes up only in modules that are already
imported and never imports one, so import the modules before reading. List
only plain data classes whose construction and ``__setstate__`` do nothing
more than store their fields, such as dataclasses, named tuples, enums and
pydantic models, because allowing a class lets a crafted pickle create
instances of it with any field values. numpy classes are refused: numpy
restores a dtype's internal flags from the pickle without checking them, so a
crafted array pickle can corrupt memory. Store arrays as bytes instead, for
example with ``numpy.save(buffer, array, allow_pickle=False)``. A write whose
value pickles a class outside the allowlist raises :exc:`TypeError` that names
the class. Calling ``with_types`` on the returned class adds to its allowlist,
and a cache that uses it can be pickled as usual.

.. _tutorial-read-only:

Read-Only Caches
----------------

Opening an existing cache writes nothing to it: settings are written only
when they differ from the stored ones, and the schema, triggers and tag index
are left alone when they already match. A cache directory kept as a test
fixture therefore stays byte-for-byte identical across runs, as long as the
eviction policy does not record access times and statistics are off.

A cache whose database file or directory is not writable opens read-only
without any argument, so a cache baked into a read-only container layer or a
read-only mount works for reads. The same can be requested for a writable
directory:

    >>> cache = Cache('/tmp/mycachedir')
    >>> cache['key'] = 'value'
    >>> cache.close()
    >>> snapshot = Cache('/tmp/mycachedir', read_only=True)
    >>> snapshot.read_only
    True
    >>> snapshot['key']
    'value'

Reads, iteration, ``len``, :meth:`volume <diskcache_community.Cache.volume>`,
:meth:`check <diskcache_community.Cache.check>`, memoized calls that hit and
the read-only methods of :class:`FanoutCache
<diskcache_community.FanoutCache>`, :class:`Deque <diskcache_community.Deque>`
and :class:`Index <diskcache_community.Index>` all work. Every method that
would write raises :exc:`ReadOnlyError <diskcache_community.ReadOnlyError>`, a
subclass of :exc:`sqlite3.OperationalError`, before anything is written:

    >>> snapshot['other'] = 'value'  # doctest: +IGNORE_EXCEPTION_DETAIL
    Traceback (most recent call last):
        ...
    ReadOnlyError: cache in '/tmp/mycachedir' is read-only
    >>> snapshot.close()

A read-only cache cannot record hits, misses or access times, so :meth:`stats
<diskcache_community.Cache.stats>` returns the stored counters without enabling
or resetting them, the ``least-recently-used`` and ``least-frequently-used``
policies read without updating, and expired items are skipped instead of
removed. The ``read_only`` argument is not a setting and is never persisted;
passing it through ``FanoutCache(directory, read_only=True)`` or the Django
``OPTIONS`` works the same way.

Two details of the file system. When the directory is writable, SQLite may
create the ``cache.db-shm`` and ``cache.db-wal`` files next to a read-only
database while reading it. When the directory is not writable, the database
is opened in SQLite's immutable mode, which skips those files and all
locking; that is safe only because nothing can write to that directory.

Caveats
-------

Though :doc:`DiskCache <index>` has a dictionary-like interface, Python's `hash
protocol`_ is not used. Neither the `__hash__` nor `__eq__` methods are used
for lookups. Instead lookups depend on the serialization method defined by
:class:`Disk <diskcache_community.Disk>` objects. For strings, bytes, integers,
and floats, equality matches Python's definition. But large integers and all
other types will be converted to bytes and the bytes representation will define
equality.

The default :class:`diskcache_community.Disk` serialization uses pickling for
both keys and values. Unfortunately, pickling produces inconsistencies
sometimes when applied to container data types like tuples. Two equal tuples
may serialize to different bytes objects using pickle. The likelihood of
differences is reduced by using `pickletools.optimize` but still
inconsistencies occur (`#54`_). The inconsistent serialized pickle values is
particularly problematic when applied to the key in the cache. Consider using
an alternative Disk type, like :class:`JSONDisk
<diskcache_community.JSONDisk>`, for consistent serialization of keys.

SQLite is used to synchronize database access between threads and processes and
as such inherits all SQLite caveats. Most notably SQLite is `not recommended`_
for use with Network File System (NFS) mounts. For this reason, :doc:`DiskCache
<index>` currently `performs poorly`_ on `Python Anywhere`_. Users have also
reported issues running inside of `Parallels`_ shared folders.

When the disk or database is full, a :exc:`sqlite3.OperationalError` will be
raised from any method that attempts to write data. Read operations will still
succeed so long as they do not cause any write (as might occur if cache
statistics are being recorded).

Asynchronous support using Python's ``async`` and ``await`` keywords and
`asyncio`_ module is blocked by a lack of support in the underlying SQLite
module. But it is possible to run :doc:`DiskCache <index>` methods in a
thread-pool executor asynchronously. For example::

    import asyncio

    async def set_async(key, val):
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(None, cache.set, key, val)
        result = await future
        return result

    asyncio.run(set_async('test-key', 'test-value'))

The cache :meth:`volume <diskcache_community.Cache.volume>` is based on the
size of the database that stores metadata and the size of the values stored in
files. It does not account the size of directories themselves or other
filesystem metadata. If directory count or size is a concern then consider
implementing an alternative :class:`Disk <diskcache_community.Disk>`.

.. _`#54`: https://github.com/grantjenks/python-diskcache/issues/54
.. _`hash protocol`: https://docs.python.org/library/functions.html#hash
.. _`not recommended`: https://www.sqlite.org/faq.html#q5
.. _`performs poorly`: https://www.pythonanywhere.com/forums/topic/1847/
.. _`Python Anywhere`: https://www.pythonanywhere.com/
.. _`Parallels`: https://www.parallels.com/
.. _`asyncio`: https://docs.python.org/3/library/asyncio.html

Implementation
--------------

:doc:`DiskCache <index>` is mostly built on SQLite and the filesystem. Some
techniques used to improve performance:

* Shard database to distribute writes.
* Leverage SQLite native types: integers, floats, unicode, and bytes.
* Use SQLite write-ahead-log so reads and writes don't block each other.
* Use SQLite memory-mapped pages to accelerate reads.
* Store small values in SQLite database and large values in files.
* Always use a SQLite index for queries.
* Use SQLite triggers to maintain key count and database size.
