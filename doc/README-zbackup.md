#zbackup

## Introduction
   zbackup is a front-end for a backup service using ZFS snapshots and replication to safely replicate a set of ZFS filesystems onto another server.  It makes use of zsnap and zreplicate, so ensure these are working nicely before trying to get going with zbackup.

## ZFS properties governing zbackup behaviour
   zbackup is driven by ZFS properties, so your scripts and/or crontab entries need make no mention of particular ZFS datasets, number of snapshots to keep, etc.

   The following user properties define the behaviour, where *tier* is  arbitrary, but expected to be e.g. hourly, daily, weekly, etc. All properties must be in the module `com.github.tesujimath.zbackup`, so prefix each property listed here with `com.github.tesujimath.zbackup:`, following the best practice for user properties as described on the zfs man page.

   - `*tier*-snapshots`      - turns on snapshots, and limits how many snapshots to keep in given tier
   - `*tier*-snapshot-limit` - limits how many snapshots to keep in given tier (overrides *tier*-snapshots)
   - `replica`               - comma-separated list of dstdatasetname, as used by zreplicate
   - `replicate`             - *tier*, which tier to replicate

   See `zbackup --list`, `zbackup --set`, and `zbackup --unset` below for an easy interface to listing, setting, and unsetting these properties.

   Snapshotting for a given tier will be active as soon as `*tier*-snapshots` is defined with an integer value, with a property source of local.  Received properties will not cause new snapshots to be taken.

   However, old snapshots will be reaped if the property source is local or received.  This means that reaping old snapshots on a destination replica is driven by the received property `*tier*-snapshots`, or the property `*tier*-snapshot-limit`, with the latter overriding the former if both are present.  Note that the limit property functions even if its source is inherited.

   Replication is done for a single tier only, as per the 'replicate' property. Again, these properties must have the source being local to have any effect. Note that the `--no-replication-stream` option for zreplicate is used, so that no destination replica snapshots and filesystems are deleted as a side-effect of running a backup.  To purge obsolete snapshots from the destination, it is recommended to use the behaviour described in the previous paragraph.

## Locking of filesystems during replication
Replicating a large filesystem can take many hours, perhaps so long that another zbackup instance is started by cron in the meantime.  For this reason, all filesystems to be replicated are first locked using `zlock`.  A subsequent `zbackup` will simply skip any such locked filesystem.

To manually disable replication of a filesystem, `zlock` may be run by hand.  This may be useful for example when migrating replicas from one replica server to another.  See `zlock --help` for details.

Note that `zlock` has no effect beyond disabling replication by `zbackup`.  (It does nothing at the ZFS filesystem level.  It simply creates a lockfile in */var/lib/zfs-tools/zlock*, which is checked only by later instances of `zlock`.)

## ssh authentication
   It is up to you to arrange your own ssh authentication.  For example, you could use an ssh agent and ssh public key authentication, or say Kerberos.  (The crontab example below assumes Kerberos, which explains the call to kinit to acquire a Kerberos ticket from the local keytab file.)
## Interfacing with cron
   zbackup is best run as a cron job.  It is up to you to define the tiers which make sense to you, but these would be reasonable entries in a crontab:

```
0 8,9,10,11,12,13,14,15,16,17,18 * * * zbackup -v -t '\%Y-\%m-\%d-\%H\%M' hourly >/root/zbackup.hourly 2>&1
0 23 * * * kinit -k -C root/HOST.YOURDOMAIN ; zbackup -v -t '\%Y-\%m-\%d-\%H\%M' -d hourly daily >/root/zbackup.daily 2>&1
30 23 * * 0 zbackup -v -t '\%Y-\%m-\%d-\%H\%M' weekly >/root/zbackup.weekly 2>&1
45 23 1 * * zbackup -v -t '\%Y-\%m-\%d-\%H\%M' monthly >/root/zbackup.monthly 2>&1
```
### Notes
1. Percent signs need to be escaped in crontabs.

2. I specify the timestamp format explicitly, to avoid seconds appearing in the timestamps.  You may choose to not care about that.

3. My daily tier sets up ssh authentication by acquiring a Kerberos ticket from the local keytab.  This is for a system which performs replication in the daily tier.  You will have to change this to match your system requirements.

4. the `-d hourly` option in the daily zbackup deletes all hourly snapshots, so these do not appear on the destination replica.  It is up to you to decide what behaviour you want.

## Getting started
   Run `zbackup --help` for the usage, and complete options.

   Run `zbackup --list` to see what backup properties are set.

   Setting and unsetting of the properties used by zbackup is most easily done using zbackup --set, and zbackup --unset.  For example:

```
# zbackup --set zpoolsrc/playpen daily-snapshots=6 weekly-snapshots=5 replica=MYREPLICASERVER:zpooldst/playpen2/replica/zpoolsrc/playpen replicate=daily

# zbackup --list
```

## Error reporting
It is clearly rather important to know if zbackup fails.  Any or all of these three mechanisms can be used:

1. Non-zero exit status

2. Error text appearing on stderr.

3. Optionally, use the -e option to email the given recipient on failure.

It is recommended to use these to check carefully that replication in particular is working as intended.

## The dangers of ZFS replication streams when used for backup
The default behaviour of zsnap is to use ZFS replication streams, i.e. `zfs send -R`.  This is inhibited when zsnap is called from zbackup, using the `--no-replication-stream` option to zsnap.

The problem with ZFS replication streams arises when you have nested ZFS datasets, e.g. home, with a dataset for each user's home directory.  If a user's home is deleted on the source side, using zfs destroy, then `zfs send -R` will replicate this deletion to the destination side.

zbackup avoids this unsafe behaviour following a `zfs destroy` operation on the source side.

## Author
zbackup was written by Simon Guest, developed in the [tesujimath fork of zfs-tools](https://github.com/tesujimath/zfs-tools), and now contributed upstream.  Thanks to the original author of zfs-tools for providing an excellent framework on which to base zbackup.
