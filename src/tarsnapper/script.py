import sys
import argparse
import subprocess
import re
from datetime import datetime, timedelta
import logging

import expire


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
    '%Y-%m-%dT%H:%M:%S.Z',
    '%Y%m%d-%H%M'
)

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


def tarsnap_expire(deltas, regex, dateformat, options):
    """Call into tarsnap, parse the list of archives, then proceed to
    actually have tarsnap delete those archives we need to expire
    according to the deltas defined.
    """
    regex = re.compile(regex)

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

    # Determine which backups we need to get rid of, which to keep
    to_keep = expire.expire(backups, deltas)
    log.info('%d of those can be deleted' % (len(backups)-len(to_keep)))

    # Delete all others
    for name, _ in backups.items():
        if not name in to_keep:
            log.info('Deleting %s' % name)
            call_tarsnap(['-d', '-f', name], options)
        else:
            log.debug('Keeping %s' % name)


def timedelta_string(value):
    """Parse a string to a timedelta value.
    """
    if value.endswith('s'):
        return timedelta(seconds=int(value[:-1]))
    elif value.endswith('h'):
        return timedelta(seconds=int(value[:-1]) * 3600)
    elif value.endswith('d'):
        return timedelta(days=int(value[:-1]))
    raise argparse.ArgumentTypeError('invalid delta value: %r (suffix d, s allowed)' % value)


def parse_args(argv):
    """Parse the command line.
    """
    parser = argparse.ArgumentParser(description='Make backups.')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('-q', action='store_true', dest='quiet', help='be quiet')
    group.add_argument('-v', action='store_true', dest='verbose', help='be verbose')
    parser.add_argument('--expire', action='store_true',
                        help='expire only, don\'t make backups')
    parser.add_argument('--config', '-c', help='use the given config file')
    parser.add_argument('--regex', help='regex to use to parse the date ' +
                        'from a backup filename.')
    parser.add_argument('--deltas', '-d', metavar='DELTA',
                        type=timedelta_string,
                        help='generation deltas', nargs='+')
    parser.add_argument('--dateformat', '-f', help='dateformat')
    parser.add_argument('-o', metavar=('name', 'value'), nargs=2,
                        dest='tarsnap_options', action='append', default=[],
                        help='option to pass to tarsnap')
    parser.add_argument('jobs', metavar='job', nargs='*')
    args = parser.parse_args(argv)

    # Do some argument validation that would be to much to ask for
    # argparse to handle internally.
    if not args.expire:
        raise ArgumentError('--expire is required, for now')
    if args.config:
        raise ArgumentError('--config is not yet supported')
    if args.config and (args.regex or args.dateformat or args.deltas):
        raise ArgumentError('If --config is used, then --regex, --deltas and '
                           '--dateformat are not available')
    if args.jobs and not args.config:
        raise ArgumentError(('Specific jobs (%s) can only be given if a '
                            'config file is used') % args.jobs)
    if not args.config and not args.deltas or not args.regex:
        raise ArgumentError('If no config file is used, both --regex and '
                           '--deltas need to be given')

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
    jobs = []
    if args.config:
        pass  # XXX
    else:
        # Only a single job, as given on the command line
        jobs.append({'regex': args.regex, 'dateformat': args.dateformat,
                     'deltas': args.deltas})

    for job in jobs:
        # Do a new backup
        if not args.expire:
            pass # XXX

        # Delete old backups
        try:
            tarsnap_expire(job['deltas'], job['regex'], job['dateformat'],
                           args.tarsnap_options)
        except TarsnapError, e:
            print "tarsnap execution failed:\n%s" % e
            return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]) or 0)