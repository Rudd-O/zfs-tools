# -*- coding: utf-8 -*-

import sys, os

sys.path.append(
    os.path.join(os.path.dirname(os.path.realpath(__file__)), os.path.pardir, "src")
)
import itertools
import multiprocessing
import optparse
import signal
import time
import traceback
import urllib
from zfs_tools.connection import ZFSConnection
from zfs_tools.util import stderr, verbose_stderr, set_verbose
from zfs_tools.sync import recursive_replicate, optimize
from zfs_tools.sync import recursive_clear_obsolete


def main():
    # ===================== configuration =====================

    parser = optparse.OptionParser(
        "usage: %prog [-onv] [-b BUFSIZE] [-l RATELIMIT] <srcdatasetname> <dstdatasetname>"
    )
    parser.add_option(
        "-o",
        "--progress",
        action="store_true",
        dest="progress",
        default=False,
        help="show progress (depends on the executabilty of the 'bar' a.k.a. 'clpbar' program, or the 'pv' program) (default: %default)",
    )
    parser.add_option(
        "-l",
        "--rate-limit",
        action="store",
        dest="ratelimit",
        default=-1,
        type="int",
        help="rate limit in bytes per second (requires --progress) (default: %default which means no limit)",
    )
    parser.add_option(
        "-n",
        "--dry-run",
        action="store_true",
        dest="dryrun",
        default=False,
        help="don't actually manipulate any file systems",
    )
    parser.add_option(
        "-b",
        "--bufsize",
        action="store",
        dest="bufsize",
        default=-1,
        help="buffer size in bytes for network operations (default: %default i.e. OS default)",
    )
    parser.add_option(
        "-C",
        "--force-compression",
        action="store_true",
        dest="force_compression",
        default=False,
        help="forcibly enable gzip compression for transfers via SSH (default: %default i.e. obey SSH configuration)",
    )
    parser.add_option(
        "-v",
        "--verbose",
        action="store_true",
        dest="verbose",
        default=False,
        help="be verbose (default: %default)",
    )
    parser.add_option(
        "-t",
        "--trust",
        action="store_true",
        dest="trust",
        default=False,
        help="automatically trust unknown or mismatched SSH keys of remote hosts (default: %default)",
    )
    parser.add_option(
        "-c",
        "--clear-obsolete",
        action="store_true",
        dest="clear_obsolete",
        default=False,
        help="automatically destroy file systems and snapshots at the destination that are no longer present in the source (default: %default)",
    )
    parser.add_option(
        "--ssh-cipher",
        action="store",
        dest="sshcipher",
        default=None,
        type="string",
        help="ssh cipher, careful selection of which may increase performance (default: as per ssh_config)",
    )
    parser.add_option(
        "--identity-file",
        action="store",
        dest="identityfile",
        default=None,
        type="string",
        help="path to the SSH identity file (-i) to use (default: as per ssh_config)",
    )
    parser.add_option(
        "--known-hosts-file",
        action="store",
        dest="knownhostsfile",
        default=None,
        type="string",
        help="path to the SSH known_hosts file (-o KnownHostsFile) to use (default: as per ssh_config)",
    )
    parser.add_option(
        "--create-destination",
        action="store_true",
        dest="create_destination",
        default=False,
        help="create destination dataset if missing (default: %default)",
    )
    parser.add_option(
        "--replication-stream",
        action="store_true",
        dest="replication_stream",
        default=True,
        help="use zfs send -R, which may destroy destination filesystems/snapshots (default: %default)",
    )
    parser.add_option(
        "--no-replication-stream",
        action="store_false",
        dest="replication_stream",
        help="don't use zfs send -R, to protect destination filesystems/snapshots",
    )
    parser.add_option(
        "--lock-source",
        action="store_true",
        dest="lock_src",
        default=False,
        help="zflock the source dataset (default: %default)",
    )
    parser.add_option(
        "--lock-destination",
        action="store_true",
        dest="lock_dst",
        default=False,
        help="zflock the destination dataset (default: %default)",
    )
    parser.add_option(
        "--parallel",
        action="store",
        dest="parallel",
        type="int",
        default=1,
        metavar="N",
        help="number of parallel processes (default: %default)",
    )
    parser.add_option(
        "--parallel-log",
        action="store",
        dest="parallel_log",
        type="string",
        default="/var/log/zfs-tools/zreplicate.%(filesystem)s.%(timestamp)s",
        metavar="PATTERN",
        help="log file pattern to use in parallel mode (default: %default)",
    )
    parser.add_option(
        "--timeformat",
        action="store",
        dest="timeformat",
        default="%Y-%m-%d-%H%M%S",
        help="time format for logfiles (default: %default)",
    )
    parser.add_option(
        "--utc",
        action="store_true",
        dest="utc",
        default=False,
        help="Use UTC for timestamps (default: no)",
    )
    opts, args = parser.parse_args(sys.argv[1:])

    try:
        bufsize = int(opts.bufsize)
        assert bufsize >= 16384 or bufsize == -1
    except (ValueError, AssertionError) as e:
        parser.error("bufsize must be an integer greater than 16384")

    if len(args) == 2:
        try:
            source_host, source_dataset_name = args[0].split(":", 1)
        except ValueError:
            source_host, source_dataset_name = "localhost", args[0]
        try:
            destination_host, destination_dataset_name = args[1].split(":", 1)
        except ValueError:
            destination_host, destination_dataset_name = "localhost", args[1]
    else:
        parser.error("arguments are wrong")

    if opts.ratelimit != -1:
        if opts.ratelimit < 1024:
            parser.error(
                "rate limit (%s) must be higher than 1024 bytes per second"
                % opts.ratelimit
            )
        if not opts.progress:
            parser.error("to apply a rate limit, you must specify --progress too")

    set_verbose(opts.verbose)

    # ===================== end configuration =================

    # ================ start program algorithm ===================

    src_conn = ZFSConnection(
        source_host,
        subset=source_dataset_name,
        trust=opts.trust,
        sshcipher=opts.sshcipher,
        identityfile=opts.identityfile,
        knownhostsfile=opts.knownhostsfile,
        verbose=opts.verbose,
    )
    dst_conn = ZFSConnection(
        destination_host,
        subset=destination_dataset_name,
        trust=opts.trust,
        sshcipher=opts.sshcipher,
        identityfile=opts.identityfile,
        knownhostsfile=opts.knownhostsfile,
        verbose=opts.verbose,
    )

    verbose_stderr(
        "Replicating dataset %s:%s into %s:%s..."
        % (source_host, source_dataset_name, destination_host, destination_dataset_name)
    )

    verbose_stderr("Assessing that the source dataset exists...")
    try:
        source_dataset = src_conn.pools.lookup(source_dataset_name)
    except KeyError:
        stderr("Error: the source dataset does not exist.  Backup cannot continue.")
        sys.exit(2)

    verbose_stderr("Assessing that the destination dataset exists...")
    try:
        destination_dataset = dst_conn.pools.lookup(destination_dataset_name)
    except KeyError:
        if opts.create_destination:
            verbose_stderr("Creating missing destination dataset exists as requested")
            dst_conn.create_dataset(destination_dataset_name)
            try:
                destination_dataset = dst_conn.pools.lookup(destination_dataset_name)
            except KeyError:
                stderr(
                    "Error: failed to create the destination dataset.  Backup cannot continue."
                )
                sys.exit(2)
        else:
            stderr(
                "Error: the destination dataset does not exist.  Backup cannot continue."
            )
            sys.exit(2)

    if opts.clear_obsolete:
        operation_schedule = recursive_clear_obsolete(
            source_dataset, destination_dataset
        )

        verbose_stderr("=================================")
        for op, dset in operation_schedule:
            dataset_path = dset.get_path()

            if op == "destroy":
                verbose_stderr("Destroying (%s) %s in destination" % (op, dataset_path))
                if not opts.dryrun:
                    dst_conn.destroy_dataset(dataset_path)
            elif op == "destroy_recursively":
                verbose_stderr(
                    "Destroying recursively (%s) %s in destination" % (op, dataset_path)
                )
                if not opts.dryrun:
                    dst_conn.destroy_recursively(dataset_path)
            else:
                assert 0, "not reached: unknown operation %r" % op
            verbose_stderr("=================================")

        verbose_stderr("Clearing of obsolete datasets complete.")

        verbose_stderr("=================================")
        verbose_stderr("Refreshing dataset data...")
        source_dataset = src_conn.pools.lookup(source_dataset_name)
        destination_dataset = dst_conn.pools.lookup(destination_dataset_name)

    operation_schedule = recursive_replicate(source_dataset, destination_dataset)
    optimized_operation_schedule = optimize(
        operation_schedule, allow_recursivize=opts.replication_stream
    )

    send_opts = []
    receive_opts = []
    if opts.verbose:
        send_opts.append("-v")
        receive_opts.append("-v")

    def transfer(operation):
        op, src, dst, srcs, dsts = operation
        source_dataset_path = src.get_path()

        if dst:
            destination_dataset_path = dst.get_path()
        else:
            commonbase = os.path.commonprefix(
                [src.get_path(), source_dataset.get_path()]
            )
            remainder = src.get_path()[len(commonbase) :]
            destination_dataset_path = destination_dataset.get_path() + remainder

        if op == "create_stub":
            verbose_stderr(
                "Creating (%s) %s in destination" % (op, destination_dataset_path)
            )
            if not opts.dryrun:
                dst_conn.create_dataset(destination_dataset_path)

        else:
            destination_snapshot_path = dsts.get_path()
            if srcs:
                this_send_opts = ["-I", "@" + srcs.name]
            else:
                this_send_opts = []
            if "recursive" in op and opts.replication_stream:
                this_send_opts.append("-R")
            verbose_stderr(
                "Replicating (%s) %s to %s"
                % (op, source_dataset_path, destination_dataset_path)
            )
            verbose_stderr("Base snapshot available in destination: %s" % srcs)
            verbose_stderr("Target snapshot available in source:    %s" % dsts)

            locksrcdataset = source_dataset_path if opts.lock_src else None
            lockdstdataset = destination_dataset_path if opts.lock_dst else None

            if not opts.dryrun:
                src_conn.transfer(
                    dst_conn,
                    destination_snapshot_path,
                    destination_dataset_path,
                    showprogress=opts.progress,
                    compression=opts.force_compression,
                    ratelimit=opts.ratelimit,
                    bufsize=bufsize,
                    send_opts=send_opts + this_send_opts,
                    receive_opts=receive_opts,
                    locksrcdataset=locksrcdataset,
                    lockdstdataset=lockdstdataset,
                )

    timestamp = None

    def set_timestamp(t):
        global timestamp
        timestamp = t

    def redirect_log(filesystem, timestamp):
        """Redirect stdout and stderr to logfile for this filesystem/timestamp."""
        logfile = opts.parallel_log % {
            "timestamp": timestamp,
            "filesystem": urllib.quote(filesystem, ""),
        }
        logdir = os.path.dirname(logfile)
        if not os.path.isdir(logdir):
            try:
                os.remove(logdir)
            except OSError:
                pass
            try:
                os.makedirs(logdir, mode=0o0755)
            except OSError:
                pass
        logfd = os.open(logfile, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        os.dup2(logfd, sys.stdout.fileno())
        os.dup2(logfd, sys.stderr.fileno())

    def parallel_transfer(operations):
        """Wraps transfer(), to redirect stdout/stderr into separate files."""
        # we need to catch exceptions, as these can't be pickled back across
        # the multiprocessing interface
        try:
            if len(operations) > 0:
                src = operations[0][1]  # a representative, all are the same
                source_dataset_path = src.get_path()
                redirect_log(source_dataset_path, timestamp)
                for operation in operations:
                    transfer(operation)
        except:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            stderr(
                "zreplicate failed: %s"
                % traceback.format_exception(exc_type, exc_value, exc_traceback)
            )

    if opts.parallel == 1:
        verbose_stderr("=================================")
        for operation in optimized_operation_schedule:
            transfer(operation)
            verbose_stderr("=================================")
    else:
        verbose_stderr("Logging in parallel mode to %s" % opts.parallel_log)

        operations_grouped_by_source = []
        for k, g in itertools.groupby(optimized_operation_schedule, lambda op: op[1]):
            operations_grouped_by_source.append(list(g))
        p = multiprocessing.Pool(
            processes=opts.parallel,
            initializer=set_timestamp,
            initargs=(
                time.strftime(
                    opts.timeformat, time.gmtime() if opts.utc else time.localtime()
                ),
            ),
        )

        # terminate the pool on interrupt or SIGTERM
        def terminate_handler(signum, frame):
            verbose_stderr("SIGTERM, terminating ...\n")
            p.terminate()
            p.join()
            sys.exit(1)

        signal.signal(signal.SIGTERM, terminate_handler)
        try:
            p.map(parallel_transfer, operations_grouped_by_source)
        except KeyboardInterrupt:
            verbose_stderr("KeyboardInterrupt, terminating ...\n")
            p.terminate()
            p.join()
            raise

    verbose_stderr("Replication complete.")
