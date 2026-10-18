"""Turn the benchmark JSON results into reST tables, charts and the docs page.

python report.py --results results/ --docs ../../docs
"""

import argparse
import glob
import json
import os
import re
import statistics
import textwrap

STORE_ORDER = [
    'cache',
    'fanout',
    'cache563',
    'pymemcache',
    'pylibmc',
    'redis',
    'lmdb',
    'sqlitedict',
    'shelve',
]
LABELS = {
    'cache': 'diskcache-community Cache',
    'fanout': 'diskcache-community FanoutCache(8)',
    'cache563': 'diskcache 5.6.3 Cache',
    'pymemcache': 'memcached, pymemcache',
    'pylibmc': 'memcached, pylibmc',
    'redis': 'Redis, redis-py',
    'lmdb': 'lmdb',
    'sqlitedict': 'sqlitedict',
    'shelve': 'shelve (dbm)',
}
DJANGO_ORDER = [
    'django-locmem',
    'django-diskcache',
    'django-diskcache563',
    'django-pymemcache',
    'django-pylibmc',
    'django-redis',
    'django-filebased',
    'django-db',
]
DJANGO_LABELS = {
    'django-locmem': 'LocMemCache',
    'django-diskcache': 'DjangoCache, diskcache-community',
    'django-diskcache563': 'DjangoCache, diskcache 5.6.3',
    'django-pymemcache': 'PyMemcacheCache',
    'django-pylibmc': 'PyLibMCCache',
    'django-redis': 'RedisCache',
    'django-filebased': 'FileBasedCache',
    'django-db': 'DatabaseCache (SQLite)',
}
COLORS = {
    'cache': '#0F766E',
    'fanout': '#2DD4BF',
    'cache563': '#94A3B8',
    'pymemcache': '#F59E0B',
    'pylibmc': '#D97706',
    'redis': '#DC2626',
    'lmdb': '#7C3AED',
    'sqlitedict': '#2563EB',
    'shelve': '#64748B',
}


def load(results_dir):
    """Results keyed by (workload, store) from the file name, which is the
    driver's name for the item: the two Django diskcache files share a store
    name inside."""
    docs = {}
    for path in sorted(glob.glob(os.path.join(results_dir, '*.json'))):
        with open(path) as reader:
            doc = json.load(reader)
        workload, store = os.path.basename(path)[: -len('.json')].split(
            '__', 1
        )
        if workload == 'django':
            store = 'django-' + store
        docs[(workload, store)] = doc
    return docs


def med(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def stat(doc, action, field, tier=None):
    """Median across runs of one statistic."""
    values = []
    for run in doc['runs']:
        block = run['tiers'][tier][action] if tier else run['ops'].get(action)
        if block:
            values.append(block[field])
    return med(values)


def spread(doc, action, field):
    values = [
        run['ops'][action][field]
        for run in doc['runs']
        if action in run['ops']
    ]
    return (min(values), max(values)) if values else (None, None)


def fmt_ns(value):
    if value is None:
        return 'n/a'
    us = value / 1000
    if us >= 1000:
        return '%.2f ms' % (us / 1000)
    return '%.1f µs' % us


def fmt_bytes(value):
    if value is None:
        return 'n/a'
    if value == 0:
        return 'server'
    for unit in ('B', 'KB', 'MB', 'GB'):
        if value < 1024:
            return '%.0f %s' % (value, unit)
        value /= 1024
    return '%.1f TB' % value


def list_table(title, header, rows, widths=None):
    out = ['.. list-table:: %s' % title, '   :header-rows: 1']
    if widths:
        out.append('   :widths: %s' % ' '.join(str(w) for w in widths))
    out.append('')
    for i, row in enumerate([header] + rows):
        for j, cell in enumerate(row):
            prefix = '   * - ' if j == 0 else '     - '
            out.append(prefix + str(cell))
    out.append('')
    return '\n'.join(out)


def op_table(docs, workload, action, title, stores=STORE_ORDER, labels=LABELS):
    rows = []
    for store in stores:
        doc = docs.get((workload, store))
        if not doc:
            continue
        p50 = stat(doc, action, 'p50')
        if p50 is None:
            continue
        lo, hi = spread(doc, action, 'p50')
        rows.append(
            [
                labels[store],
                fmt_ns(p50),
                '%s to %s' % (fmt_ns(lo), fmt_ns(hi)),
                fmt_ns(stat(doc, action, 'p90')),
                fmt_ns(stat(doc, action, 'p99')),
                fmt_ns(stat(doc, action, 'max')),
                '%d' % stat(doc, action, 'misses'),
            ]
        )
    return list_table(
        title,
        ['Store', 'p50', 'p50 across runs', 'p90', 'p99', 'max', 'misses'],
        rows,
        [30, 10, 18, 10, 10, 10, 8],
    )


def summary_table(docs, workload, title, stores=STORE_ORDER, labels=LABELS):
    rows = []
    for store in stores:
        doc = docs.get((workload, store))
        if not doc:
            continue
        footprint = fmt_bytes(med([r['footprint_bytes'] for r in doc['runs']]))
        if store == 'django-locmem':
            footprint = 'in memory'
        rows.append(
            [
                labels[store],
                '%.0f' % med([r['throughput_ops_s'] for r in doc['runs']]),
                '%.2f s' % med([r['elapsed_s'] for r in doc['runs']]),
                footprint,
            ]
        )
    return list_table(
        title,
        ['Store', 'ops per second', 'wall time', 'on disk after the run'],
        rows,
        [30, 14, 12, 20],
    )


def sizes_table(docs, tier, title):
    rows = []
    for store in STORE_ORDER:
        doc = docs.get(('sizes', store))
        if not doc or tier not in doc['runs'][0]['tiers']:
            continue
        rows.append(
            [
                LABELS[store],
                fmt_ns(stat(doc, 'set', 'p50', tier)),
                fmt_ns(stat(doc, 'set', 'p99', tier)),
                fmt_ns(stat(doc, 'get', 'p50', tier)),
                fmt_ns(stat(doc, 'get', 'p99', tier)),
            ]
        )
    return list_table(
        title,
        ['Store', 'set p50', 'set p99', 'get p50', 'get p99'],
        rows,
        [30, 12, 12, 12, 12],
    )


def hit_table(docs, title):
    rows = []
    for store in STORE_ORDER:
        d95, d50 = docs.get(('hit95', store)), docs.get(('hit50', store))
        if not (d95 and d50):
            continue
        rows.append(
            [
                LABELS[store],
                fmt_ns(stat(d95, 'get', 'p50')),
                fmt_ns(stat(d95, 'get', 'p99')),
                fmt_ns(stat(d50, 'get', 'p50')),
                fmt_ns(stat(d50, 'get', 'p99')),
                fmt_bytes(med([r['footprint_bytes'] for r in d95['runs']])),
            ]
        )
    return list_table(
        title,
        [
            'Store',
            '95 % hits p50',
            '95 % hits p99',
            '50 % hits p50',
            '50 % hits p99',
            'on disk',
        ],
        rows,
        [30, 12, 12, 12, 12, 12],
    )


def concurrency_table(docs, title):
    rows = []
    for store in STORE_ORDER:
        cells = [LABELS[store]]
        found = False
        for workload in ('classic', 'procs4', 'procs8', 'threads8'):
            doc = docs.get((workload, store))
            if doc:
                found = True
                cells.append(
                    '%s / %s'
                    % (
                        fmt_ns(stat(doc, 'get', 'p50')),
                        fmt_ns(stat(doc, 'set', 'p50')),
                    )
                )
            else:
                cells.append('not run')
        if found:
            rows.append(cells)
    return list_table(
        title,
        ['Store', '1 process', '4 processes', '8 processes', '8 threads'],
        rows,
        [30, 16, 16, 16, 16],
    )


def throughput_table(docs, title):
    rows = []
    for store in STORE_ORDER:
        cells = [LABELS[store]]
        found = False
        for workload in ('classic', 'procs4', 'procs8', 'threads8'):
            doc = docs.get((workload, store))
            if doc:
                found = True
                cells.append(
                    '%.0f' % med([r['throughput_ops_s'] for r in doc['runs']])
                )
            else:
                cells.append('not run')
        if found:
            rows.append(cells)
    return list_table(
        title,
        ['Store', '1 process', '4 processes', '8 processes', '8 threads'],
        rows,
        [30, 16, 16, 16, 16],
    )


# Rows of the fork-against-5.6.3 table: label, workload, the two store keys,
# what to compare, the action and the size tier.
FORK_ROWS = [
    (
        'Classic mix, get p50',
        'classic',
        'cache',
        'cache563',
        'p50',
        'get',
        None,
    ),
    (
        'Classic mix, set p50',
        'classic',
        'cache',
        'cache563',
        'p50',
        'set',
        None,
    ),
    (
        'Classic mix, delete p50',
        'classic',
        'cache',
        'cache563',
        'p50',
        'delete',
        None,
    ),
    (
        'Classic mix, ops per second',
        'classic',
        'cache',
        'cache563',
        'throughput',
        None,
        None,
    ),
    (
        '100-byte values, set p50',
        'sizes',
        'cache',
        'cache563',
        'p50',
        'set',
        '100 B',
    ),
    (
        '64 KB values, set p50',
        'sizes',
        'cache',
        'cache563',
        'p50',
        'set',
        '64 KB',
    ),
    (
        '1 MB values, set p50',
        'sizes',
        'cache',
        'cache563',
        'p50',
        'set',
        '1 MB',
    ),
    (
        '1 MB values, get p50',
        'sizes',
        'cache',
        'cache563',
        'p50',
        'get',
        '1 MB',
    ),
    ('95 % hits, get p50', 'hit95', 'cache', 'cache563', 'p50', 'get', None),
    (
        '8 processes, set p50',
        'procs8',
        'cache',
        'cache563',
        'p50',
        'set',
        None,
    ),
    (
        '8 threads, ops per second',
        'threads8',
        'cache',
        'cache563',
        'throughput',
        None,
        None,
    ),
    (
        'Django, get p50',
        'django',
        'django-diskcache',
        'django-diskcache563',
        'p50',
        'get',
        None,
    ),
    (
        'Django, set p50',
        'django',
        'django-diskcache',
        'django-diskcache563',
        'p50',
        'set',
        None,
    ),
]


def fork_table(docs, title):
    rows = []
    for label, workload, new, old, kind, action, tier in FORK_ROWS:
        new_doc, old_doc = docs.get((workload, new)), docs.get((workload, old))
        if not (new_doc and old_doc):
            continue
        if kind == 'throughput':
            values = [
                med([r['throughput_ops_s'] for r in doc['runs']])
                for doc in (old_doc, new_doc)
            ]
            cells = ['%.0f' % value for value in values]
        else:
            values = [
                stat(doc, action, kind, tier) for doc in (old_doc, new_doc)
            ]
            cells = [fmt_ns(value) for value in values]
        if None in values or not values[0]:
            continue
        change = (values[1] - values[0]) / values[0] * 100
        rows.append([label] + cells + ['%+.0f %%' % change])
    return list_table(
        title,
        ['Measure', 'diskcache 5.6.3', 'diskcache-community', 'change'],
        rows,
        [34, 18, 20, 10],
    )


# ---------------------------------------------------------------- charts


def chart_classic(docs, out_dir, workload='classic', name='classic'):
    import matplotlib

    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    actions = ['get', 'set', 'delete']
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.2), sharey=False)
    for ax, action in zip(axes, actions):
        stores = [
            s
            for s in STORE_ORDER
            if (workload, s) in docs
            and stat(docs[(workload, s)], action, 'p50')
        ]
        y = range(len(stores))
        for offset, field, alpha in (
            (-0.27, 'p50', 1.0),
            (0.0, 'p90', 0.7),
            (0.27, 'p99', 0.45),
        ):
            values = [
                stat(docs[(workload, s)], action, field) / 1000 for s in stores
            ]
            ax.barh(
                [i + offset for i in y],
                values,
                height=0.26,
                color=[COLORS[s] for s in stores],
                alpha=alpha,
                label=field,
            )
        ax.set_yticks(list(y))
        ax.set_yticklabels(
            [LABELS[s] for s in stores]
            if ax is axes[0]
            else [''] * len(stores),
            fontsize=8,
        )
        ax.invert_yaxis()
        ax.set_xscale('log')
        ax.set_xlabel('%s latency, µs (log), p50 dark to p99 light' % action)
        ax.grid(axis='x', alpha=0.3)
    fig.tight_layout()
    path = os.path.join(out_dir, 'bench-%s.png' % name)
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path


def chart_sizes(docs, out_dir):
    import matplotlib

    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    tiers = ['100 B', '8 KB', '64 KB', '1 MB']
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    for ax, action in zip(axes, ('set', 'get')):
        for store in STORE_ORDER:
            doc = docs.get(('sizes', store))
            if not doc:
                continue
            values = [stat(doc, action, 'p50', t) for t in tiers]
            if any(v is None for v in values):
                continue
            ax.plot(
                tiers,
                [v / 1000 for v in values],
                marker='o',
                color=COLORS[store],
                label=LABELS[store],
            )
        ax.set_yscale('log')
        ax.set_ylabel('%s p50, µs (log)' % action)
        ax.set_xlabel('value size')
        ax.grid(alpha=0.3)
    axes[1].legend(fontsize=7, loc='upper left')
    fig.tight_layout()
    path = os.path.join(out_dir, 'bench-sizes.png')
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path


def chart_throughput(docs, out_dir):
    import matplotlib

    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    workloads = [
        ('classic', '1 process'),
        ('procs4', '4 processes'),
        ('procs8', '8 processes'),
        ('threads8', '8 threads'),
    ]
    stores = [s for s in STORE_ORDER if ('classic', s) in docs]
    fig, ax = plt.subplots(figsize=(11, 4.2))
    width = 0.8 / len(workloads)
    for j, (workload, label) in enumerate(workloads):
        values = []
        for s in stores:
            doc = docs.get((workload, s))
            values.append(
                med([r['throughput_ops_s'] for r in doc['runs']]) if doc else 0
            )
        ax.bar(
            [i + (j - 1.5) * width for i in range(len(stores))],
            values,
            width=width,
            label=label,
            alpha=0.5 + 0.15 * j,
            color=[COLORS[s] for s in stores],
        )
    ax.set_xticks(range(len(stores)))
    ax.set_xticklabels(
        [LABELS[s] for s in stores], rotation=25, ha='right', fontsize=8
    )
    ax.set_ylabel('operations per second, all workers')
    ax.set_yscale('log')
    ax.grid(axis='y', alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    path = os.path.join(out_dir, 'bench-throughput.png')
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path


def chart_django(docs, out_dir):
    import matplotlib

    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    backends = [b for b in DJANGO_ORDER if ('django', b) in docs]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.2))
    for ax, action in zip(axes, ('get', 'set', 'delete')):
        y = range(len(backends))
        for offset, field, alpha in (
            (-0.27, 'p50', 1.0),
            (0.0, 'p90', 0.7),
            (0.27, 'p99', 0.45),
        ):
            values = [
                stat(docs[('django', b)], action, field) / 1000
                for b in backends
            ]
            ax.barh(
                [i + offset for i in y],
                values,
                height=0.26,
                color='#0F766E',
                alpha=alpha,
            )
        ax.set_yticks(list(y))
        ax.set_yticklabels(
            [DJANGO_LABELS[b] for b in backends]
            if ax is axes[0]
            else [''] * len(backends),
            fontsize=8,
        )
        ax.invert_yaxis()
        ax.set_xscale('log')
        ax.set_xlabel('%s latency, µs (log), p50 dark to p99 light' % action)
        ax.grid(axis='x', alpha=0.3)
    fig.tight_layout()
    path = os.path.join(out_dir, 'bench-django.png')
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path


# ------------------------------------------------------------------ page


def summary_section(docs):
    """The conclusions at the top of the page, each computed from the results
    and left out when its results are missing."""

    def p50(workload, store, action, tier=None):
        doc = docs.get((workload, store))
        return stat(doc, action, 'p50', tier) if doc else None

    def ops(workload, store):
        doc = docs.get((workload, store))
        if not doc:
            return None
        return med([r['throughput_ops_s'] for r in doc['runs']])

    lines = []
    get, put = p50('classic', 'cache', 'get'), p50('classic', 'cache', 'set')
    memcached_get = [
        p50('classic', s, 'get') for s in ('pymemcache', 'pylibmc')
    ]
    memcached_set = [
        p50('classic', s, 'set') for s in ('pymemcache', 'pylibmc')
    ]
    redis_get = p50('classic', 'redis', 'get')
    redis_set = p50('classic', 'redis', 'set')
    lmdb_set = p50('classic', 'lmdb', 'set')
    if get and None not in memcached_get and redis_get:
        others = [p50('classic', s, 'get') for s in STORE_ORDER[3:]]
        fastest = all(other is None or get <= other for other in others)
        lines.append(
            '- **Reads:** %s median in the classic mix%s, %.0f times faster'
            ' than memcached and %.0f times faster than Redis on the same'
            ' machine.'
            % (
                fmt_ns(get),
                ', the fastest store there' if fastest else '',
                min(memcached_get) / get,
                redis_get / get,
            )
        )
    hit_cache, hit_lmdb = p50('hit95', 'cache', 'get'), p50(
        'hit95', 'lmdb', 'get'
    )
    if hit_cache and hit_lmdb and hit_lmdb < hit_cache:
        lines.append(
            '- **Large working sets:** lmdb reads faster over 100,000 keys'
            ' (%s against %s at 95 %% hits).'
            % (fmt_ns(hit_lmdb), fmt_ns(hit_cache))
        )
    if put and None not in memcached_set and redis_set:
        lines.append(
            '- **Writes:** %s median, on par with memcached (%s to %s) and %.0f'
            ' times faster than Redis.'
            % (
                fmt_ns(put),
                fmt_ns(min(memcached_set)),
                fmt_ns(max(memcached_set)),
                redis_set / put,
            )
        )
    reads, writes = [], []
    for _label, workload, new, old, kind, action, tier in FORK_ROWS:
        if kind != 'p50':
            continue
        values = (
            p50(workload, old, action, tier),
            p50(workload, new, action, tier),
        )
        if None in values:
            continue
        if action == 'get':
            reads.append(abs(values[1] - values[0]))
        elif workload != 'django':
            writes.append(((values[0] - values[1]) / values[0] * 100, tier))
    if reads and writes:
        large = [change for change, tier in writes if tier == '1 MB']
        small = [change for change, tier in writes if tier != '1 MB']
        text = (
            '- **Against diskcache 5.6.3:** reads within %s, writes %.0f to %.0f %%'
            ' faster' % (fmt_ns(max(reads)), min(small), max(small))
        )
        if large:
            text += ', %.0f %% faster for 1 MB values' % large[0]
        lines.append(text + '.')
    fanout8, cache_threads, fanout_threads = (
        ops('procs8', 'fanout'),
        ops('threads8', 'cache'),
        ops('threads8', 'fanout'),
    )
    if fanout8 and cache_threads and fanout_threads:
        lines.append(
            '- **Concurrency:** FanoutCache(8) is the fastest setup across'
            ' processes, {:,.0f} operations per second from 8 processes; for 8'
            ' threads in one process use a single Cache ({:,.0f} against'
            ' {:,.0f}).'.format(fanout8, cache_threads, fanout_threads)
        )
    if lmdb_set:
        lines.append(
            '- **lmdb** writes take %s because its defaults flush to disk on'
            ' every write.' % fmt_ns(lmdb_set)
        )
    return '\n'.join(
        textwrap.fill(
            line.replace(' %', '\u00a0%'), 79, subsequent_indent='  '
        )
        for line in lines
    )


def environment_section(docs):
    env = next(iter(docs.values()))['environment']
    versions = []
    for store in STORE_ORDER:
        doc = docs.get(('classic', store))
        if doc:
            versions.append(
                '- %s: %s'
                % (LABELS[store], doc['store_version'] or 'standard library')
            )
    django = docs.get(('django', 'django-locmem'))
    if django:
        versions.append('- %s' % django['store_name'].replace(' locmem', ''))
    redis = re.search(r'v=([\d.]+)', env['redis'] or '')
    return '\n'.join(
        [
            '- memcached: %s' % env['memcached'].splitlines()[0]
            if env['memcached']
            else '- memcached: n/a',
            '- Redis: %s' % (redis.group(1) if redis else 'n/a'),
        ]
        + versions
    )


PAGE = """DiskCache Benchmarks
====================

{summary}

Environment
-----------

{environment}

diskcache-community and diskcache 5.6.3
---------------------------------------

The same workloads, run against the fork and against the last upstream
release in separate environments on the same machine. For latencies a negative
change favours the fork; for operations per second a positive one does.

{fork}

The classic mix
---------------

The workload of the original 2016 page, kept so the two can be compared: keys
drawn from a space of 100, values of up to about 600 bytes, 90 % gets, 9 %
sets and 1 % deletes, 100,000 operations after a 1,000-operation warm-up, in
one process. The ~1 % miss rate comes from gets after deletes.

.. image:: _static/benchmarks/bench-classic.png

{classic_get}
{classic_set}
{classic_delete}
{classic_summary}

Value sizes
-----------

Sets followed by gets at four value sizes. The 64 KB and 1 MB tiers cross
DiskCache's default 32 KB threshold above which values live in files next to
the database; memcached was started with its item size limit raised to 4 MB
for the 1 MB tier.

.. image:: _static/benchmarks/bench-sizes.png

{sizes_100b}
{sizes_8kb}
{sizes_64kb}
{sizes_1mb}

Hit ratio
---------

Gets over a working set of 100,000 keys with 256-byte values, 100,000
operations, at a 95 % and a 50 % hit ratio. Misses are requests for keys that
were never stored.

{hit}

Concurrency
-----------

The classic mix from 4 and 8 processes sharing one store, and from 8 threads
in one process, each worker running the full 100,000 operations. sqlitedict and
shelve are single-process stores by design and are left out of the process
workloads; shelve's dbm objects are bound to the thread that opened them, so it
is left out of the thread workload too. The memcached clients are not
thread-safe, so each thread gets its own connection, as pymemcache's
PooledClient and pylibmc's ThreadMappedPool hand out. Cells show get p50 /
set p50.

.. image:: _static/benchmarks/bench-throughput.png

{concurrency}
{throughput}

Django backends
---------------

The classic mix through Django's cache API with each backend in turn, which
adds Django's key building and versioning on top of every operation.
``DatabaseCache`` uses SQLite; ``RedisCache`` is Django's own backend.

.. image:: _static/benchmarks/bench-django.png

{django_get}
{django_set}
{django_delete}
{django_summary}

Running the benchmarks
----------------------

The scripts need memcached and redis-server on the path, a venv with
diskcache-community, pymemcache, pylibmc, redis, sqlitedict, lmdb and Django,
and a second venv with diskcache 5.6.3 and Django for the mainline column::

    python tests/benchmarks/driver.py --fork-python <venv>/bin/python \\
        --mainline-python <venv-563>/bin/python --out results/
    python tests/benchmarks/driver.py --django --fork-python <venv>/bin/python \\
        --mainline-python <venv-563>/bin/python --out results/
    python tests/benchmarks/report.py --results results/ --docs docs/

The driver starts and stops the servers, runs one store at a time, and the
report script writes this page and its charts.
"""


def build_page(docs):
    def dj(action, title):
        return op_table(
            docs, 'django', action, title, DJANGO_ORDER, DJANGO_LABELS
        )

    return PAGE.format(
        summary=summary_section(docs),
        environment=environment_section(docs),
        fork=fork_table(docs, 'diskcache-community against diskcache 5.6.3'),
        classic_get=op_table(
            docs, 'classic', 'get', 'Get latency, classic mix'
        ),
        classic_set=op_table(
            docs, 'classic', 'set', 'Set latency, classic mix'
        ),
        classic_delete=op_table(
            docs, 'classic', 'delete', 'Delete latency, classic mix'
        ),
        classic_summary=summary_table(
            docs, 'classic', 'Throughput and footprint, classic mix'
        ),
        sizes_100b=sizes_table(
            docs,
            '100 B',
            '100-byte values, 20,000 sets then 20,000 gets over 1,000 keys',
        ),
        sizes_8kb=sizes_table(
            docs,
            '8 KB',
            '8 KB values, 20,000 sets then 20,000 gets over 1,000 keys',
        ),
        sizes_64kb=sizes_table(
            docs,
            '64 KB',
            '64 KB values, 4,000 sets then 4,000 gets over 500 keys',
        ),
        sizes_1mb=sizes_table(
            docs, '1 MB', '1 MB values, 400 sets then 400 gets over 50 keys'
        ),
        hit=hit_table(docs, 'Get latency by hit ratio'),
        concurrency=concurrency_table(
            docs, 'Latency under concurrency, get p50 / set p50'
        ),
        throughput=throughput_table(
            docs, 'Operations per second, all workers together'
        ),
        django_get=dj('get', 'Get latency, Django backends'),
        django_set=dj('set', 'Set latency, Django backends'),
        django_delete=dj('delete', 'Delete latency, Django backends'),
        django_summary=summary_table(
            docs,
            'django',
            'Throughput and footprint, Django backends',
            DJANGO_ORDER,
            DJANGO_LABELS,
        ),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--results', required=True)
    parser.add_argument('--docs', required=True)
    args = parser.parse_args()
    docs = load(args.results)
    charts_dir = os.path.join(args.docs, '_static', 'benchmarks')
    os.makedirs(charts_dir, exist_ok=True)
    chart_classic(docs, charts_dir)
    chart_sizes(docs, charts_dir)
    chart_throughput(docs, charts_dir)
    if any(w == 'django' for w, _ in docs):
        chart_django(docs, charts_dir)
    page = build_page(docs)
    with open(os.path.join(args.docs, 'benchmarks.rst'), 'w') as writer:
        writer.write(page)
    print(
        'wrote',
        os.path.join(args.docs, 'benchmarks.rst'),
        'and charts in',
        charts_dir,
    )


if __name__ == '__main__':
    main()
