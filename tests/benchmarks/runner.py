"""Run one store through one workload and write a JSON result.

    python runner.py --store cache --workload classic --runs 5 --out result.json

Workloads
    classic     the 2016 mix: keys from a space of 100, values up to ~600 B,
                90 % get, 9 % set, 1 % delete, 100k ops, 1k warm-up
    sizes       set then get at 100 B, 8 KB, 64 KB, 1 MB
    hit95       gets over a 100k-key working set with 95 % hits (the set is
                loaded in bulk, unmeasured)
    hit50       the same with 50 % hits
    procs4      the classic mix from 4 processes on one shared store
    procs8      the classic mix from 8 processes on one shared store
    threads8    the classic mix from 8 threads in one process (memcached
                clients get one connection per thread, as their pools do)

Every measured operation records its latency in nanoseconds; the result
holds the percentiles, the throughput, the miss rate and the disk footprint
of every run, plus the environment.
"""

import argparse
import datetime
import json
import multiprocessing
import os
import platform
import random
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stores  # noqa: E402

OPS = int(os.environ.get('BENCH_OPS', 100_000))
WARMUP = min(1_000, OPS // 10)
RANGE = 100
SIZES = [
    ('100 B', 100, 20_000, 1_000),
    ('8 KB', 8 * 1024, 20_000, 1_000),
    ('64 KB', 64 * 1024, 4_000, 500),
    ('1 MB', 1024 * 1024, 400, 50),
]
HIT_KEYS = int(os.environ.get('BENCH_HIT_KEYS', 100_000))


def percentiles(values):
    if not values:
        return None
    values = sorted(values)
    n = len(values)

    def pct(p):
        return values[min(n - 1, max(0, int(n * p) - 1))]

    return {
        'count': n,
        'p50': pct(0.50),
        'p90': pct(0.90),
        'p99': pct(0.99),
        'max': values[-1],
        'total_ns': sum(values),
    }


def classic_ops(seed, ops=OPS):
    """The 2016 operation sequence, one deterministic stream per seed."""
    rnd = random.Random(seed)
    for count in range(ops):
        key = str(rnd.randrange(RANGE)).encode()
        value = str(count).encode() * rnd.randrange(1, 100)
        choice = rnd.random()
        yield count, key, value, (
            'get' if choice < 0.9 else 'set' if choice < 0.99 else 'delete'
        )


def run_classic(store, seed, ops=OPS, warmup=WARMUP):
    timings = {'get': [], 'set': [], 'delete': []}
    misses = {'get': 0, 'set': 0, 'delete': 0}
    perf = time.perf_counter_ns
    for count, key, value, action in classic_ops(seed, ops):
        if action == 'get':
            start = perf()
            result = store.get(key)
            end = perf()
            miss = result is None
        elif action == 'set':
            start = perf()
            result = store.set(key, value)
            end = perf()
            miss = result is False
        else:
            start = perf()
            result = store.delete(key)
            end = perf()
            miss = result is False
        if count >= warmup:
            timings[action].append(end - start)
            if miss:
                misses[action] += 1
    return timings, misses


def prepopulate(store):
    for key in range(RANGE):
        store.set(str(key).encode(), str(key).encode())


def workload_classic(cls, workdir):
    store = cls(workdir)
    prepopulate(store)
    t0 = time.perf_counter()
    timings, misses = run_classic(store, seed=0)
    elapsed = time.perf_counter() - t0
    footprint = store.footprint()
    store.close()
    return summarise(timings, misses, elapsed, footprint)


def summarise(timings, misses, elapsed, footprint, extra=None):
    out = {'ops': {}, 'elapsed_s': elapsed, 'footprint_bytes': footprint}
    total = 0
    for action, values in timings.items():
        if not values:
            continue
        stats = percentiles(values)
        stats['misses'] = misses.get(action, 0)
        out['ops'][action] = stats
        total += len(values)
    out['throughput_ops_s'] = total / elapsed if elapsed else None
    if extra:
        out.update(extra)
    return out


def workload_sizes(cls, workdir):
    store = cls(workdir)
    rnd = random.Random(1)
    result = {'tiers': {}}
    perf = time.perf_counter_ns
    t0 = time.perf_counter()
    for label, size, ops, keys in SIZES:
        payload = os.urandom(size)
        key_list = [
            ('k%d-%s' % (i, label.replace(' ', ''))).encode()
            for i in range(keys)
        ]
        set_t, get_t, misses = [], [], 0
        for i in range(ops):
            key = key_list[i % keys]
            start = perf()
            store.set(key, payload)
            set_t.append(perf() - start)
        for i in range(ops):
            key = key_list[rnd.randrange(keys)]
            start = perf()
            value = store.get(key)
            get_t.append(perf() - start)
            if value is None:
                misses += 1
        result['tiers'][label] = {
            'size': size,
            'set': percentiles(set_t),
            'get': percentiles(get_t),
            'get_misses': misses,
        }
        store.clear()
    elapsed = time.perf_counter() - t0
    result['elapsed_s'] = elapsed
    result['footprint_bytes'] = store.footprint()
    store.close()
    return result


def workload_hit(cls, workdir, hit_ratio):
    store = cls(workdir)
    payload = os.urandom(256)
    keys = [('h%d' % i).encode() for i in range(HIT_KEYS)]
    # setup is not measured, so load the working set in bulk
    store.set_many([(key, payload) for key in keys])
    rnd = random.Random(2)
    perf = time.perf_counter_ns
    get_t, misses = [], 0
    t0 = time.perf_counter()
    for i in range(OPS):
        if rnd.random() < hit_ratio:
            key = keys[rnd.randrange(HIT_KEYS)]
        else:
            key = ('miss%d' % rnd.randrange(HIT_KEYS)).encode()
        start = perf()
        value = store.get(key)
        get_t.append(perf() - start)
        if value is None:
            misses += 1
    elapsed = time.perf_counter() - t0
    footprint = store.footprint()
    store.close()
    return summarise(
        {'get': get_t},
        {'get': misses},
        elapsed,
        footprint,
        {'hit_ratio_target': hit_ratio, 'working_set_keys': HIT_KEYS},
    )


def _proc_worker(store_key, workdir, seed, queue):
    cls = stores.STORES[store_key]
    time.sleep(0.05)
    store = cls(workdir)
    timings, misses = run_classic(store, seed=seed)
    store.close()
    queue.put((timings, misses))


def workload_procs(cls, workdir, nprocs, store_key):
    store = cls(workdir)
    prepopulate(store)
    store.close()
    ctx = multiprocessing.get_context('spawn')
    queue = ctx.Queue()
    procs = [
        ctx.Process(
            target=_proc_worker, args=(store_key, workdir, seed, queue)
        )
        for seed in range(nprocs)
    ]
    t0 = time.perf_counter()
    for p in procs:
        p.start()
    results = [queue.get() for _ in procs]
    for p in procs:
        p.join()
    elapsed = time.perf_counter() - t0
    timings = {'get': [], 'set': [], 'delete': []}
    misses = {'get': 0, 'set': 0, 'delete': 0}
    for t, m in results:
        for action in timings:
            timings[action].extend(t[action])
            misses[action] += m[action]
    store = cls(workdir)
    footprint = store.footprint()
    store.close()
    return summarise(
        timings, misses, elapsed, footprint, {'processes': nprocs}
    )


def workload_threads(cls, workdir, nthreads=8):
    store = cls(workdir)
    prepopulate(store)
    results = [None] * nthreads
    errors = []

    def worker(ident):
        try:
            handle = store.for_thread()
            try:
                results[ident] = run_classic(handle, seed=ident)
            finally:
                if handle is not store:
                    handle.close()
        except BaseException as exc:  # noqa: BLE001
            errors.append((ident, exc))

    threads = [
        threading.Thread(target=worker, args=(i,)) for i in range(nthreads)
    ]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - t0
    if errors:
        ident, exc = errors[0]
        raise RuntimeError('thread %d failed: %r' % (ident, exc)) from exc
    timings = {'get': [], 'set': [], 'delete': []}
    misses = {'get': 0, 'set': 0, 'delete': 0}
    for t, m in results:
        for action in timings:
            timings[action].extend(t[action])
            misses[action] += m[action]
    footprint = store.footprint()
    store.close()
    return summarise(
        timings, misses, elapsed, footprint, {'threads': nthreads}
    )


WORKLOADS = {
    'classic': lambda cls, d, k: workload_classic(cls, d),
    'sizes': lambda cls, d, k: workload_sizes(cls, d),
    'hit95': lambda cls, d, k: workload_hit(cls, d, 0.95),
    'hit50': lambda cls, d, k: workload_hit(cls, d, 0.50),
    'procs4': lambda cls, d, k: workload_procs(cls, d, 4, k),
    'procs8': lambda cls, d, k: workload_procs(cls, d, 8, k),
    'threads8': lambda cls, d, k: workload_threads(cls, d, 8),
}


def environment():
    def cmd(*args):
        try:
            return subprocess.run(
                args, capture_output=True, text=True, timeout=10
            ).stdout.strip()
        except Exception:  # noqa: BLE001
            return ''

    return {
        'date': datetime.date.today().isoformat(),
        'python': sys.version.split()[0],
        'implementation': platform.python_implementation(),
        'platform': platform.platform(),
        'machine': platform.machine(),
        'cpu': cmd('sysctl', '-n', 'machdep.cpu.brand_string')
        or platform.processor(),
        'cores': os.cpu_count(),
        'sqlite': sqlite3.sqlite_version,
        'memcached': cmd('memcached', '-V'),
        'redis': cmd('redis-server', '--version'),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--store', required=True, choices=sorted(stores.STORES)
    )
    parser.add_argument('--workload', required=True, choices=sorted(WORKLOADS))
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('--warmup-runs', type=int, default=1)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    cls = stores.STORES[args.store]
    workload = WORKLOADS[args.workload]
    runs = []
    for i in range(args.warmup_runs + args.runs):
        workdir = tempfile.mkdtemp(prefix='bench-%s-' % args.store)
        if cls.server:
            cls(workdir).clear()
        try:
            result = workload(cls, workdir, args.store)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        if i >= args.warmup_runs:
            runs.append(result)
        print('run', i, 'done', file=sys.stderr)
    doc = {
        'store': args.store,
        'store_name': cls.name,
        'store_version': cls.version(),
        'workload': args.workload,
        'runs': runs,
        'environment': environment(),
        'ops': OPS,
        'warmup': WARMUP,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, 'w') as writer:
        json.dump(doc, writer, indent=1)


if __name__ == '__main__':
    multiprocessing.freeze_support()
    main()
