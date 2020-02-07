Tarsnapper
=========

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

Using ``pip``:

    $ pip install tarsnapper


Making a single backup without a configuration file
===================================================

```sh
tarsnapper --target foobar-\$date --sources /etc/  --deltas 6h 7d 31d - make
```

This will backup the ``/etc/`` folder every time you call this command
(put it in cron, for example), and after each backup made, attempts to
expire old backups to match the deltas given.

Note the following:

- You need to give the ``$date`` placeholder for expiration to work,
  and you will need to escape the dollar sign in your shell.

- You need to end the list of deltas with a `-` character.

- ``tarsnap`` needs to be setup on your machine correctly, that is,
  tarsnap needs to be able to find it's keyfile and so on via
  ``tarsnap.conf``. The ability to pass through options to tarsnap
  via the ``tarsnapper`` CLI exists, though.


Using a configuration file
==========================

We also support a configuration file. It allows multiple jobs to be
defined, and has more feature, such as pre-/post job commands. It
looks like this:

```yaml
# Global values, valid for all jobs unless overridden:
# A job's delta controls when old backups are expired
# (see "How expiring backups works" below)
deltas: 1d 7d 30d
# You can avoid repetition by giving deltas names
delta-names:
  super-important: 1h 1d 30d 90d 360d
# A job's target sets the name of the created archive
target: /localmachine/$name-$date
# You can also include jobs from separate files
include-jobs: /usr/local/etc/tarsnapper/*.yml

jobs:
  # define a job called images (names must be unique)
  images:
    source: /var/lib/mysql
    exclude: /var/lib/mysql/temp
    exec_before: service mysql stop
    exec_after: service mysql start
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
```

For the ``images`` job, the global target will be used, with the ``name``
placeholder replaced by the backup job name, in this case ``images``.

You can then ask tarsnapper to create new backups for each job:

    $ tarsnapper -c myconfigfile make

The name of the archive will be the ``target`` option, with the ``$date``
placeholder replaced by the current timestamp, using either the
``dateformat`` option, or ``%Y%m%d-%H%M%S``.

Or to expire those archives no longer needed, as per the chosen deltas:

    $ tarsnapper -c myconfigfile expire

If you need to pass arguments through to tarsnap, you can do this as well:

    $ tarsnapper -o configfile tarsnap.conf -o v -c tarsnapper.conf make

This will use ``tarsnap.conf`` as the tarsnap configuration file,
``tarsnapper.conf`` as the tarsnapper configuration file, and will also
put tarsnap into verbose mode via the ``-v`` flag.

Using the ``include-jobs`` option, you could insert 1 or more jobs in (for
example) ``/usr/local/etc/tarsnapper/extra-backup-jobs.yml``:

```yaml
# Included jobs act just like jobs in the main config file, so for
# example the default target is active and named deltas are
# available, and job names must still be globally unique.
yet-another-job:
  source: /var/dir/2
  deltas: 1h 1d 30d

an-important-job:
  source: /var/something-important
  delta: super-important
```

``include-jobs`` uses [Python's globbing](https://docs.python.org/2/library/glob.html) to find job files and hence is subject to the limitations thereof.

Expiring backups
================

Note that if you're running tarsnapper with ``make``, it will implicitly expire
backups as well; there is no need to run ``make`` AND ``expire`` both.

If you want to create the backups yourself, and are only interested in
the expiration functionality, you can do just that:

    $ tarsnapper --target "foobar-\$date" --deltas 1d 7d 30d - expire

The ``--target`` argument selects which set of backups to apply the expire
operation to. All archives that match this expression are considered
to be part of the same backup set that you want to operate on.

tarsnapper will then look at the date of each archive (this is why
you need the ``$date`` placeholder) and determine those which are not
needed to accommodate the given given delta range. It will parse the date
using the ``python-dateutil`` library, which supports a vast array of
different formats, though some restrictions apply: If you are using
``yyyy-dd-mm``, it cannot generally differentiate that from ``yyyy-mm-dd``.

You can specify a custom dateformat using the ``--dateformat`` option,
which should be a format string as expected by the Python ``strptime``
function (e.g. ``%Y%m%d-%H%M%S``). Usually, a custom format is not
necessary.

Note the single "-" that needs to be given between the ``--deltas``
argument and the command.

The ``expire`` command supports a ``--dry-run`` argument that will allow
you to see what would be deleted:

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

The generations are defined by a list of deltas. ``60s`` means a minute,
``12h`` is half a day, ``7d`` is a week. The number of backups in each
generation is implied by it's and the parent generation's delta.

For example, given the deltas ``1h 1d 7d``, the first generation will
consist of 24 backups each one hour older than the previous (or the closest
approximation possible given the available backups), the second generation
of 7 backups each one day older than the previous, and backups older than
7 days will be discarded for good.

The most recent backup is always kept.

As an example, here is a list of backups from a Desktop computer that has
often been running non-stop for days, but also has on occasion been turned
off for weeks at a time, using the deltas ``1d 7d 30d 360d 18000d``:

      dropbox-20140424-054252
      dropbox-20140423-054120
      dropbox-20140422-053921
      dropbox-20140421-053920
      dropbox-20140420-054246
      dropbox-20140419-054007
      dropbox-20140418-060211
      dropbox-20140226-065032
      dropbox-20140214-063824
      dropbox-20140115-072109
      dropbox-20131216-100926
      dropbox-20131115-211256
      dropbox-20131012-054438
      dropbox-20130912-054731
      dropbox-20130813-090621
      dropbox-20130713-160422
      dropbox-20130610-054348
      dropbox-20130511-055537
      dropbox-20130312-064042
      dropbox-20120325-054505
      dropbox-20110331-12174
