"""Store adapters with one small interface: get, set, delete, close, clear,
footprint, version.  Keys and values are bytes.

Each adapter wraps the library the way its own documentation shows, with
default settings unless the comment says otherwise.
"""

import os
import sys


def diskcache_package():
    """Return the diskcache under test: the fork if installed, else upstream.

    The driver runs the same store in two interpreters, one holding
    diskcache-community (imported as diskcache_community) and one holding
    only diskcache 5.6.3 (imported as diskcache).
    """
    try:
        import diskcache_community as package
    except ImportError:
        import diskcache as package
    return package


def chunks(items, size):
    items = list(items)
    for start in range(0, len(items), size):
        yield items[start : start + size]


def tree_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


class Store:
    name = 'store'
    server = None  # 'memcached' or 'redis' when a server process is needed
    needs_fork_venv = False  # True for the diskcache-community adapters

    def __init__(self, workdir):
        self.workdir = workdir

    def get(self, key):
        raise NotImplementedError

    def set(self, key, value):
        raise NotImplementedError

    def set_many(self, items):
        """Bulk load for unmeasured setup; the default is one set per item."""
        for key, value in items:
            self.set(key, value)

    def delete(self, key):
        raise NotImplementedError

    def close(self):
        pass

    def clear(self):
        raise NotImplementedError

    def footprint(self):
        return tree_size(self.workdir)

    def for_thread(self):
        """The handle a worker thread should use; the shared store by default.

        Clients that are not thread-safe return a fresh connection, which is
        what their pooled variants hand out per thread.
        """
        return self

    @classmethod
    def version(cls):
        return ''


# ------------------------------------------------------------ diskcache


class DiskCacheCache(Store):
    name = 'diskcache.Cache'

    def __init__(self, workdir):
        diskcache = diskcache_package()

        super().__init__(workdir)
        self.cache = diskcache.Cache(workdir)

    def get(self, key):
        return self.cache.get(key)

    def set(self, key, value):
        return self.cache.set(key, value)

    def set_many(self, items):
        with self.cache.transact():
            for key, value in items:
                self.cache.set(key, value)

    def delete(self, key):
        return self.cache.delete(key)

    def close(self):
        self.cache.close()

    def clear(self):
        self.cache.clear()

    @classmethod
    def version(cls):
        diskcache = diskcache_package()

        return '%s %s' % (diskcache.__title__, diskcache.__version__)


class DiskCacheFanout(DiskCacheCache):
    name = 'diskcache.FanoutCache(shards=8, timeout=0.010)'

    def __init__(self, workdir):
        diskcache = diskcache_package()

        Store.__init__(self, workdir)
        self.cache = diskcache.FanoutCache(workdir, shards=8, timeout=0.010)


# ------------------------------------------------------------ memcached


class PyMemcache(Store):
    name = 'memcached (pymemcache)'
    server = 'memcached'

    def __init__(self, workdir):
        import pymemcache.client.base

        super().__init__(workdir)
        # wait for the server's reply on every command, as the other clients do
        self.client = pymemcache.client.base.Client(
            ('127.0.0.1', 11211), no_delay=True, default_noreply=False
        )

    def get(self, key):
        return self.client.get(key)

    def set(self, key, value):
        return self.client.set(key, value)

    def set_many(self, items):
        for chunk in chunks(items, 1000):
            self.client.set_many(dict(chunk), noreply=False)

    def for_thread(self):
        # pymemcache.Client is not thread-safe; PooledClient would do the same
        return PyMemcache(self.workdir)

    def delete(self, key):
        return self.client.delete(key, noreply=False)

    def close(self):
        self.client.close()

    def clear(self):
        self.client.flush_all()

    def footprint(self):
        return 0

    @classmethod
    def version(cls):
        import pymemcache

        return 'pymemcache %s' % pymemcache.__version__


class PyLibMC(Store):
    name = 'memcached (pylibmc)'
    server = 'memcached'

    def __init__(self, workdir):
        import pylibmc

        super().__init__(workdir)
        # the settings the 2016 benchmark used
        self.client = pylibmc.Client(
            ['127.0.0.1'],
            binary=True,
            behaviors={'tcp_nodelay': True, 'ketama': True},
        )

    def get(self, key):
        return self.client.get(key)

    def set(self, key, value):
        return self.client.set(key, value)

    def set_many(self, items):
        for chunk in chunks(items, 1000):
            self.client.set_multi(dict(chunk))

    def for_thread(self):
        # pylibmc.Client is not thread-safe; ThreadMappedPool clones one per thread
        return PyLibMC(self.workdir)

    def delete(self, key):
        return self.client.delete(key)

    def close(self):
        self.client.disconnect_all()

    def clear(self):
        self.client.flush_all()

    def footprint(self):
        return 0

    @classmethod
    def version(cls):
        import pylibmc

        return 'pylibmc %s, libmemcached %s' % (
            pylibmc.__version__,
            pylibmc.libmemcached_version,
        )


# ---------------------------------------------------------------- redis


class Redis(Store):
    name = 'redis (redis-py)'
    server = 'redis'

    def __init__(self, workdir):
        import redis

        super().__init__(workdir)
        self.client = redis.Redis(host='127.0.0.1', port=6379, db=1)

    def get(self, key):
        return self.client.get(key)

    def set(self, key, value):
        return self.client.set(key, value)

    def set_many(self, items):
        for chunk in chunks(items, 10000):
            self.client.mset(dict(chunk))

    def delete(self, key):
        return bool(self.client.delete(key))

    def close(self):
        self.client.close()

    def clear(self):
        self.client.flushdb()

    def footprint(self):
        return 0

    @classmethod
    def version(cls):
        import redis

        hiredis = (
            'with hiredis'
            if redis.utils.HIREDIS_AVAILABLE
            else 'without hiredis'
        )
        return 'redis-py %s %s' % (redis.__version__, hiredis)


# ------------------------------------------------------ embedded stores


class SqliteDict(Store):
    name = 'sqlitedict (autocommit)'

    def __init__(self, workdir):
        import sqlitedict

        super().__init__(workdir)
        os.makedirs(workdir, exist_ok=True)
        self.db = sqlitedict.SqliteDict(
            os.path.join(workdir, 'store.sqlite'), autocommit=True
        )

    def get(self, key):
        # UserDict.get checks membership first, so a concurrent delete from
        # another thread can surface as KeyError here
        try:
            return self.db[key.decode()]
        except KeyError:
            return None

    def set(self, key, value):
        self.db[key.decode()] = value
        return True

    def set_many(self, items):
        self.db.update((key.decode(), value) for key, value in items)

    def delete(self, key):
        try:
            del self.db[key.decode()]
        except KeyError:
            return False
        return True

    def close(self):
        self.db.close()

    def clear(self):
        self.db.clear()

    @classmethod
    def version(cls):
        import sqlitedict

        return 'sqlitedict %s' % sqlitedict.__version__


class Shelve(Store):
    name = 'shelve (dbm)'

    def __init__(self, workdir):
        import shelve

        super().__init__(workdir)
        os.makedirs(workdir, exist_ok=True)
        self.db = shelve.open(os.path.join(workdir, 'shelf'))

    def get(self, key):
        return self.db.get(key.decode())

    def set(self, key, value):
        self.db[key.decode()] = value
        return True

    def delete(self, key):
        try:
            del self.db[key.decode()]
        except KeyError:
            return False
        return True

    def close(self):
        self.db.close()

    def clear(self):
        self.db.clear()

    @classmethod
    def version(cls):
        import dbm
        import shelve
        import shutil
        import tempfile

        # open a throwaway shelf to see which dbm module this Python picks
        probe = tempfile.mkdtemp(prefix='bench-shelve-probe-')
        try:
            shelve.open(os.path.join(probe, 'shelf')).close()
            backend = dbm.whichdb(os.path.join(probe, 'shelf')) or 'unknown'
        finally:
            shutil.rmtree(probe, ignore_errors=True)
        return 'shelve over %s, Python %s' % (backend, sys.version.split()[0])


class Lmdb(Store):
    name = 'lmdb (py-lmdb)'

    def __init__(self, workdir):
        import lmdb

        super().__init__(workdir)
        os.makedirs(workdir, exist_ok=True)
        self.env = lmdb.open(workdir, map_size=4 * 2**30)

    def get(self, key):
        with self.env.begin() as txn:
            return txn.get(key)

    def set(self, key, value):
        with self.env.begin(write=True) as txn:
            return txn.put(key, value)

    def set_many(self, items):
        with self.env.begin(write=True) as txn:
            for key, value in items:
                txn.put(key, value)

    def delete(self, key):
        with self.env.begin(write=True) as txn:
            return txn.delete(key)

    def close(self):
        self.env.close()

    def clear(self):
        with self.env.begin(write=True) as txn:
            txn.drop(self.env.open_db(), delete=False)

    def footprint(self):
        # the data file is sparse up to map_size; count the used pages
        info = self.env.info()
        stat = self.env.stat()
        return stat['psize'] * (info['last_pgno'] + 1)

    @classmethod
    def version(cls):
        import lmdb

        return 'py-lmdb %s, liblmdb %s' % (
            lmdb.__version__,
            '.'.join(map(str, lmdb.version())),
        )


STORES = {
    'cache': DiskCacheCache,
    'fanout': DiskCacheFanout,
    'cache563': DiskCacheCache,  # run under the venv holding diskcache 5.6.3
    'pymemcache': PyMemcache,
    'pylibmc': PyLibMC,
    'redis': Redis,
    'sqlitedict': SqliteDict,
    'shelve': Shelve,
    'lmdb': Lmdb,
}
