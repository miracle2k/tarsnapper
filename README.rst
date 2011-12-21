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


Basic usage
===========

Create backups based on the jobs defined in the configuration file (see
below for information about the config file format)::

    $ tarsnapper -c myconfigfile make


Specify a job on the command line: In this case, we use the "expire"
command, so no backups will be created, but only old backups deleted::

    $ tarsnapper --target "foobar-\$date" --deltas 1d 7d 30d - expire

The --target argument selects which set of backups to apply the expire
operation to. tarsnapper will try to match the archives it finds into
the given delta range, and will delete those which seem unnecessary.

Note the single "-" that needs to be given between the --deltas argument
and the command.

The ``expire`` command supports a ``--dry-run`` argument that will allow
you to see what would be deleted:

    $ tarsnapper --target "foobar-\$date" --deltas 1d 7d 30d - expire --dry-run


If you need to pass arguments through to tarsnap, you can do this as well:

    $ tarsnapper -o configfile tarsnap.conf -o v -c tarsnapper.conf make

This will use ``tarsnap.conf`` as the tarsnap configuration file,
``tarnspapper.conf`` as the tarsnapper configuration file, and will also
put tarsnap into verbose mode via the ``-v`` flag.


The config file
===============

Example::

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


How expiring backups works
==========================

The approach chosen tries to achieve the following:

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
