"""The classic mix through Django's cache API, one backend per process.

    python django_bench.py --backend diskcache --runs 5 --out result.json

Backends: locmem, filebased, db (SQLite), pymemcache, pylibmc, redis
(Django's own backend), diskcache (diskcache-community if the interpreter holds
it, else upstream diskcache).
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import runner  # noqa: E402
from stores import diskcache_package  # noqa: E402


def configure(backend, workdir):
    import django
    from django.conf import settings

    caches = {
        'locmem': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'bench',
        },
        'filebased': {
            'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache',
            'LOCATION': os.path.join(workdir, 'filebased'),
        },
        'db': {
            'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
            'LOCATION': 'bench_cache_table',
        },
        'pymemcache': {
            'BACKEND': 'django.core.cache.backends.memcached.PyMemcacheCache',
            'LOCATION': '127.0.0.1:11211',
        },
        'pylibmc': {
            'BACKEND': 'django.core.cache.backends.memcached.PyLibMCCache',
            'LOCATION': '127.0.0.1:11211',
        },
        'redis': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': 'redis://127.0.0.1:6379/2',
        },
        'diskcache': {
            'BACKEND': diskcache_package().__name__ + '.DjangoCache',
            'LOCATION': os.path.join(workdir, 'diskcache'),
        },
    }
    settings.configure(
        CACHES={'default': caches[backend]},
        DATABASES={
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': os.path.join(workdir, 'db.sqlite3'),
            }
        },
        INSTALLED_APPS=[],
        USE_TZ=True,
    )
    django.setup()
    if backend == 'db':
        from django.core.management import call_command

        call_command('createcachetable', verbosity=0)
    from django.core.cache import cache

    return cache


class DjangoStore:
    """Adapter so the classic mix can drive Django's cache API."""

    def __init__(self, cache):
        self.cache = cache

    def get(self, key):
        return self.cache.get(key.decode())

    def set(self, key, value):
        self.cache.set(key.decode(), value)
        return True

    def delete(self, key):
        return self.cache.delete(key.decode())


def one_run(backend):
    workdir = tempfile.mkdtemp(prefix='bench-django-')
    cache = configure(backend, workdir)
    cache.clear()
    store = DjangoStore(cache)
    runner.prepopulate(store)
    t0 = time.perf_counter()
    timings, misses = runner.run_classic(store, seed=0)
    elapsed = time.perf_counter() - t0
    footprint = runner.stores.tree_size(workdir)
    cache.clear()
    try:
        cache.close()
    except Exception:  # noqa: BLE001
        pass
    shutil.rmtree(workdir, ignore_errors=True)
    return runner.summarise(timings, misses, elapsed, footprint)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backend', required=True)
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('--warmup-runs', type=int, default=1)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    # Django can be configured once per process, so every run is a child process.
    if os.environ.get('BENCH_DJANGO_CHILD'):
        print(json.dumps(one_run(args.backend)))
        return
    import subprocess

    runs = []
    env = dict(os.environ, BENCH_DJANGO_CHILD='1')
    for i in range(args.warmup_runs + args.runs):
        proc = subprocess.run(
            [
                sys.executable,
                '-I',
                __file__,
                '--backend',
                args.backend,
                '--out',
                args.out,
            ],
            env=env,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            sys.stderr.write(proc.stderr)
            raise SystemExit(proc.returncode)
        if i >= args.warmup_runs:
            runs.append(json.loads(proc.stdout.strip().splitlines()[-1]))
        print('run', i, 'done', file=sys.stderr)
    import django

    version = ''
    if args.backend == 'diskcache':
        diskcache = diskcache_package()

        version = '%s %s' % (diskcache.__title__, diskcache.__version__)
    doc = {
        'store': 'django-' + args.backend,
        'store_name': 'Django %s %s' % (django.get_version(), args.backend),
        'store_version': version,
        'workload': 'django',
        'runs': runs,
        'environment': runner.environment(),
        'ops': runner.OPS,
        'warmup': runner.WARMUP,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, 'w') as writer:
        json.dump(doc, writer, indent=1)


if __name__ == '__main__':
    main()
