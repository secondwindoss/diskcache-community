"""Run the whole benchmark matrix.

    python driver.py --fork-python <venv-with-fork>/bin/python \
                     --mainline-python <venv-with-5.6.3>/bin/python \
                     --out results/ [--stores ...] [--workloads ...] [--runs 5]

The fork interpreter needs diskcache-community plus pymemcache, pylibmc,
redis, sqlitedict and lmdb; the mainline interpreter needs diskcache 5.6.3.
memcached and redis-server must be on PATH; they are started on their default
ports for the duration of the run, restarted if they die, and stopped
afterwards.  Every item runs in its own process group with a timeout, so a
hung store cannot stall the matrix.  Finished items are skipped on rerun.
"""

import argparse
import os
import signal
import socket
import subprocess
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ALL_STORES = [
    'cache',
    'fanout',
    'cache563',
    'pymemcache',
    'pylibmc',
    'redis',
    'sqlitedict',
    'shelve',
    'lmdb',
]
ALL_WORKLOADS = [
    'classic',
    'sizes',
    'hit95',
    'hit50',
    'procs4',
    'procs8',
    'threads8',
]
CONCURRENT = {'procs4', 'procs8', 'threads8'}
# single-process stores by design: one writer, no cross-process locking
SINGLE_PROCESS = {'sqlitedict', 'shelve'}
# shelve's dbm objects are bound to the thread that opened them
SINGLE_THREAD = {'shelve'}
SERVER_OF = {
    'pymemcache': 'memcached',
    'pylibmc': 'memcached',
    'redis': 'redis',
}
PORTS = {'memcached': 11211, 'redis': 6379}


def log(*parts):
    print(time.strftime('%H:%M:%S'), *parts, flush=True)


def port_open(port):
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(('127.0.0.1', port)) == 0


def wait_port(port, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_open(port):
            return True
        time.sleep(0.1)
    return False


class Servers:
    COMMANDS = {
        # memcached: default memory limit raised and item size raised to 4 MB for the 1 MB tier
        'memcached': ['memcached', '-p', '11211', '-m', '1024', '-I', '4m'],
        # redis: no persistence, so the comparison is memory-only like memcached
        'redis': [
            'redis-server',
            '--port',
            '6379',
            '--save',
            '',
            '--appendonly',
            'no',
            '--loglevel',
            'warning',
        ],
    }

    def __init__(self):
        self.procs = {}

    def start(self, name):
        self.procs[name] = subprocess.Popen(
            self.COMMANDS[name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if not wait_port(PORTS[name]):
            raise SystemExit('%s did not start' % name)

    def start_all(self):
        for name in self.COMMANDS:
            self.start(name)

    def ensure(self, name):
        """Restart the server if it died; return True when a restart happened."""
        proc = self.procs.get(name)
        if proc is not None and proc.poll() is None and port_open(PORTS[name]):
            return False
        log(
            'restart',
            name,
            '(exited with %s)' % (proc.poll() if proc else 'never started'),
        )
        self.start(name)
        return True

    def stop(self):
        for proc in self.procs.values():
            proc.terminate()
        for proc in self.procs.values():
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
        self.procs = {}


def run_item(cmd, timeout):
    """Run one benchmark process in its own process group; kill the group on timeout."""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        _out, err = proc.communicate(timeout=timeout)
        return proc.returncode, err
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        _out, err = proc.communicate()
        return (
            'timeout',
            (err or '') + '\nkilled after %d s timeout\n' % timeout,
        )


def run_one(label, name, cmd, out, timeout):
    t0 = time.time()
    code, err = run_item(cmd, timeout)
    status = 'ok' if code == 0 else 'FAILED (%s)' % code
    log('%-9s %-20s %-18s %7.1fs' % (label, name, status, time.time() - t0))
    if code != 0:
        with open(out + '.err', 'w') as writer:
            writer.write(err)
        print(err[-600:], flush=True)


DJANGO_BACKENDS = [
    'locmem',
    'filebased',
    'db',
    'pymemcache',
    'pylibmc',
    'redis',
    'diskcache',
]


def run_django(args, servers):
    jobs = [
        (backend, args.fork_python, 'django__' + backend)
        for backend in DJANGO_BACKENDS
    ]
    jobs.append(('diskcache', args.mainline_python, 'django__diskcache563'))
    for backend, python, name in jobs:
        out = os.path.join(args.out, name + '.json')
        if os.path.exists(out):
            log('skip', name, '(exists)')
            continue
        if backend in SERVER_OF:
            servers.ensure(SERVER_OF[backend])
        cmd = [
            python,
            '-I',
            os.path.join(HERE, 'django_bench.py'),
            '--backend',
            backend,
            '--runs',
            str(args.django_runs),
            '--out',
            out,
        ]
        run_one('django', name, cmd, out, args.item_timeout)


def run_matrix(args, servers):
    for workload in args.workloads.split(','):
        for store in args.stores.split(','):
            if store in SINGLE_PROCESS and workload.startswith('procs'):
                log('skip', workload, store, '(single-process store)')
                continue
            if store in SINGLE_THREAD and workload.startswith('threads'):
                log('skip', workload, store, '(single-thread store)')
                continue
            python = (
                args.mainline_python
                if store == 'cache563'
                else args.fork_python
            )
            out = os.path.join(args.out, '%s__%s.json' % (workload, store))
            if os.path.exists(out):
                log('skip', workload, store, '(exists)')
                continue
            if store in SERVER_OF:
                servers.ensure(SERVER_OF[store])
            runs = (
                args.concurrent_runs if workload in CONCURRENT else args.runs
            )
            cmd = [
                python,
                '-I',
                os.path.join(HERE, 'runner.py'),
                '--store',
                store,
                '--workload',
                workload,
                '--runs',
                str(runs),
                '--out',
                out,
            ]
            run_one(workload, store, cmd, out, args.item_timeout)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fork-python', required=True)
    parser.add_argument('--mainline-python', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--stores', default=','.join(ALL_STORES))
    parser.add_argument('--workloads', default=','.join(ALL_WORKLOADS))
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('--concurrent-runs', type=int, default=3)
    parser.add_argument(
        '--item-timeout',
        type=int,
        default=7200,
        help='seconds before one store/workload is killed',
    )
    parser.add_argument(
        '--django',
        action='store_true',
        help='run the Django backend matrix instead',
    )
    parser.add_argument('--django-runs', type=int, default=3)
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)
    servers = Servers()
    servers.start_all()
    log('servers up')
    try:
        if args.django:
            run_django(args, servers)
        else:
            run_matrix(args, servers)
    finally:
        servers.stop()
        log('servers down')


if __name__ == '__main__':
    main()
