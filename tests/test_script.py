from StringIO import StringIO
from os import path
import re
import shutil
import tempfile
import logging
import argparse
from datetime import datetime
from tarsnapper.script import (
    TarsnapBackend, MakeCommand, ListCommand, ExpireCommand, parse_args,
    DEFAULT_DATEFORMAT)
from tarsnapper.config import Job, parse_deltas, str_to_timedelta


class FakeBackend(TarsnapBackend):

    def __init__(self, *a, **kw):
        TarsnapBackend.__init__(self, *a, **kw)
        self.calls = []
        self.fake_archives = []

    def _call(self, *args):
        self.calls.append(args)
        if '--list-archives' in args:
            return StringIO("\n".join(self.fake_archives))

    def match(self, expect_calls):
        """Compare the calls we have captured with what the list of
        regexes in ``expect``.
        """
        print expect_calls, '==', self.calls
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
            'tarsnap_options': {},
            'no_expire': False,
        }
        final_args.update(args)
        cmd = self.command_class(argparse.Namespace(**final_args),
                                 self.log, backend_class=FakeBackend)
        cmd.backend.fake_archives = archives
        for job in (jobs if isinstance(jobs, list) else [jobs]):
            cmd.run(job)
        return cmd

    def job(self, deltas='1d 2d', name='test'):
        """Make a job object.
        """
        return Job(
            target="$name-$date",
            deltas=parse_deltas(deltas),
            name=name,
            sources=[self._tmpdir])

    def filename(self, delta, name='test', fmt='%s-%s'):
        return fmt % (
            name,
            (self.now - str_to_timedelta(delta)).strftime(DEFAULT_DATEFORMAT))


class TestMake(BaseTest):

    command_class = MakeCommand

    def test(self):
        cmd = self.run(self.job(), [])
        assert cmd.backend.match([
            ('-c', '-f', 'test-.*', '.*'),
            ('--list-archives',)
        ])

    def test_no_expire(self):
        cmd = self.run(self.job(), [], no_expire=True)
        assert cmd.backend.match([
            ('-c', '-f', 'test-.*', '.*'),
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

    def test_something_to_expire(self):
        cmd = self.run(self.job(deltas='1d 2d'), [
            self.filename('1d'),
            self.filename('5d'),
        ])
        assert cmd.backend.match([
            ('--list-archives',),
            ('-d', '-f', 'test-.*'),
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