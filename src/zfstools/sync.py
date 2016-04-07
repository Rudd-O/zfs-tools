'''
Synchronization-related functionality
'''

import itertools
from zfstools.util import simplify
from zfstools.models import Snapshot
import warnings

# it is time to determine which datasets need to be synced
# we walk the entire dataset structure, and sync snapshots recursively
def recursive_replicate(s, d):
    sched = []

    # we first collect all snapshot names, to later see if they are on both sides, one side, or what
    all_snapshots = []
    if s: all_snapshots.extend(s.get_snapshots())
    if d: all_snapshots.extend(d.get_snapshots())
    all_snapshots = [ y[1] for y in sorted([ (x.get_property('creation'), x.name) for x in all_snapshots ]) ]
    snapshot_pairs = []
    for snap in all_snapshots:
        try: ssnap = s.get_snapshot(snap)
        except (KeyError, AttributeError): ssnap = None
        try: dsnap = d.get_snapshot(snap)
        except (KeyError, AttributeError): dsnap = None
        # if the source snapshot exists and is not already in the table of snapshots
        # then pair it up with its destination snapshot (if it exists) or None
        # and add it to the table of snapshots
        if ssnap and not snap in [ x[0].name for x in snapshot_pairs ]:
            snapshot_pairs.append((ssnap, dsnap))

    # now we have a list of all snapshots, paired up by name, and in chronological order
    # (it's quadratic complexity, but who cares)
    # now we need to find the snapshot pair that happens to be the the most recent common pair
    found_common_pair = False
    for idx, (m, n) in enumerate(snapshot_pairs):
        if m and n and m.name == n.name:
            found_common_pair = idx

    # we have combed through the snapshot pairs
    # time to check what the latest common pair is
    if not s.get_snapshots():
        if d is None:
            # well, no snapshots in source, just create a stub in the target
            sched.append(("create_stub", s, d, None, None))
    elif found_common_pair is False:
        # no snapshot is in common, problem!
        # theoretically destroying destination dataset and resyncing it recursively would work
        # but this requires work in the optimizer that comes later
        if d is not None and d.get_snapshots():
            warnings.warn("Asked to replicate %s into %s but %s has snapshots and both have no snapshots in common!" % (s, d, d))
        # see source snapshots
        full_source_snapshots = [ y[1] for y in sorted([ (x.get_property('creation'), x) for x in s.get_snapshots() ]) ]
        # send first snapshot as full snapshot
        sched.append(("full", s, d, None, full_source_snapshots[0]))
        if len(full_source_snapshots) > 1:
            # send other snapshots as incremental snapshots
            sched.append(("incremental", s, d, full_source_snapshots[0], full_source_snapshots[-1]))
    elif found_common_pair == len(snapshot_pairs) - 1:
        # the latest snapshot of both datasets that is common to both, is the latest snapshot in the source
        # we have nothing to do here because the datasets are "in sync"
        pass
    else:
        # the source dataset has more recent snapshots, not present in the destination dataset
        # we need to transfer those
        snapshots_to_transfer = [ x[0] for x in snapshot_pairs[found_common_pair:] ]
        for n, x in enumerate(snapshots_to_transfer):
            if n == 0: continue
            sched.append(("incremental", s, d, snapshots_to_transfer[n - 1], x))

    # now let's apply the same argument to the children
    children_sched = []
    for c in [ x for x in s.children if not isinstance(x, Snapshot) ]:
        try: cd = d.get_child(c.name)
        except (KeyError, AttributeError): cd = None
        children_sched.extend(recursive_replicate(c, cd))

    # and return our schedule of operations to the parent
    return sched + children_sched

def optimize_coalesce(operation_schedule):
    # now let's optimize the operation schedule
    # this optimization is quite basic
    # step 1: coalesce contiguous operations on the same file system

    operations_grouped_by_source = itertools.groupby(
        operation_schedule,
        lambda op: op[1]
    )
    new = []
    for _, opgroup in [ (x, list(y)) for x, y in operations_grouped_by_source ]:
        if not opgroup:  # empty opgroup
            continue
        if opgroup[0][0] == 'full':  # full operations
            new.extend(opgroup)
        elif opgroup[0][0] == 'create_stub':  # create stub operations
            new.extend(opgroup)
        elif opgroup[0][0] == 'incremental':  # incremental
            # 1->2->3->4 => 1->4
            new_ops = [ (srcs, dsts) for _, _, _, srcs, dsts in opgroup ]
            new_ops = simplify(new_ops)
            for srcs, dsts in new_ops:
                new.append(tuple(opgroup[0][:3] + (srcs, dsts)))
        else:
            assert 0, "not reached: unknown operation type in %s" % opgroup
    return new

def optimize_recursivize(operation_schedule):
    def recurse(dataset, func):
        results = []
        results.append((dataset, func(dataset)))
        results.extend([ x for child in dataset.children if child.__class__ != Snapshot for x in recurse(child, func) ])
        return results

    def zero_out_sched(dataset):
        dataset._ops_schedule = []

    def evict_sched(dataset):
        dataset._ops_schedule = []

    operations_grouped_by_source = itertools.groupby(
        operation_schedule,
        lambda op: op[1]
    )
    operations_grouped_by_source = [ (x, list(y)) for x, y in operations_grouped_by_source ]

    roots = set()
    for root, opgroup in operations_grouped_by_source:
        while root.parent is not None:
            root = root.parent
        roots.add(root)

    for root in roots:
        recurse(root, zero_out_sched)

    for source, opgroup in operations_grouped_by_source:
        source._ops_schedule = opgroup

    def compare(*ops_schedules):
        assert len(ops_schedules), "operations schedules cannot be empty: %r" % ops_schedules

        # in the case of the list of operations schedules being just one (no children)
        # we return True, cos it's safe to recursively replicate this one
        if len(ops_schedules) == 1:
            return True

        # now let's check that all ops schedules are the same length
        # otherwise they are not the same and we can say the comparison isn't the same
        lens = set([ len(o) for o in ops_schedules ])
        if len(lens) != 1:
            return False

        # we have multiple schedules
        # if their type, snapshot origin and snapshot destination are all the same
        # we can say that they are "the same"
        comparisons = [
                all([
                    # never attempt to recursivize operations who involve create_stub
                    all(["create_stub" not in o[0] for o in ops]),
                    len(set([o[0] for o in ops])) == 1,
                    any([o[3] is None for o in ops]) or len(set([o[3].name for o in ops])) == 1,
                    any([o[4] is None for o in ops]) or len(set([o[4].name for o in ops])) == 1,
                ])
                for ops
                in zip(*ops_schedules)
        ]
        return all(comparisons)

    # remove unnecessary stubs that stand in for only other stubs
    for root in roots:
        for dataset, _ in recurse(root, lambda d: d):
            ops = [z for x, y in recurse(dataset, lambda d: d._ops_schedule) for z in y]
            if all([o[0] == 'create_stub' for o in ops]):
                dataset._ops_schedule = []

    for root in roots:
        for dataset, _ in recurse(root, lambda d: d):
            if compare(*[y for x, y in recurse(dataset, lambda d: d._ops_schedule)]):
                old_ops_schedule = dataset._ops_schedule
                recurse(dataset, zero_out_sched)
                for op in old_ops_schedule:
                    dataset._ops_schedule.append((
                        op[0] + "_recursive", op[1], op[2], op[3], op[4]
                    ))

    new_operation_schedule = []
    for root in roots:
        for dataset, ops_schedule in recurse(root, lambda d: d._ops_schedule):
            new_operation_schedule.extend(ops_schedule)

    for root in roots:
        recurse(root, evict_sched)

    return new_operation_schedule

def optimize(operation_schedule, allow_recursivize = True):
    operation_schedule = optimize_coalesce(operation_schedule)
    if allow_recursivize:
        operation_schedule = optimize_recursivize(operation_schedule)
    return operation_schedule

# we walk the entire dataset structure, and sync snapshots recursively
def recursive_clear_obsolete(s, d):
    sched = []

    # we first collect all snapshot names, to later see if they are on both sides, one side, or what
    all_snapshots = []
    snapshots_in_src = set([ m.name for m in s.get_snapshots() ])
    snapshots_in_dst = set([ m.name for m in d.get_snapshots() ])

    snapshots_to_delete = snapshots_in_dst - snapshots_in_src
    snapshots_to_delete = [ d.get_snapshot(m) for m in snapshots_to_delete ]

    for m in snapshots_to_delete:
        sched.append(("destroy", m))

    # now let's apply the same argument to the children
    children_sched = []
    for child_d in [ x for x in d.children if not isinstance(x, Snapshot) ]:
        child_s = None

        try:
            child_s = s.get_child(child_d.name)
        except (KeyError, AttributeError):
            children_sched.append(("destroy_recursively", child_d))

        if child_s:
            children_sched.extend(recursive_clear_obsolete(child_s, child_d))

    # and return our schedule of operations to the parent
    return sched + children_sched
