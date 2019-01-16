from __future__ import print_function

import argparse
from datetime import datetime
import getpass
from io import StringIO
import logging
import os
from os import path
from string import Template
import subprocess
import re
import sys
import uuid

import dateutil.parser
import pexpect

from . import config, expire
from .config import Job


class ArgumentError(Exception):
    pass


class TarsnapError(Exception):
    pass


class TarsnapBackend(object):
    """
    The code that calls the tarsnap executable.

    One of the reasons this is designed as a class is to allow the backend
    to mimimize the calls to "tarsnap --list-archives" by caching the result.
    """

    def __init__(self, log, options, dryrun=False):
        """
        ``options`` - options to pass to each tarsnap call
        (a list of key value pairs).

        In ``dryrun`` mode, the class will only pretend to make and/or
        delete backups. This is a global option rather than a method
        specific one, because once the cached list of archives is tainted
        with simulated data, you don't really want to run in non-dry mode.
        """
        self.log = log
        self.options = options
        self.dryrun = dryrun
        self._queried_archives = None
        self._known_archives = []
        self.key_passphrase = None

    def call(self, *arguments):
        """
        ``arguments`` is a single list of strings.
        """
        call_with = ['tarsnap']
        for option in self.options:
            key = option[0]
            pre = "-" if len(key) == 1 else "--"
            call_with.append("%s%s" % (pre, key))
            for value in option[1:]:
                call_with.append(value)
        call_with.extend(arguments)
        return self._exec_tarsnap(call_with)

    def _exec_tarsnap(self, args):
        self.log.debug("Executing: %s", " ".join(args))
        env = os.environ
        child = pexpect.spawn(args[0], args[1:], env=env, timeout=None,
                              encoding='utf-8')

        if self.log.isEnabledFor(logging.DEBUG):
            child.logfile = sys.stdout

        # look for the passphrase prompt
        has_prompt = (child.expect([u'Please enter passphrase for keyfile .*?:', pexpect.EOF]) == 0)
        if has_prompt:
            child.sendline(self._get_key_passphrase())
            child.expect(pexpect.EOF)
        out = child.before
        child.close()

        if child.exitstatus != 0:
            raise TarsnapError("tarsnap failed with status {0}:{1}{2}".format(
                        child.exitstatus, os.linesep, out))
        return out

    def _get_key_passphrase(self):
        if not self.key_passphrase:
            self.key_passphrase = getpass.getpass('Passphrase for the tarsnap key: ')
        return self.key_passphrase

    def _exec_util(self, cmdline, shell=False):
        # TODO: can this be merged with _exec_tarsnap into something generic?
        self.log.debug("Executing: %s", cmdline)
        p = subprocess.Popen(cmdline, shell=True)
        p.communicate()
        if p.returncode:
            raise RuntimeError('%s failed with exit code %s' % (
                cmdline, p.returncode))

    def _add_known_archive(self, name):
        """If we make a backup, store it's name in a separate list.

        This list can be combined with the one read from the server. This
        means that when we create a new backup, we subsequently don't need
        to requery the server.
        """
        self._known_archives.append(name)

    def get_archives(self):
        """A list of archives as returned by --list-archives. Queried
        the first time it is accessed, and then subsequently cached.
        """
        if self._queried_archives is None:
            response = StringIO(self.call('--list-archives'))
            self._queried_archives = [l.rstrip() for l in response.readlines()]
            if ['v'] in self.options:
                # Filter out extraneous info if tarsnap was run with
                # verbose flag
                self._queried_archives = [
                    l.rsplit('\t', 1)[0] for l in self._queried_archives]
        return self._queried_archives + self._known_archives
    archives = property(get_archives)

    def get_backups(self, job):
        """Return a dict of backups that exist for the given job, by
        parsing the list of archives.
        """
        # Assemble regular expressions that match the job's target
        # filenames, including those based on it's aliases.
        unique = uuid.uuid4().hex
        regexes = []
        for possible_name in [job.name] + (job.aliases or []):
            target = Template(job.target).substitute(
                {'name': possible_name, 'date': unique})
            regexes.append(re.compile("^%s$" %
                           re.escape(target).replace(unique, '(?P<date>.*?)')))

        backups = {}
        for backup_path in self.get_archives():
            match = None
            for regex in regexes:
                match = regex.match(backup_path)
                if match:
                    break
            else:
                # Not one of the regexes matched.
                continue
            try:
                date = parse_date(match.groupdict()['date'], job.dateformat)
            except ValueError as e:
                # This can occasionally happen when multiple archives
                # share a prefix, say for example you have "windows-$date"
                # and "windows-data-$date". Since we have to use a generic
                # .* regex to capture the date part, when processing the
                # "windows-$date" targets, we'll stumble over entries where
                # we try to parse "data-$date" as a date. Make sure we
                # only print a warning, rather than crashing.
                # TODO: It'd take some work, but we could build a proper
                # regex based on any given date format string, thus avoiding
                # the issue for most cases.
                self.log.exception("Ignoring '%s': %s", backup_path, e)
            else:
                backups[backup_path] = date

        return backups

    def expire(self, job):
        """Have tarsnap delete those archives which we need to expire
        according to the deltas defined.

        If a dry run is wanted, set ``dryrun`` to a dict of the backups to
        pretend that exist (they will always be used, and not matched).
        """

        backups = self.get_backups(job)
        self.log.info('%d backups are matching', len(backups))

        # Determine which backups we need to get rid of, which to keep
        to_keep = expire.expire(backups, job.deltas)
        self.log.info('%d of those can be deleted', (len(backups)-len(to_keep)))

        # Delete all others
        to_delete = []
        for name in backups.keys():
            if name not in to_keep:
                to_delete.append(name)

        to_keep.sort()
        to_delete.sort()

        self.log.debug('Keeping %s', ' '.join(to_keep))

        if len(to_delete) == 0:
            return

        self.log.info('Deleting %s', ' '.join(to_delete))

        if not self.dryrun:
            # group into batches of up to 500 files in a single delete call for
            # improved efficiency: https://www.tarsnap.com/improve-speed.html#faster-delete
            # 500 is a somewhat arbitrary batch size. The actual restriction is
            # typically a bytes limit on the size of the command that the shell
            # will accept, which can vary widely across OS flavors. Because
            # it's a bytes limit, this is also dependent on the length of the
            # backup filenames. So rather than deal with all this complexity,
            # 500 was chosen as a reasonable balance between safety and speed.
            batch_size = 500
            for i in range(0, len(to_delete), batch_size):
                batch = to_delete[i:i + batch_size]
                self.call('-d', '-f', *' -f '.join(batch).split(' '))
                for name in batch:
                    self.archives.remove(name)

    def make(self, job):
        now = datetime.utcnow()
        date_str = now.strftime(job.dateformat or DEFAULT_DATEFORMAT)
        target = Template(job.target).safe_substitute(
            {'date': date_str, 'name': job.name})

        if job.name:
            self.log.info('Creating backup %s: %s', job.name, target)
        else:
            self.log.info('Creating backup: %s', target)

        if not self.dryrun:
            args = ['-c']
            [args.extend(['--exclude', e]) for e in job.excludes]
            args.extend(['-f', target])
            args.extend(job.sources)
            self.call(*args)
        # Add the new backup the list of archives, so we have an up-to-date
        # list without needing to query again.
        self._add_known_archive(target)

        return target, now


DEFAULT_DATEFORMAT = '%Y%m%d-%H%M%S'


def parse_date(string, dateformat=None):
    """Parse a date string, either using the given format, or by
    relying on python-dateutil.
    """
    if dateformat:
        return datetime.strptime(string, dateformat)
    else:
        return dateutil.parser.parse(string)


def timedelta_string(value):
    """Parse a string to a timedelta value.
    """
    try:
        return config.str_to_timedelta(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError('invalid delta value: %r (suffix d, s allowed)' % e)


class Command(object):

    BackendClass = TarsnapBackend

    def __init__(self, args, log, backend_class=None):
        self.args = args
        self.log = log
        self.backend = (backend_class or self.BackendClass)(
            self.log, self.args.tarsnap_options,
            dryrun=getattr(self.args, 'dryrun', False))

    @classmethod
    def setup_arg_parser(self, parser):
        pass

    @classmethod
    def validate_args(self, args):
        pass

    def run(self, job):
        raise NotImplementedError()


class ListCommand(Command):

    help = 'list all the existing backups'
    description = 'For each job, output a sorted list of existing backups.'

    def run(self, job):
        self.log.info('%s', (job.name or "Unnamed job"))
        unsorted_backups = self.backend.get_backups(job).items()
        # Sort backups by time
        # TODO: This duplicates code from the expire module. Should
        # the list of backups always be returned sorted instead?
        backups = sorted(unsorted_backups, key=lambda x: x[1], reverse=True)
        for backup, _ in backups:
            print("  %s" % backup)


class ExpireCommand(Command):

    help = 'delete old backups, but don\'t create a new one'
    description = 'For each job defined, determine which backups can ' \
                  'be deleted according to the deltas, and then delete them.'

    @classmethod
    def setup_arg_parser(self, parser):
        parser.add_argument('--dry-run', dest='dryrun', action='store_true',
                            help='only simulate, don\'t delete anything')

    def expire(self, job):
        if not job.deltas:
            self.log.info("Skipping '%s', does not define deltas", job.name)
            return

        self.backend.expire(job)

    def run(self, job):
        self.expire(job)


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
            raise ArgumentError('Since you are not using a config file, '
                                'you need to give --target')
        if not args.config and not args.deltas and not args.no_expire:
            raise ArgumentError('Since you are not using a config file, and '
                                'have not specified --no-expire, you will '
                                'need to give --deltas')
        if not args.config and not args.sources:
            raise ArgumentError('Since you are not using a config file, you '
                                'need to specify at least one source path '
                                'using --sources')

    def run(self, job):
        if not job.sources:
            self.log.info("Skipping '%s', does not define sources", job.name)
            return

        if job.exec_before:
            self.backend._exec_util(job.exec_before)

        # Determine whether we can run this job. If any of the sources
        # are missing, or any source directory is empty, we skip this job.
        sources_missing = False
        if not job.force:
            for source in job.sources:
                if not path.exists(source):
                    sources_missing = True
                    break
                if path.isdir(source) and not os.listdir(source):
                    # directory is empty
                    sources_missing = True
                    break

        # Do a new backup
        skipped = False

        if sources_missing:
            if job.name:
                self.log.info("Not backing up '%s', because not all given "
                               "sources exist", job.name)
            else:
                self.log.info("Not making backup, because not all given "
                              "sources exist")
            skipped = True
        else:
            try:
                self.backend.make(job)
            except Exception:
                self.log.exception("Something went wrong with backup job: '%s'",
                    job.name)

        if job.exec_after:
            self.backend._exec_util(job.exec_after)

        # Expire old backups, but only bother if either we made a new
        # backup, or if expire was explicitly requested.
        if not skipped and not self.args.no_expire:
            self.expire(job)


COMMANDS = {
    'make': MakeCommand,
    'expire': ExpireCommand,
    'list': ListCommand,
}


PLUGINS = [
]


def parse_args(argv):
    """Parse the command line.
    """
    parser = argparse.ArgumentParser(
        description='An interface to tarsnap to manage backups.')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('-q', action='store_true', dest='quiet', help='be quiet')
    group.add_argument('-v', action='store_true', dest='verbose', help='be verbose')
    # We really want nargs=(1,2), but since this isn't available, we can
    # just asl well support an arbitrary number of values for each -o.
    parser.add_argument('-o', metavar=('name', 'value'), nargs='+',
                        dest='tarsnap_options', default=[], action='append',
                        help='option to pass to tarsnap',)
    parser.add_argument('--config', '-c', help='use the given config file')

    group = parser.add_argument_group(
        description='Instead of using a configuration file, you may define '
                    'a single job on the command line:')
    group.add_argument('--target', help='target filename for the backup')
    group.add_argument('--sources', nargs='+', help='paths to backup',
                       default=[])
    group.add_argument('--deltas', '-d', metavar='DELTA',
                       type=timedelta_string,
                       help='generation deltas', nargs='+')
    group.add_argument('--dateformat', '-f', help='dateformat')

    for plugin in PLUGINS:
        plugin.setup_arg_parser(parser)

    # This will allow the user to break out of an nargs='*' to start
    # with the subcommand. See http://bugs.python.org/issue9571.
    parser.add_argument('-', dest='__dummy', action="store_true",
                        help=argparse.SUPPRESS)

    subparsers = parser.add_subparsers(
        title="commands", description="commands may offer additional options")
    for cmd_name, cmd_klass in COMMANDS.items():
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
    # explicitly defining the group causes to happen).
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
    except ArgumentError as e:
        print("Error: %s" % e)
        return 1

    # Setup logging
    level = logging.WARNING if args.quiet else (
        logging.DEBUG if args.verbose else logging.INFO)
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(message)s"))
    log = logging.getLogger()
    log.setLevel(level)
    log.addHandler(ch)

    # Build a list of jobs, process them.
    if args.config:
        try:
            jobs, global_config = config.load_config_from_file(args.config)
        except config.ConfigError:
            log.exception("Error loading config file:")
            return 1
    else:
        # Only a single job, as given on the command line
        jobs = {None: Job(**{'target': args.target, 'dateformat': args.dateformat,
                             'deltas': args.deltas, 'sources': args.sources})}
        global_config = {}

    # Validate the requested list of jobs to run
    if args.jobs:
        unknown = set(args.jobs) - set(jobs.keys())
        if unknown:
            log.error('Error: not defined in the config file: %s', ", ".join(unknown))
            return 1
        jobs_to_run = dict([(n, j) for n, j in jobs.items() if n in args.jobs])
    else:
        jobs_to_run = jobs

    command = args.command(args, log)
    try:
        for job in jobs_to_run.values():
            command.run(job)

        for plugin in PLUGINS:
            plugin.all_jobs_done(args, global_config, args.command)
    except TarsnapError:
        log.exception("tarsnap execution failed:")
        return 1


def run():
    sys.exit(main(sys.argv[1:]) or 0)


if __name__ == '__main__':
    run()
