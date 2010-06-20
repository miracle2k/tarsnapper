#!/usr/bin/env python

import sys
from os import path
sys.path.insert(0, path.join(path.dirname(__file__), 'src'))

from datetime import timedelta

from tarsnapper.test import BackupSimulator
from tarsnapper.config import parse_deltas


def main(argv):
    s = BackupSimulator(parse_deltas('1d 7d 30d'))

    until = s.now + timedelta(days=17)
    while s.now <= until:
        s.go_by(timedelta(days=1))
        s.backup()

    for name, date in s.backups.iteritems():
        print name


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]) or 0)