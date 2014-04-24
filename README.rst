==========
Tarsnapper
==========

A wrapper around tarsnap which does two things:

- Lets you define "backup jobs" (tarsnap invocations) in a config file,
  though on it's own this has little advantage over just using a a shell
  script.

- The ability to expire old backups using a Grandfather-father-son backup
  scheme. This feature can be used in conjunction with tarsnapper
  backup jobs, or standalone, to be applied to any existing set of
  tarsnap backup archives, regardless of how they have been created.


Installation
============

Using ``easy_install``::

    $ apt-get install python-setuptools
    $ easy_install tarsnapper


Using a configuration file
==========================

A configuration file looks like this::

    # Global values, valid for all jobs unless overridden:
    deltas: 1d 7d 30d
    target: /localmachine/$name-$date

    jobs:
      images:
        source: /var/lib/mysql
        exclude: /var/lib/mysql/temp
        exec_before: service stop mysql
        exec_after: service start mysql
        # Aliases can be used when renaming a job to match old archives.
        alias: img

      some-other-job:
        sources:
          - /var/dir/1
          - /etc/google
        excludes:
          - /etc/google/cache
        target: /custom-target-$date.zip
        deltas: 1h 6h 1d 7d 24d 180d

For the ``images`` job, the global target will be used, with the ``name``
placeholder replaced by the backup job name, in this case ``images``.

You can then ask tarsnapper to create new backups for each job::

    $ tarsnapper -c myconfigfile make

Or to expire those archives no longer needed, as per the chosen deltas::

  $ tarsnapper -c myconfigfile expire

If you need to pass arguments through to tarsnap, you can do this as well::

    $ tarsnapper -o configfile tarsnap.conf -o v -c tarsnapper.conf make

This will use ``tarsnap.conf`` as the tarsnap configuration file,
``tarnspapper.conf`` as the tarsnapper configuration file, and will also
put tarsnap into verbose mode via the ``-v`` flag.


Expiring backups
================

If you want to create the backups yourself, and are only interested in
the expiration functionality, you can do just that::

    $ tarsnapper --target "foobar-\$date" --deltas 1d 7d 30d - expire

The ``--target`` argument selects which set of backups to apply the expire
operation to. All archives that match this expression are considered
to be part of the same backup set that you want to operate on.

tarsnapper will then look at the date of each archive (this is why
you need the ``$date`` placeholder) and determine those which are not
needed to accomodate the given given delta range. It will parse the date
using the ``python-dateutil`` library, which supports a vast array of
different formats, though some restrictions apply: If you are using
``yyyy-dd-mm``, it cannot generally differentiate that from ``yyyy-mm-dd``.

Note the single "-" that needs to be given between the ``--deltas``
argument and the command.

The ``expire`` command supports a ``--dry-run`` argument that will allow
you to see what would be deleted::

    $ tarsnapper --target "foobar-\$date" --deltas 1d 7d 30d - expire --dry-run


How expiring backups works
==========================

The design goals for this were as follows:

* Do not require backup names to include information on which generation
  a backup belongs to, like for example ``tarsnap-generations`` does.
  That is, you can create your backups anyway you wish, and simply use
  this utility to delete old backups.

* Do not use any fixed generations (weekly, monthly etc), but freeform
  timespans.

* Similarily, do not make any assumptions about when or if backup jobs
  have actually run or will run, but try to match the given deltas as
  closely as possible.

The generations are defined by a list of deltas. ``60`` means a minute,
``12h`` is half a day, ``7d`` is a week. The number of backups in each
generation is implied by it's and the parent generation's delta.

For example, given the deltas ``1h 1d 7d``, the first generation will
consist of 24 backups each one hour older than the previous (or the closest
approximation possible given the available backups), the second generation
of 7 backups each one day older than the previous, and backups older than
7 days will be discarded for good.

The most recent backup is always kept.


Bonus: Support for xpect.io
===========================

`xpect.io`_ is a neat monitoring system that will trigger an exception if a
system does not check in regularly. tarsnapper has support for the service
builtin.

Two values are needed: The **expectation url** and the access key. Both
can be provided either on the command line, or at the global level in
the YAML file::

    xpect: https://xpect.io/v1/accounts/42/expectations/99
    xpect-key: 6173642377656633343b4b617364237

    jobs:
       ....


Additionally, the environment variable ``XPECTIO_ACCESS_KEY`` is supported.

.. _xpect.io: https://xpect.io/
