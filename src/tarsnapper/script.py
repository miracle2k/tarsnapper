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


def tarsnap_get_list(name, target, dateformat, options):
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

    return backups


def tarsnap_expire(name, deltas, target, dateformat, options, dryrun=False):
    """Call into tarsnap, parse the list of archives, then proceed to
    actually have tarsnap delete those archives we need to expire
    according to the deltas defined.

    If a dry run is wanted, set ``dryrun`` to a dict of the backups to
    pretend that exist (they will always be used, and not matched).
    """
    backups = tarsnap_get_list(name, target, dateformat, options)

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


class Command(object):

    def __init__(self, args, log):
        self.args = args
        self.log = log

    @classmethod
    def setup_arg_parser(self, parser):
        pass

    @classmethod
    def validate_args(self, args):
        pass

    def run(self, jobs):
        raise NotImplementedError()


class ListCommand(Command):

    help = 'list all the existing backups'
    description = 'For each job, output a sorted list of existing backups.'

    def run(self, jobs):
        for job_name, job in jobs.iteritems():
            self.log.info('%s' % job_name)

            # XXX: We seriouly need a way to minimize the number of
            # calls to tarsnap. It's not as simple as just doing a single
            # call though. We need to be sure that there's nothing in
            # tarsnap_options which could change the result. I guess
            # that's only the keyfile parameter, so we'd need to pay
            # attention to that.
            backups = tarsnap_get_list(job_name, job['target'],
                                       job['dateformat'],
                                       self.args.tarsnap_options,)

            backups = [(name, time) for name, time in backups.items()]
            backups.sort(cmp=lambda x, y: -cmp(x[1], y[1]))
            for backup, _ in backups:
                print "  %s" % backup


class ExpireCommand(Command):

    help = 'delete old backups, but don\'t create a new one'
    description = 'For each job defined, determine which backups can ' \
                  'be deleted according to the deltas, and then delete them.'

    @classmethod
    def setup_arg_parser(self, parser):
        parser.add_argument('--dry-run', dest='dryrun', action='store_true',
                            help='only simulate, don\'t delete anything')

    def expire(self, job_name, job, fake_backups=False):
        tarsnap_expire(job_name, job['deltas'], job['target'],
                       job['dateformat'], self.args.tarsnap_options,
                       fake_backups)

    def run(self, jobs):
        for job_name, job in jobs.iteritems():
            self.expire(job_name, job)


class MakeCommand(ExpireCommand):

    help = 'create a new backup, and afterwards expire old backups'
    description = 'For each job defined, make a new backup, then ' \
                  'afterwards delete old backups no longer required. '\
                  'If you need only the latter, see the separate ' \
                  '"expire" command.'

    @classmethod
    def setup_arg_parser(self, parser):
        parser.add_argument('--dry-run', dest='dryrun', action='store_true',
                            help='only simulate, make no changes',)
        parser.add_argument('--no-expire', dest='no_expire',
                            action='store_true', default=None,
                            help='don\'t expire, only make backups')

    @classmethod
    def validate_args(self, args):
        if not args.config and not args.target:
            raise ArgumentError('Since you are not using a config file, '\
                                'you need to give --target')
        if not args.config and not args.deltas and not args.no_expire:
            raise ArgumentError('Since you are not using a config file, and '\
                                'have not specified --no-expire, you will '
                                'need to give --deltas')
        if not args.config and not args.sources:
            raise ArgumentError('Since you are not using a config file, you '
                                'need to specify at least one source path '
                                'using --sources')

    def run(self, jobs):
        # validate that each job we run has a deltas, a target? this
        # could replace stuff in validate_args

        for job_name, job in jobs.iteritems():
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

            if sources_missing:
                if job_name:
                    self.log.info(("Not backing up '%s', because not all given "
                                   "sources exist") % job_name)
                else:
                    self.log.info("Not making backup, because not all given "
                                  "sources exist")
                skipped = True
            else:
                name, date = tarsnap_make(job_name, job['target'],
                                          job['sources'], job['dateformat'],
                                          self.args.tarsnap_options,
                                          self.args.dryrun)
                created_backups[name] = date

            # Expire old backups, but only bother if either we made a new
            # backup, or if expire was explicitly requested.
            if not skipped and not self.args.no_expire:
                self.expire(job_name, job,
                            created_backups if self.args.dryrun else False)


COMMANDS = {
    'make': MakeCommand,
    'expire': ExpireCommand,
    'list': ListCommand,
}


def parse_args(argv):
    """Parse the command line.
    """
    parser = argparse.ArgumentParser(
        description='An interface to tarsnap to manage backups.')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('-q', action='store_true', dest='quiet', help='be quiet')
    group.add_argument('-v', action='store_true', dest='verbose', help='be verbose')
    parser.add_argument('-o', metavar=('name', 'value'), nargs=2,
                        dest='tarsnap_options', default=[], action='append',
                        help='option to pass to tarsnap')
    parser.add_argument('--config', '-c', help='use the given config file')

    group = parser.add_argument_group(
        description='Instead of using a configuration file, you may define '\
                    'a single job on the command line:')
    group.add_argument('--target', help='target filename for the backup')
    group.add_argument('--sources', nargs='+', help='paths to backup',
                        default=[])
    group.add_argument('--deltas', '-d', metavar='DELTA',
                        type=timedelta_string,
                        help='generation deltas', nargs='+')
    group.add_argument('--dateformat', '-f', help='dateformat')

    # This will allow the user to break out of an nargs='*' to start
    # with the subcommand. See http://bugs.python.org/issue9571.
    parser.add_argument('-', dest='__dummy', action="store_true",
                        help=argparse.SUPPRESS)

    subparsers = parser.add_subparsers(
        title="commands", description="commands may offer additional options")
    for cmd_name, cmd_klass in COMMANDS.iteritems():
        subparser = subparsers.add_parser(cmd_name, help=cmd_klass.help,
                                          description=cmd_klass.description,
                                          add_help=False)
        subparser.set_defaults(command=cmd_klass)
        group = subparser.add_argument_group(
            title="optional arguments for this command")
        # We manually add the --help option so that we can have a
        # custom group title, but only show a single group.
        group.add_argument('-h', '--help', action='help',
                           default=argparse.SUPPRESS,
                           help='show this help message and exit')
        cmd_klass.setup_arg_parser(group)

        # Unfortunately, we need to redefine the jobs argument for each
        # command, rather than simply having it once, globally.
        subparser.add_argument(
            'jobs', metavar='job', nargs='*',
            help='only process the given job as defined in the config file')

    # This would be in a group automatically, but it would be shown as
    # the very first thing, while it really should be the last (which
    # explicitely defining the group causes to happen).
    #
    # Also, note that we define this argument for each command as well,
    # and the command specific one will actually be parsed. This is
    # because while argparse allows us to *define* this argument globally,
    # and renders the usage syntax correctly as well, it isn't actually
    # able to parse the thing it correctly (see
    # http://bugs.python.org/issue9540).
    group = parser.add_argument_group(title='positional arguments')
    group.add_argument(
        '__not_used', metavar='job', nargs='*',
        help='only process the given job as defined in the config file')

    args = parser.parse_args(argv)

    # Do some argument validation that would be to much to ask for
    # argparse to handle internally.
    if args.config and (args.target or args.dateformat or args.deltas or
                        args.sources):
        raise ArgumentError('If --config is used, then --target, --deltas, '
                            '--sources and --dateformat are not available')
    if args.jobs and not args.config:
        raise ArgumentError(('Specific jobs (%s) can only be given if a '
                            'config file is used') % ", ".join(args.jobs))
    # The command may want to do some validation regarding it's own options.
    args.command.validate_args(args)

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
        unknown = set(args.jobs) - set(jobs.keys())
        if unknown:
            log.fatal('Error: not defined in the config file: %s' % ", ".join(unknown))
            return 1
        jobs_to_run = dict([(n, j) for n, j in jobs.iteritems() if n in args.jobs])
    else:
        jobs_to_run = jobs

    command = args.command(args, log)
    try:
        command.run(jobs_to_run)
    except TarsnapError, e:
        log.fatal("tarsnap execution failed:\n%s" % e)
        return 1


def run():
    sys.exit(main(sys.argv[1:]) or 0)


if __name__ == '__main__':
    run()