Comparisons
===========

Comparisons to popular projects related to DiskCache.

Key-Value Stores
................

DiskCache is mostly a simple key-value store. Feature comparisons with four
other projects are shown in the tables below.

* `dbm`_ is part of Python's standard library and implements a generic
  interface to variants of the DBM database — dbm.gnu or dbm.ndbm. If none of
  these modules is installed, the slow-but-simple dbm.dumb is used.
* `shelve`_ is part of Python's standard library and implements a “shelf” as a
  persistent, dictionary-like object. The difference with “dbm” databases is
  that the values can be anything that the pickle module can handle.
* `sqlitedict`_ is a lightweight wrapper around Python's sqlite3 database with
  a simple, Pythonic dict-like interface and support for multi-thread
  access. Keys are arbitrary strings, values arbitrary pickle-able objects.
* `pickleDB`_ is a lightweight and simple key-value store. It is built upon
  Python's simplejson module and was inspired by Redis. It is licensed with the
  BSD three-clause license.

.. _`dbm`: https://docs.python.org/3/library/dbm.html
.. _`shelve`: https://docs.python.org/3/library/shelve.html
.. _`sqlitedict`: https://github.com/RaRe-Technologies/sqlitedict
.. _`pickleDB`: https://pythonhosted.org/pickleDB/

**Features**

================ ============= ========= ========= ============ ============
Feature          diskcache     dbm       shelve    sqlitedict   pickleDB
================ ============= ========= ========= ============ ============
Atomic?          Always        Maybe     Maybe     Maybe        No
Persistent?      Yes           Yes       Yes       Yes          Yes
Thread-safe?     Yes           No        No        Yes          No
Process-safe?    Yes           No        No        Maybe        No
Backend?         SQLite        DBM       DBM       SQLite       File
Serialization?   Customizable  None      Pickle    Customizable JSON
Data Types?      Mapping/Deque Mapping   Mapping   Mapping      Mapping
Ordering?        Insert/Sorted None      None      None         None
Eviction?        LRU/LFU/more  None      None      None         None
Vacuum?          Automatic     Maybe     Maybe     Manual       Automatic
Transactions?    Yes           No        No        Maybe        No
Multiprocessing? Yes           No        No        No           No
Forkable?        Yes           No        No        No           No
Metadata?        Yes           No        No        No           No
================ ============= ========= ========= ============ ============

**Quality**

================ ============= ========= ========= ============ ============
Project          diskcache     dbm       shelve    sqlitedict   pickleDB
================ ============= ========= ========= ============ ============
Tests?           Yes           Yes       Yes       Yes          Yes
Coverage?        Yes           Yes       Yes       Yes          No
Stress?          Yes           No        No        No           No
CI Tests?        Linux/Mac/Win Yes       Yes       Linux        No
Python?          3.10+         All       All       2/3          2/3
License?         Apache2       Python    Python    Apache2      3-Clause BSD
Docs?            Extensive     Summary   Summary   Readme       Summary
Benchmarks?      Yes           No        No        No           No
Sources?         GitHub        GitHub    GitHub    GitHub       GitHub
Pure-Python?     Yes           Yes       Yes       Yes          Yes
Server?          No            No        No        No           No
Integrations?    Django        None      None      None         None
================ ============= ========= ========= ============ ============

**Timings**

These are rough measurements. See :doc:`benchmarks` for more
rigorous data.

================ ============= ========= ========= ============ ============
Project          diskcache     dbm       shelve    sqlitedict   pickleDB
================ ============= ========= ========= ============ ============
get                      25 µs     36 µs     41 µs       513 µs        92 µs
set                     198 µs    900 µs    928 µs       697 µs     1,020 µs
delete                  248 µs    740 µs    702 µs     1,717 µs     1,020 µs
================ ============= ========= ========= ============ ============

Caching Libraries
.................

* `joblib.Memory`_ provides caching functions and works by explicitly saving
  the inputs and outputs to files. It is designed to work with non-hashable and
  potentially large input and output data types such as numpy arrays.
* `klepto`_ extends Python’s `lru_cache` to utilize different keymaps and
  alternate caching algorithms, such as `lfu_cache` and `mru_cache`. Klepto
  uses a simple dictionary-sytle interface for all caches and archives.

.. _`klepto`: https://pypi.org/project/klepto/
.. _`joblib.Memory`: https://joblib.readthedocs.io/en/latest/memory.html

Data Structures
...............

* `dict`_ is a mapping object that maps hashable keys to arbitrary
  values. Mappings are mutable objects. There is currently only one standard
  Python mapping type, the dictionary.
* `pandas`_ is a Python package providing fast, flexible, and expressive data
  structures designed to make working with “relational” or “labeled” data both
  easy and intuitive.
* `Sorted Containers`_ is an Apache2 licensed sorted collections library,
  written in pure-Python, and fast as C-extensions. Sorted Containers
  implements sorted list, sorted dictionary, and sorted set data types.

.. _`dict`: https://docs.python.org/3/library/stdtypes.html#typesmapping
.. _`pandas`: https://pandas.pydata.org/
.. _`Sorted Containers`: https://pypi.org/project/sortedcontainers/

Pure-Python Databases
.....................

* `ZODB`_ supports an isomorphic interface for database operations which means
  there's little impact on your code to make objects persistent and there's no
  database mapper that partially hides the database.
* `CodernityDB`_ is an open source, pure-Python, multi-platform, schema-less,
  NoSQL database and includes an HTTP server version, and a Python client
  library that aims to be 100% compatible with the embedded version.
* `TinyDB`_ is a tiny, document oriented database optimized for your
  happiness. If you need a simple database with a clean API that just works
  without lots of configuration, TinyDB might be the right choice for you.

.. _`ZODB`: http://www.zodb.org/
.. _`CodernityDB`: https://pypi.org/project/CodernityDB/
.. _`TinyDB`: https://tinydb.readthedocs.io/

Object Relational Mappings (ORM)
................................

* `Django ORM`_ provides models that are the single, definitive source of
  information about data and contains the essential fields and behaviors of the
  stored data. Generally, each model maps to a single SQL database table.
* `SQLAlchemy`_ is the Python SQL toolkit and Object Relational Mapper that
  gives application developers the full power and flexibility of SQL. It
  provides a full suite of well known enterprise-level persistence patterns.
* `Peewee`_ is a simple and small ORM. It has few (but expressive) concepts,
  making it easy to learn and intuitive to use. Peewee supports Sqlite, MySQL,
  and PostgreSQL with tons of extensions.
* `SQLObject`_ is a popular Object Relational Manager for providing an object
  interface to your database, with tables as classes, rows as instances, and
  columns as attributes.
* `Pony ORM`_ is a Python ORM with beautiful query syntax. Use Python syntax
  for interacting with the database. Pony translates such queries into SQL and
  executes them in the database in the most efficient way.

.. _`Django ORM`: https://docs.djangoproject.com/en/dev/topics/db/
.. _`SQLAlchemy`: https://www.sqlalchemy.org/
.. _`Peewee`: http://docs.peewee-orm.com/
.. _`SQLObject`: http://sqlobject.org/
.. _`Pony ORM`: https://ponyorm.com/

SQL Databases
.............

* `SQLite`_ is part of Python's standard library and provides a lightweight
  disk-based database that doesn’t require a separate server process and allows
  accessing the database using a nonstandard variant of the SQL query language.
* `MySQL`_ is one of the world’s most popular open source databases and has
  become a leading database choice for web-based applications. MySQL includes a
  standardized database driver for Python platforms and development.
* `PostgreSQL`_ is a powerful, open source object-relational database system
  with over 30 years of active development. Psycopg is the most popular
  PostgreSQL adapter for the Python programming language.
* `Oracle DB`_ is a relational database management system (RDBMS) from the
  Oracle Corporation. Originally developed in 1977, Oracle DB is one of the
  most trusted and widely used enterprise relational database engines.
* `Microsoft SQL Server`_ is a relational database management system developed
  by Microsoft. As a database server, it stores and retrieves data as requested
  by other software applications.

.. _`SQLite`: https://docs.python.org/3/library/sqlite3.html
.. _`MySQL`: https://dev.mysql.com/downloads/connector/python/
.. _`PostgreSQL`: http://initd.org/psycopg/
.. _`Oracle DB`: https://pypi.org/project/cx_Oracle/
.. _`Microsoft SQL Server`: https://pypi.org/project/pyodbc/

Other Databases
...............

* `Memcached`_ is free and open source, high-performance, distributed memory
  object caching system, generic in nature, but intended for use in speeding up
  dynamic web applications by alleviating database load.
* `Redis`_ is an open source, in-memory data structure store, used as a
  database, cache and message broker. It supports data structures such as
  strings, hashes, lists, sets, sorted sets with range queries, and more.
* `MongoDB`_ is a cross-platform document-oriented database program. Classified
  as a NoSQL database program, MongoDB uses JSON-like documents with
  schema. PyMongo is the recommended way to work with MongoDB from Python.
* `LMDB`_ is a lightning-fast, memory-mapped database. With memory-mapped
  files, it has the read performance of a pure in-memory database while
  retaining the persistence of standard disk-based databases.
* `BerkeleyDB`_ is a software library intended to provide a high-performance
  embedded database for key/value data. Berkeley DB is a programmatic toolkit
  that provides built-in database support for desktop and server applications.
* `LevelDB`_ is a fast key-value storage library written at Google that
  provides an ordered mapping from string keys to string values. Data is stored
  sorted by key and users can provide a custom comparison function.

.. _`Memcached`: https://pypi.org/project/python-memcached/
.. _`MongoDB`: https://api.mongodb.com/python/current/
.. _`Redis`: https://redis.io/clients#python
.. _`LMDB`: https://lmdb.readthedocs.io/
.. _`BerkeleyDB`: https://pypi.org/project/bsddb3/
.. _`LevelDB`: https://plyvel.readthedocs.io/
