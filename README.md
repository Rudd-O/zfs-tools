#ZFS tools

The ZFS backup tools will help you graft an entire ZFS pool as a filesystem
into a backup machine, without having to screw around snapshot names or
complicated shell commands or crontabs.

The utilities let you do this:

1. zfs-shell:  
   a shell that allows remote ZFS administration and nothing more

2. zmirror:  
   a command that snapshots a dataset or pool, then sends the snapshots,
   dataset by dataset, to another machine, without using replication streams.
   It will delete obsolete snapshots on the source and destination machines,
   keeping a maximum of one snapshot tree on each machine.  It will not
   delete snapshots indiscriminately, though -- it will only delete snapshots
   prefixed with zmirror-.

3. zsnap:  
   a command that snapshots a dataset or pool, then deletes old snapshots

4. zreplicate  
   a command that replicates an entire dataset tree using ZFS replication
   streams.  Best used in combination with zsnap as in:
   
   - zsnap on the local machine
   - zreplicate from the local machine to the destination machine

   Obsolete snapshots deleted by zsnap will be automatically purged on
   the destination machine by zreplicate.
   
   Run `zreplicate --help` for a compendium of options you may use.

The repository, bug tracker and Web site for this tool is at [http://github.com/Rudd-O/zfs-tools](http://github.com/Rudd-O/zfs-tools).  Comments to me through rudd-o@rudd-o.com.

##Setting up

Setup is rather complicated.  It assumes that you already have ZFS running
and vaults on both the machine you're going to back up and the machine that
will be receiving the backup.

###On the machine to back up

- Install the zfs-shell command   
  `cp zfs-shell /usr/local/sbin`  
  `chmod 755 /usr/local/sbin/zfs-shell`  
  `chown root.root /usr/local/sbin/zfs-shell`  

- Create a user with a home directory and shell `zfs-shell`  
  `useradd -rUm -b /var/lib -s /usr/local/sbin/zfs-shell zfs`

- Let `sudo` know that the new user can run the zfs command  
  `zfs ALL = NOPASSWD: /usr/local/sbin/zfs`  
  (ensure you remove the `requiretty` default on `/etc/sudoers`)

- Set up a cron job to run `zsnap` as frequently as you want to,
  snapshotting the dataset you intend to replicate.

###On the backup machine

- Set up public key authentication for SSH so the backup machine
  may log as the user `zfs` (as laid out above) in the machine to
  be backed up.

- Create a dataset to receive the backup stream.

- Set up a cron job to fetch the dataset snapshotted by zsnap
  from the remote machine into the newly created dataset.  You
  will use `zreplicate` for that (see below for examples).

- After the first replication, you may want to set the `mountpoint`
  attributes on the received datasets so they do not automount
  on the backup machine.

###Test

If all went well, you should be able to do this without issue:

(on the machine to back up)

    [root@peter]
    zsnap senderpool

(on the machine to receive)

    [root@paul]
    zfs create receiverpool/senderpool # <--- run this ONLY ONCE
    zreplicate -o zfs@paul:senderpool receiverpool/senderpool
    # this should send the entire senderpool with all snapshots
    # over from peter to paul, placing it in receiverpool/senderpool

(on the machine to back up)

    [root@peter]
    zsnap senderpool

(on the machine to receive)

    [root@paul]
    zreplicate -o zfs@paul:senderpool receiverpool/senderpool
    # this should send an incremental stream of senderpool
    # into receiverpool/senderpool

And that's it, really.

##zmirror

Zmirror is an useful command that does not replicate a dataset tree and
all of its snapshots, but rather only replicates dataset by dataset
(still recursively, but breaking the logical references between datasets)
and only keeps the latest snapshot.  This can be useful in the case that
you do not have as much disk space on the receiving pool as you have on
the source pool.  It, however, will not respect deduplication, clones or
copy-on-write, so there's that.  It is old code that I was using before
I figured out how to effectively use replication streams in lieu of simple
dataset sends and receives.