"""
XXX: How should test this? What exactly should be tested?
- Backups are deleted past the last generation
- At the end of each generation, most backups are deleted, but some
  are persisted. Try to write this as a test.
- Jumping a long time into the future -> stuff should be deleted.
"""

from tarsnapper.test import BackupSimulator


def test_failing_keep():
    """This used to delete backup B, because we were first looking
    for a seven day old backup, finding A, then looking for a six day
    old backup, finding A again (it is closer to six days old then B)
    and then stopping the search, assuming after two identical matches
    that there are no more.
    """
    s = BackupSimulator('1d 7d')
    s.add([
        '20100615-000000',   # A
        '20100619-000000',   # B
        '20100620-000000',   # C
    ])
    delete, keep = s.expire()
    assert not delete
