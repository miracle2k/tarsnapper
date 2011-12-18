==========
Tarsnapper
==========

A wrapper around tarsnap which does two things:

- Let's you define "backup jobs" (tarsnap invocations) in a config file,
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


The example tries to show most of the features.

- Configuration values defined on the root level outside of a job
  definition are used as default values for every job. The ``$name``
  placeholder will be replaced by the name of each job.

- The backup sources can be specified using ``sources``, which expects
  a list of source paths as children::

    sources:
       - /usr
       - /home/*/.ssh

  Or, if only a single path is needed, ``source`` can be used for
  simplicity::

    source: /var/lib/mysql

  As you can see, you may use glob patterns. The globbing is done by
  tarsnapper, not the shell. If you install the ``glob2`` library
  (``easy_install glob2``), you are also able to do recursive globbing:

    source: /home/me/Development/**/TODO

  Note: You may specify relative paths. They will be considered relative
  to the location of the configuration file.

- To exclude files from a backup set, use ``excludes`` or ``exclude``.
  These two options work exactly the same as ``sources`` or ``source``,
  respectively.

- Use ``target`` to specify the backup archive name, like you would using
  tarsnap directly. You want to use the ``$date`` placeholder, which will be
  replaced with the current timestamp at the time of the backup.

  If you define a global ``target`` value, then use the ``$name``
  placeholder, which will be replaced by the name of the backup job.

- ``deltas`` is a space-separated list of timespans which are used to
  determine which backups are kept and which are to be deleted, during
  the "expire" stage. Valid prefixes are ``s``, ``h`` and ``d``, for
  seconds, hours and days, respectively. See below for more details
  on how the expiring works.

- If you need to run something before a backup job, use ``exec_before``.
  The command will be run via a subshell. There is also ``exec_after``
  if you need to do cleanup.

- If you rename a backup job, specify a list of old names via
  ``alias``. When determining which existing archives belong to a
  backup job, archive names are also matched against the aliases.


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
