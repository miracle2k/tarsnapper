import argparse
from datetime import datetime
import logging
from os import path
import re
import shutil
import tempfile

from tarsnapper.config import Job, parse_deltas, str_to_timedelta
from tarsnapper.script import (
    TarsnapBackend, MakeCommand, ListCommand, ExpireCommand, parse_args,
    DEFAULT_DATEFORMAT)


class FakeBackend(TarsnapBackend):

    def __init__(self, *a, **kw):
        TarsnapBackend.__init__(self, *a, **kw)
        self.calls = []
        self.fake_archives = []

    def _exec_tarsnap(self, args):
        self.calls.append(args[1:])  # 0 is "tarsnap"
        if '--list-archives' in args:
            return u"\n".join(self.fake_archives)

    def _exec_util(self, cmdline):
        self.calls.append(cmdline)

    def match(self, expect_calls):
        """Compare the calls we have captured with what the list of
        regexes in ``expect``.
        """
        print(expect_calls, '==', self.calls)
        if not len(expect_calls) == len(self.calls):
            return False
        for args, expected_args in zip(self.calls, expect_calls):
            # Each call has multiple arguments
            if not len(args) == len(expected_args):
                return False
            for actual, expected_re in zip(args, expected_args):
                if not re.match(expected_re, actual):
                    return False
        return True


class BaseTest(object):

    def setup(self):
        self.log = logging.getLogger("test_script")
        self._tmpdir = tempfile.mkdtemp()
        # We need at least a file for tarsnapper to consider a source
        # to "exist".
        open(path.join(self._tmpdir, '.placeholder'), 'w').close()
        self.now = datetime.utcnow()

    def teardown(self):
        shutil.rmtree(self._tmpdir)

    def run(self, jobs, archives, **args):
        final_args = {
            'tarsnap_options': (),
            'no_expire': False,
        }
        final_args.update(args)
        cmd = self.command_class(argparse.Namespace(**final_args),
                                 self.log, backend_class=FakeBackend)
        cmd.backend.fake_archives = archives
        for job in (jobs if isinstance(jobs, list) else [jobs]):
            cmd.run(job)
        return cmd

    def job(self, deltas='1d 2d', name='test', **kwargs):
        """Make a job object.
        """
        opts = dict(
            target="$name-$date",
            deltas=parse_deltas(deltas),
            name=name,
            sources=[self._tmpdir])
        opts.update(kwargs)
        return Job(**opts)

    def filename(self, delta, name='test', fmt='%s-%s'):
        return fmt % (
            name,
            (self.now - str_to_timedelta(delta)).strftime(DEFAULT_DATEFORMAT))


class TestTarsnapOptions(BaseTest):

    command_class = ExpireCommand

    def tset_parse(self):
        parse_args(['-o', 'name', 'foo', '-', 'list'])
        parse_args(['-o', 'name', '-', 'list'])
        parse_args(['-o', 'name', 'sdf', 'sdf', '-', 'list'])

    def test_pass_along(self):
        # Short option
        cmd = self.run(self.job(), [], tarsnap_options=(('o', '1'),))
        assert cmd.backend.match([('-o', '1', '--list-archives')])

        # Long option
        cmd = self.run(self.job(), [], tarsnap_options=(('foo', '1'),))
        assert cmd.backend.match([('--foo', '1', '--list-archives')])

        # No value
        cmd = self.run(self.job(), [], tarsnap_options=(('foo',),))
        assert cmd.backend.match([('--foo', '--list-archives')])

        # Multiple values
        cmd = self.run(self.job(), [], tarsnap_options=(('foo', '1', '2'),))
        assert cmd.backend.match([('--foo', '1', '2', '--list-archives')])


class TestMake(BaseTest):

    command_class = MakeCommand

    def test(self):
        cmd = self.run(self.job(), [])
        assert cmd.backend.match([
            ('-c', '-f', 'test-.*', '.*'),
            ('--list-archives',)
        ])

    def test_no_sources(self):
        """If no sources are defined, the job is skipped."""
        cmd = self.run(self.job(sources=None), [])
        assert cmd.backend.match([])

    def test_excludes(self):
        cmd = self.run(self.job(excludes=['foo']), [])
        assert cmd.backend.match([
            ('-c', '--exclude', 'foo', '-f', 'test-.*', '.*'),
            ('--list-archives',)
        ])

    def test_no_expire(self):
        cmd = self.run(self.job(), [], no_expire=True)
        assert cmd.backend.match([
            ('-c', '-f', 'test-.*', '.*'),
        ])

    def test_exec(self):
        """Test ``exec_before`` and ``exec_after`` options.
        """
        cmd = self.run(self.job(exec_before="echo begin", exec_after="echo end"),
                       [], no_expire=True)
        assert cmd.backend.match([
            ('echo begin'),
            ('-c', '-f', 'test-.*', '.*'),
            ('echo end'),
        ])


class TestExpire(BaseTest):

    command_class = ExpireCommand

    def test_nothing_to_do(self):
        cmd = self.run(self.job(deltas='1d 10d'), [
            self.filename('1d'),
            self.filename('5d'),
        ])
        assert cmd.backend.match([
            ('--list-archives',)
        ])

    def test_no_deltas(self):
        """If a job does not define deltas, we skip it."""
        cmd = self.run(self.job(deltas=None), [
            self.filename('1d'),
            self.filename('5d'),
        ])
        assert cmd.backend.match([])

    def test_something_to_expire(self):
        cmd = self.run(self.job(deltas='1d 2d'), [
            self.filename('1d'),
            self.filename('5d'),
        ])
        assert cmd.backend.match([
            ('--list-archives',),
            ('-d', '-f', 'test-.*'),
        ])

    def test_aliases(self):
        cmd = self.run(self.job(deltas='1d 2d', aliases=['alias']), [
            self.filename('1d'),
            self.filename('5d', name='alias'),
        ])
        assert cmd.backend.match([
            ('--list-archives',),
            ('-d', '-f', 'alias-.*'),
        ])

    def test_date_name_mismatch(self):
        """Make sure that when processing a target "home-$date",
        we won't stumble over "home-dev-$date". This can be an issue
        due to the way we try to parse the dates in filenames.
        """
        cmd = self.run(self.job(name="home"), [
            self.filename('1d', name="home-dev"),
        ])


class TestList(BaseTest):

    command_class = ListCommand

    def test(self):
        cmd = self.run([self.job(), self.job(name='foo')], [
            self.filename('1d'),
            self.filename('5d'),
            self.filename('1d', name='foo'),
            self.filename('1d', name='something-else'),
        ])
        # We ask to list two jobs, but only one --list-archives call is
        # necessary.
        assert cmd.backend.match([
            ('--list-archives',)
        ])
