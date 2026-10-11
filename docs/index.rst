DiskCache: Disk Backed Cache
============================

DiskCache is an Apache2 licensed disk and file backed cache library, written
in pure Python, and compatible with Django. It stores keys and values in a
SQLite database and in files next to it, is safe to share between threads and
processes, evicts by LRU, LFU and other policies, and ships ``Deque`` and
``Index`` containers plus recipes for memoization, locks and throttling.

This documentation describes `diskcache-community`_, a community fork of
`python-diskcache`_. The fork is published on PyPI as ``diskcache-community``
and imported as ``diskcache``. It keeps the public API, the ``cache.db``
schema and the file layout of the last upstream release, 5.6.3, so existing
cache directories keep working, and it carries the fix path for
CVE-2025-69872 through the opt-in :class:`SafeDisk <diskcache.SafeDisk>`.
The README in the repository explains why the fork exists and how to migrate.

Install it with pip, after removing the upstream ``diskcache`` package if it
is present::

    $ pip uninstall diskcache
    $ pip install diskcache-community

Start with the :doc:`tutorial` and keep the :doc:`api` at hand.

.. toctree::
   :maxdepth: 1

   tutorial
   cache-benchmarks
   djangocache-benchmarks
   case-study-web-crawler
   case-study-landing-page-caching
   sf-python-2017-meetup-talk
   comparisons
   api
   development

.. _`diskcache-community`: https://github.com/secondwindoss/diskcache-community
.. _`python-diskcache`: https://github.com/grantjenks/python-diskcache
