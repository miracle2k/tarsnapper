import operator


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
    a grandfather-father-son backup strategy.

    The approach chosen tries to achieve the following:

    * Do not require backup names to include information on which generation
      a backup belongs to, like for example ``tarsnap-generations`` does.
      That is, you can create your backups anyway you wish, and simply use
      this utility to delete old backups.

    * Do not use any fixed generations (weekly, monthly etc), but freeform
      timespans.

    * Similarily, do not make any assumptions about when or if backup jobs
      have actually run or will run, but try to match the given deltas as
      closely as possible.

    What the code actually does is, for each generation, start at a fixed
    point in time determined by the most recent backup (which is always
    kept) plus the parent generation's delta and then repeatedly stepping
    the generation's delta forwards in time, chosing a backup that fits
    best which will then be kept.

    Returned is a list of backup names.
    """

    # Deal with some special cases
    assert len(deltas) >= 2, "At least two deltas are required"
    if not backups:
        return []

    # First, sort the backups with most recent one first
    backups = sorted(backups.items(), key=lambda x: x[1], reverse=True)
    old_backups = backups[:]

    # Also make sure that we have the deltas in ascending order
    deltas.sort()

    # Always keep the most recent backup
    most_recent_backup = backups[0][1]
    to_keep = set([backups[0][0]])

    # Then, for each delta/generation, determine which backup to keep
    last_delta = deltas.pop()
    while deltas:
        current_delta = deltas.pop()

        # (1) Start from the point in time where the current generation ends.
        dt_pointer = most_recent_backup - last_delta
        last_selected = None
        while dt_pointer < most_recent_backup:
            # (2) Find the backup that matches the current position best.
            # We have different options here: Take the closest older backup,
            # take the closest newer backup, or just take the closest backup
            # in general. We do the latter. The difference is merely in how
            # long the oldest backup in each generation should be kept, that
            # is, how the given deltas should be interpreted.
            by_dist = sorted([(bn, bd, abs(bd - dt_pointer)) for bn, bd in backups], key=operator.itemgetter(2))
            if by_dist:
                if by_dist[0][0] == last_selected:
                    # If the time diff between two backups is larger than
                    # the delta, it can happen that multiple iterations of
                    # this loop determine the same backup to be closest.
                    # In this case, to avoid looping endlessly, we need to
                    # force the date pointer to move forward.
                    dt_pointer += current_delta
                else:
                    last_selected = by_dist[0][0]
                    to_keep.add(by_dist[0][0])
                    # (3) Proceed forward in time, jumping by the current
                    # generation's delta.
                    dt_pointer = by_dist[0][1] + current_delta
            else:
                # No more backups found in this generation.
                break

        last_delta = current_delta

    return list(to_keep)
