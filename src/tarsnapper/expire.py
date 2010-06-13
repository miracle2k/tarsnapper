from datetime import datetime, timedelta


__all__ = ('expire',)


def timedelta_div(td1, td2):
    """http://stackoverflow.com/questions/865618/how-can-i-perform-divison-on-a-datetime-timedelta-in-python
    """
    us1 = td1.microseconds + 1000000 * (td1.seconds + 86400 * td1.days)
    us2 = td2.microseconds + 1000000 * (td2.seconds + 86400 * td2.days)
    return float(us1) / us2


def expire(backups, deltas):
    """Given a dict of backup name => backup timestamp pairs in
    ``backups``, and a list of ``timedelta`` objects in ``deltas`` defining
    the generations, will decide which of the backups can be deleted using
    a  grandfather-father-son backup strategy.

    This approach insists on keeping a minimum number of backups in each
    generation, regardless of their timestamp. The number of backups in a
    generation is implicitly defined by the deltas. For example, if the
    first delta is 1 hour, and the second delta is 1 day, then we will
    always try to keep 24 backups in the first generation, even if they
    stretch over, say, the timespan of a year. So for example, if you put
    your backups on hold for a year, and then pick up again, the old backups
    will not be immediately deleted, but only after a sufficient number of
    new backups are available.

    This is what I wanted to accomplish:

      * Do not require backup names to include information on which
        generation a backup belongs to, like for example
        ``tarsnap-generations`` does.

      * Do not make any assumptions about when the backup jobs have
        actually run (this expire function is completely separate from the
        actual backup creation), and when in doubt opt to keep backups
        rather than deleting them.

    Returned is a list of backup names.
    """

    # Deal with some special cases
    assert len(deltas) > 2, "At least two deltas are required"
    if not backups:
        return []

    # First, sort the backups with most recent one first
    backups = [(name, time) for name, time in backups.items()]
    backups.sort(cmp=lambda x, y: cmp(x[1], y[1]))
    old_backups = backups[:]

    # Also make sure that we have the deltas in ascending order
    deltas = list(deltas[:])
    deltas.sort()

    latest_backup = backups.pop()
    dt_incr = latest_backup[1]
    to_keep = [latest_backup[0]]
    while len(deltas) > 1:   # the last delta is the final barrier
        current_delta = deltas.pop(0)
        next_delta = deltas[0]
        num_backups_in_generation = timedelta_div(next_delta, current_delta)

        # For the number of backups needed, use the first backup that is
        # not younger than the requested limit.
        # XXX: Actually, this is pretty broken. No backup would ever
        # graduate to an older generation, and backups already in older
        # generations would never expire. If anything, we would need to
        # use the first backup that is younger than the limit.
        while num_backups_in_generation > 0 and backups:
            name, backup_time = backups.pop()
            if backup_time <= dt_incr - current_delta:
                dt_incr = backup_time
                to_keep.append(name)
                num_backups_in_generation -= 1

    return to_keep

