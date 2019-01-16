from datetime import datetime
try:
    from collections import OrderedDict    # Python 2.7
except ImportError:
    # Install from: http://pypi.python.org/pypi/ordereddict
    from ordereddict import OrderedDict

from .config import parse_deltas
from .expire import expire as default_expire_func
from .script import parse_date


__all__ = ('BackupSimulator',)


class BackupSimulator(object):
    """Helper to simulate making backups, and expire old ones, at
    various points in time.
    """

    def __init__(self, deltas, expire_func=default_expire_func):
        if isinstance(deltas, str):
            deltas = parse_deltas(deltas)
        self.deltas = deltas
        self.expire_func = expire_func
        self.now = datetime.now()
        self.backups = OrderedDict()

    def add(self, backups):
        for dt in backups:
            if isinstance(dt, str):
                dt = parse_date(dt)
            self.backups[str(dt)] = dt

    def go_to(self, dt):
        self.now = dt

    def go_by(self, td):
        self.now += td

    def backup(self, expire=True):
        self.add([self.now])
        if expire:
            return self.expire()

    def expire(self):
        keep = self.expire_func(self.backups, self.deltas)
        deleted = []
        for key in self.backups.keys():
            if not key in keep:
                deleted.append(key)
                del self.backups[key]
        return deleted, keep
