DiskCache Development
=====================

:doc:`DiskCache <index>` is developed in the `GitHub repository`_ of the
diskcache-community fork. Questions and ideas go to `Discussions`_, bugs to
the `issue tracker`_.

Collaborators Welcome
---------------------

#. Search issues or open a new issue to start a discussion around a bug.
#. Fork the `GitHub repository`_ and make your changes in a new branch.
#. Write a test which shows the bug was fixed.
#. Send a pull request. It merges once CI is green and it has been reviewed.

.. _`GitHub repository`: https://github.com/secondwindoss/diskcache-community
.. _`Discussions`: https://github.com/secondwindoss/diskcache-community/discussions
.. _`issue tracker`: https://github.com/secondwindoss/diskcache-community/issues

Requests for Contributions
--------------------------

#. Command-line interface. Operations to support: get, set, store, delete,
   expire, evict, clear, path, check, stats.
#. Django admin interface for cache stats and interaction.
#. Cache stampede barrier (source prototype in repo).
#. API Compatibility

   #. `Shelf interface <https://docs.python.org/2/library/shelve.html>`_
   #. `DBM interface <https://docs.python.org/2/library/anydbm.html>`_

#. Backend Compatibility

   #. `Flask-Caching <https://flask-caching.readthedocs.io/>`_
   #. `Beaker <http://beaker.readthedocs.org/en/latest/>`_
   #. `dogpile.cache <http://dogpilecache.readthedocs.org/en/latest/>`_

Get the Code
------------

:doc:`DiskCache <index>` is actively developed in a `GitHub repository`_.

You can either clone the public repository::

    $ git clone https://github.com/secondwindoss/diskcache-community.git

Download the `tarball <https://github.com/secondwindoss/diskcache-community/tarball/master>`_::

    $ curl -OL https://github.com/secondwindoss/diskcache-community/tarball/master

Or, download the `zipball <https://github.com/secondwindoss/diskcache-community/zipball/master>`_::

    $ curl -OL https://github.com/secondwindoss/diskcache-community/zipball/master

Installing Dependencies
-----------------------

Install development dependencies with `pip <http://www.pip-installer.org/>`_::

    $ pip install -r requirements-dev.txt

All packages for running tests and the lint checks will be installed.

Additional packages like ``pylibmc`` and ``redis`` along with their server
counterparts are necessary for some benchmarks.

Testing
-------

:doc:`DiskCache <index>` tests against five versions of Python:

* CPython 3.10
* CPython 3.11
* CPython 3.12
* CPython 3.13
* CPython 3.14

Testing uses `tox <https://pypi.python.org/pypi/tox>`_. If you don't want to
install all the development requirements, then, after downloading, you can
simply run::

    $ tox

``tox -e py`` runs the test suite with `pytest <https://docs.pytest.org/>`_ in
the current interpreter. The options in the ``[pytest]`` section of
``tox.ini`` run the tests in parallel, collect the doctests from the ``.rst``
files and fail the run if branch coverage of the ``diskcache`` package drops
below 98%. The lint checks are tox environments as well::

    $ tox -e bluecheck,isortcheck,flake8,mypy,pylint,doc8,rstcheck,docs

`Read the Docs <https://diskcache-community.readthedocs.io/>`_ builds the
``docs`` directory from ``master`` on every push, configured by
``.readthedocs.yaml`` with the build dependencies in
``docs/requirements.txt``.

Stress tests can be run independently as a module. They are kept in the
tests directory and prefixed with ``stress_test_``. Stress tests accept many
arguments. Read the help for details.

::

   $ python -m tests.stress_test_core --help
   usage: stress_test_core.py [-h] [-n OPERATIONS] [-g GET_AVERAGE]
                              [-k KEY_COUNT] [-d DEL_CHANCE] [-w WARMUP]
                              [-e EXPIRE] [-t THREADS] [-p PROCESSES] [-s SEED]
                              [--no-create] [--no-delete] [-v EVICTION_POLICY]

   optional arguments:
     -h, --help            show this help message and exit
     -n OPERATIONS, --operations OPERATIONS
                           Number of operations to perform (default: 10000)
     -g GET_AVERAGE, --get-average GET_AVERAGE
                           Expected value of exponential variate used for GET
                           count (default: 100)
     -k KEY_COUNT, --key-count KEY_COUNT
                           Number of unique keys (default: 10)
     -d DEL_CHANCE, --del-chance DEL_CHANCE
                           Likelihood of a key deletion (default: 0.1)
     -w WARMUP, --warmup WARMUP
                           Number of warmup operations before timings (default:
                           10)
     -e EXPIRE, --expire EXPIRE
                           Number of seconds before key expires (default: None)
     -t THREADS, --threads THREADS
                           Number of threads to start in each process (default:
                           1)
     -p PROCESSES, --processes PROCESSES
                           Number of processes to start (default: 1)
     -s SEED, --seed SEED  Random seed (default: 0)
     --no-create           Do not create operations data (default: True)
     --no-delete           Do not delete operations data (default: True)
     -v EVICTION_POLICY, --eviction-policy EVICTION_POLICY

If stress exits normally then it worked successfully. Some stress is run by the
test suite but the iteration count is limited. More rigorous testing requires
increasing the iteration count to millions. At that level, it's best to just
let it run overnight. Stress testing will stop at the first failure.

Running Benchmarks
------------------

Running and plotting benchmarks is a two step process. Each is a Python script
in the tests directory. Benchmark scripts are prefixed with ``benchmark_``. For
example:

::

    $ python tests/benchmark_core.py --help
    usage: benchmark_core.py [-h] [-p PROCESSES] [-n OPERATIONS] [-r RANGE]
                             [-w WARMUP]

    optional arguments:
      -h, --help            show this help message and exit
      -p PROCESSES, --processes PROCESSES
                            Number of processes to start (default: 8)
      -n OPERATIONS, --operations OPERATIONS
                            Number of operations to perform (default: 100000)
      -r RANGE, --range RANGE
                            Range of keys (default: 100)
      -w WARMUP, --warmup WARMUP
                            Number of warmup operations before timings (default:
                            1000)

Benchmark output is stored in text files prefixed with ``timings_`` in the
`tests` directory. Plotting the benchmarks is done by passing the timings file
as an argument to ``plot.py``.
