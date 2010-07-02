import sys, os
from os import path
import uuid
import subprocess
import re
from string import Template
from datetime import datetime, timedelta
import logging
import argparse

import expire, config


log = logging.getLogger()


class ArgumentError(Exception):
    pass

class TarsnapError(Exception):
    pass


def call_tarsnap(arguments, options):
    """
    ``arguments`` is a single list of strings, ``options`` is a list of
    key value pairs.
    """
    call_with = ['tarsnap']
    call_with.extend(arguments)
    for key, value in options:
        call_with.extend(["--%s" % key, value])
    log.debug("Executing: %s" % " ".join(call_with))
    p = subprocess.Popen(call_with, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
    p.wait()
    if p.returncode != 0:
        raise TarsnapError('%s' % p.stderr.read())
    return p.stdout


DATE_FORMATS = (
    '%Y%m%d-%H%M%S',
    '%Y%m%d-%H%M',
)
DEFAULT_DATEFORMAT = '%Y%m%d-%H%M%S'

def parse_date(string, dateformat=None):
    """Parse a date string using either a list of builtin formats,
    or the given one.
    """
    for to_try in ([dateformat] if dateformat else DATE_FORMATS):
        try:
            return datetime.strptime(string, to_try)
        except ValueError:
            pass
    else:
        raise ValueError('"%s" is not a supported date format' % string)


def tarsnap_expire(name, deltas, target, dateformat, options, dryrun=False):
    """Call into tarsnap, parse the list of archives, then proceed to
    actually have tarsnap delete those archives we need to expire
    according to the deltas defined.

    If a dry run is wanted, set ``dryrun`` to a dict of the backups to
    pretend that exist (they will always be used, and not matched).
    """
    unique = uuid.uuid4().hex
    target = Template(target).substitute({'name': name, 'date': unique})
    regex = re.compile("^%s$" % re.escape(target).replace(unique, '(?P<date>.*?)'))

    # Build a list of existing backups
    response = call_tarsnap(['--list-archives'], options)
    backups = {}
    for backup_path in response.readlines():
        backup_path = backup_path.rstrip('\n\r')
        match = regex.match(backup_path)
        if not match:
            continue
        date = parse_date(match.groupdict()['date'], dateformat)
        backups[backup_path] = date
    log.info('%d backups are matching' % len(backups))

    # Use any fake backups for dry runs?
    if dryrun:
        backups.update(dryrun)

    # Determine which backups we need to get rid of, which to keep
    to_keep = expire.expire(backups, deltas)
    log.info('%d of those can be deleted' % (len(backups)-len(to_keep)))

    # Delete all others
    for name, _ in backups.items():
        if not name in to_keep:
            log.info('Deleting %s' % name)
            if dryrun in (False, None):
                call_tarsnap(['-d', '-f', name], options)
        else:
            log.debug('Keeping %s' % name)


def tarsnap_make(name, target_templ, sources, dateformat, options, dryrun=False):
    """Call tarsnap to make a backup, given the options.
    """
    now = datetime.utcnow()
    date_str = now.strftime(dateformat or DEFAULT_DATEFORMAT)
    target = Template(target_templ).safe_substitute({'date': date_str,
                                                     'name': name})

    if name:
        log.info('Creating backup %s: %s' % (name, target))
    else:
        log.info('Creating backup: %s' % target)
    if not dryrun:
        call_tarsnap(['-c', '-f', target] + sources, options)

    return target, now


def timedelta_string(value):
    """Parse a string to a timedelta value.
    """
    try:
        return config.str_to_timedelta(value)
    except ValueError, e:
        raise argparse.ArgumentTypeError('invalid delta value: %r (suffix d, s allowed)' % e)


def parse_args(argv):
    """Parse the command line.
    """
    parser = argparse.ArgumentParser(description='Make backups.')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('-q', action='store_true', dest='quiet', help='be quiet')
    group.add_argument('-v', action='store_true', dest='verbose', help='be verbose')
    parser.add_argument('--expire', action='store_true', dest='expire_only',
                        default=None, help='expire only, don\'t make backups')
    parser.add_argument('--no-expire', action='store_true',  default=None,
                        help='don\'t expire, only make backups')
    parser.add_argument('--config', '-c', help='use the given config file')
    parser.add_argument('--dry-run', help='only simulate, make no changes',
                        dest='dryrun', action='store_true')
    parser.add_argument('--target', help='target filename for the backup')
    parser.add_argument('--sources', nargs='+', help='paths to backup',
                        default=[])
    parser.add_argument('--deltas', '-d', metavar='DELTA',
                        type=timedelta_string,
                        help='generation deltas', nargs='+')
    parser.add_argument('--dateformat', '-f', help='dateformat')
    parser.add_argument('-o', metavar=('name', 'value'), nargs=2,
                        dest='tarsnap_options', default=[], action='append',
                        help='option to pass to tarsnap')
    parser.add_argument('jobs', metavar='job', nargs='*')
    args = parser.parse_args(argv)

    # Do some argument validation that would be to much to ask for
    # argparse to handle internally.
    if args.config and (args.target or args.dateformat or args.deltas or
                        args.sources):
        raise ArgumentError('If --config is used, then --target, --deltas, '
                            '--sources and --dateformat are not available')
    if args.jobs and not args.config:
        raise ArgumentError(('Specific jobs (%s) can only be given if a '
                            'config file is used') % args.jobs)
    if not args.config and (not args.deltas or not args.target):
        raise ArgumentError('If no config file is used, both --target and '
                           '--deltas need to be given')
    if not args.config and (not args.sources and not args.expire_only):
        raise ArgumentError('Unless --expire is given, you need to specify '
                            'at least one source path using --sources')
    if args.expire_only and args.no_expire:
        raise ArgumentError('Cannot specify both --expire and --no-expire')
    return args


def main(argv):
    try:
        args = parse_args(argv)
    except ArgumentError, e:
        print "Error: %s" % e
        return 1

    # Setup logging
    level = logging.WARNING if args.quiet else (
        logging.DEBUG if args.verbose else logging.INFO)
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(message)s"))
    log.setLevel(level)
    log.addHandler(ch)

    # Build a list of jobs, process them.
    if args.config:
        try:
            jobs = config.load_config_from_file(args.config)
        except config.ConfigError, e:
            log.fatal('Error loading config file: %s' % e)
            return 1
    else:
        # Only a single job, as given on the command line
        jobs = {None: {'target': args.target, 'dateformat': args.dateformat,
                       'deltas': args.deltas, 'sources': args.sources}}

    # Validate the requested list of jobs to run
    if args.jobs:
        for name in args.jobs:
            if not name in jobs:
                log.fatal('Job "%s" is not defined in the config file' % name)
                return 1

    for job_name, job in jobs.iteritems():
        if args.jobs and not job_name in args.jobs:
            continue

        try:
            # Determine whether we can run this job. If any of the sources
            # are missing, or any source directory is empty, we skip this job.
            sources_missing = False
            for source in job['sources']:
                if not path.exists(source):
                    sources_missing = True
                    break
                if path.isdir(source) and not os.listdir(source):
                    # directory is empty
                    sources_missing = True
                    break

            # Do a new backup
            created_backups = {}
            skipped = False
            if not args.expire_only:
                if sources_missing:
                    if job_name:
                        log.info(("Not backing up '%s', because not all given "
                                 "sources exist") % job_name)
                    else:
                        log.info("Not making backup, because not all given "
                                 "sources exist")
                    skipped = True
                else:
                  name, date = tarsnap_make(job_name, job['target'],
                                            job['sources'], job['dateformat'],
                                            args.tarsnap_options, args.dryrun)
                  created_backups[name] = date

            # Expire old backups, but only bother if either we made a new
            # backup, or if expire was explicitly requested.
            if (not skipped or args.expire_only) and not args.no_expire:
                # Delete old backups
                tarsnap_expire(job_name, job['deltas'], job['target'],
                               job['dateformat'], args.tarsnap_options,
                               created_backups if args.dryrun else False)
        except TarsnapError, e:
            log.fatal("tarsnap execution failed:\n%s" % e)
            return 1


def run():
    sys.exit(main(sys.argv[1:]) or 0)


if __name__ == '__main__':
    run()