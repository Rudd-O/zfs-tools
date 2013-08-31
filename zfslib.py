#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import subprocess
import os
import time
import optparse
import threading
import signal
import select
from zfsutils import uniq
from zfsutils import simplify
import warnings
import itertools

# solaris doesn't have python 2.5, we copy code from the Python library this as a compatibility measure
try: from subprocess import CalledProcessError
except ImportError:
	class CalledProcessError(Exception):
		"""This exception is raised when a process run by check_call() returns
		a non-zero exit status.  The exit status will be stored in the
		returncode attribute."""
		def __init__(self, returncode, cmd):
			self.returncode = returncode
			self.cmd = cmd
		def __str__(self):
			return "Command '%s' returned non-zero exit status %d" % (self.cmd, self.returncode)

def run_command(cmd,inp=None,capture_stderr=False):
        if capture_stderr:
                p = subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        else:
                p = subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE)

        # work around the stupidest python bug
        stdout = []
        stderr = []
        def read(pipe,chunk_accumulator):
                while True:
                        chunk = pipe.read()
                        if chunk == "": break
                        chunk_accumulator.append(chunk)
        soreader = threading.Thread(target=read,args=(p.stdout,stdout))
        soreader.setDaemon(True)
        soreader.start()
        if capture_stderr:
                sereader = threading.Thread(target=read,args=(p.stderr,stderr))
                sereader.setDaemon(True)
                sereader.start()

        if inp: p.stdin.write(inp)

        exit = p.wait()
        soreader.join()
        if capture_stderr:
                sereader.join()
        if exit != 0:
                c = CalledProcessError(exit,cmd)
                raise c
        return ''.join(stdout),''.join(stderr)

def progressbar(pipe,bufsize=-1,ratelimit=-1):

    def clpbar(cmdname):
        barargs = []
        if bufsize != -1:
            barargs = ["-bs",str(bufsize)]
        if ratelimit != -1:
            barargs = barargs + ['-th',str(ratelimit)]
        barprg = subprocess.Popen(
            [cmdname,"-dan"] + barargs,
            stdin=pipe,stdout=subprocess.PIPE,bufsize=bufsize)
        return barprg

    def pv(cmdname):
        barargs = []
        if bufsize != -1:
            barargs = ["-B",str(bufsize)]
        if ratelimit != -1:
            barargs = barargs + ['-L',str(ratelimit)]
        barprg = subprocess.Popen(
            [cmdname,"-ptrb"] + barargs,
            stdin=pipe,stdout=subprocess.PIPE,bufsize=bufsize)
        return barprg

    barprograms = [
        ("bar",clpbar),
        ("clpbar",clpbar),
        ("pv",pv),
    ]

    for name,func in barprograms:
        try:
            subprocess.call([name,'-h'],stdout=file(os.devnull,"w"),stderr=file(os.devnull,"w"),stdin=file(os.devnull,"r"))
        except OSError,e:
            if e.errno == 2: continue
            assert 0, "not reached while searching for clpbar or pv"
        return func(name)
    raise OSError(2,"no such file or directory searching for clpbar or pv")


class Dataset:
	name = None
	children = None
	parent = None
	invalidated = False
	def __init__(self,name,parent=None):
		self.name = name
		self.children = []
		if parent:
			self.parent = parent
			self.parent.add_child(self)

	def add_child(self,child):
		self.children.append(child)
		return child

	def get_child(self,name):
		child = [ c for c in self.children if c.name == name and isinstance(c,Dataset) ]
		assert len(child) < 2
		if not child: raise KeyError,name
		return child[0]

	def get_snapshots(self,flt=True):
		if flt is True: flt = lambda x:True
		children = [ c for c in self.children if isinstance(c,Snapshot) and flt(c) ]
		return children

	def get_snapshot(self,name):
		children = [ c for c in self.get_snapshots() if c.name == name ]
		assert len(children) < 2
		if not children: raise KeyError,name
		return children[0]

	def lookup(self,name): # FINISH THIS
		if "@" in name:
			path,snapshot = name.split("@")
		else:
			path = name
			snapshot = None

		if "/" not in path:
			try: dset = self.get_child(path)
			except KeyError: raise KeyError,"No such dataset %s at %s" %(path,self.get_path())
			if snapshot:
				try: dset = dset.get_snapshot(snapshot)
				except KeyError: raise KeyError,"No such snapshot %s at %s" %(snapshot,dset.get_path())
		else:
			head,tail = path.split("/",1)
			try: child = self.get_child(head)
			except KeyError: raise KeyError,"No such dataset %s at %s" %(head,self.get_path())
			if snapshot: tail = tail + "@" + snapshot
			dset = child.lookup(tail)

		return dset

	def remove(self,child):
		if child not in self.children: raise KeyError, child.name
		child.invalidated = True
		child.parent = None
		self.children.remove(child)
		for c in child.children:
			child.remove(c)

	def get_path(self):
		if not self.parent: return self.name
		return "%s/%s"%(self.parent.get_path(),self.name)

	def get_relative_name(self):
		if not self.parent: return self.name
		return self.get_path()[len(self.parent.get_path())+1:]

	def walk(self):
		assert not self.invalidated, "%s invalidated"%self
		yield self
		for c in self.children:
			for element in c.walk():
				yield element
			
	def __iter__(self):
		return self.walk()

	def __str__(self):
		return "<Dataset:  %s>"%self.get_path()
	__repr__ = __str__

	def get_creation(self):
		return self._creation


class Pool(Dataset):
	def __str__(self):
		return "<Pool:     %s>"%self.get_path()
	__repr__ = __str__


class Snapshot(Dataset):
	#def __init__(self,name):
		#Dataset.__init__(self,name)
	def get_path(self):
		if not self.parent: return self.name
		return "%s@%s"%(self.parent.get_path(),self.name)

	def __str__(self):
		return "<Snapshot: %s>"%self.get_path()
	__repr__ = __str__


class PoolSet: # maybe rewrite this as a dataset or something?
	pools = None

	def __init__(self):
		self.pools = {}

	def lookup(self,name):
		if "@" in name:
			path,snapshot = name.split("@")
		else:
			path = name
			snapshot = None

		if "/" not in path:
			try: dset = self.pools[path]
			except KeyError: raise KeyError,"No such pool %s" %(name)
			if snapshot:
				try: dset = dset.get_snapshot(snapshot)
				except KeyError: raise KeyError,"No such snapshot %s at %s" %(snapshot,dset.get_path())
		else:
			head,tail = path.split("/",1)
			try: pool = self.pools[head]
			except KeyError: raise KeyError,"No such pool %s" %(head)
			if snapshot: tail = tail + "@" + snapshot
			dset = pool.lookup(tail)

		return dset

	def parse_zfs_r_output(self,output,creationtimes):

		# make into array
		lines = [ s.strip() for s in output.splitlines() ]

		creations = dict([ s.strip().split("	") for s in creationtimes.splitlines() if s.strip() ])

		# names of pools
		old_dsets = [ x.get_path() for x in self.walk() ]
		old_dsets.reverse()
		new_dsets = [ s.split("	")[0] for s in lines ]
		
		for dset in new_dsets:
			if "@" in dset:
				dset, snapshot = dset.split("@")
			else:
				snapshot = None
			if "/" not in dset: # pool name
				if dset not in self.pools:
					self.pools[dset] = Pool(dset)
					fs = self.pools[dset]
			poolname, pathcomponents = dset.split("/")[0],dset.split("/")[1:]
			fs = self.pools[poolname]
			for pcomp in pathcomponents:
				# traverse the child hierarchy or create if that fails
				try: fs = fs.get_child(pcomp)
				except KeyError:
					fs = Dataset(pcomp,fs)

			if snapshot:
				if snapshot not in [ x.name for x in fs.children ]:
					fs = Snapshot(snapshot,fs)

			fs._creation = creations[fs.get_path()]

		for dset in old_dsets:
			if dset not in new_dsets:
				if "/" not in dset and "@" not in dset: # a pool
					self.remove(dset)
				else:
					d = self.lookup(dset)
					d.parent.remove(d)

	def remove(self,name): # takes a NAME, unlike the child that is taken in the remove of the dataset method
		for c in self.pools[name].children:
			self.pools[name].remove(c)
		self.pools[name].invalidated = True
		del self.pools[name]

	def __getitem__(self,name):
		return self.pools[name]

	def __str__(self):
		return "<PoolSet at %s>"%id(self)
	__repr__ = __str__

	def walk(self):
		for item in self.pools.values():
			for dset in item.walk():
				yield dset

	def __iter__(self):
		return self.walk()


class ZFSConnection:
	host = None
	_poolset = None
	_dirty = True
	_trust = False
	def __init__(self,host="localhost", trust=False):
		self.host = host
		self._trust = trust
		self._poolset= PoolSet()
		if host in ['localhost','127.0.0.1']:
			self.command = ["zfs"]
		else:
			self.command = ["ssh","-o","BatchMode yes","-a","-x","-c","arcfour"]
			if self._trust:
				self.command.extend(["-o","CheckHostIP no"])
				self.command.extend(["-o","StrictHostKeyChecking no"])
			self.command.extend([self.host,"zfs"])

	def _get_poolset(self):
		if self._dirty:
			stdout,stderr = run_command(self.command+["list","-r","-t","all","-H","-o","name"])
			stdout2,stderr2 = run_command(self.command+["get","-r","-o","name,value","creation","-Hp"])
			self._poolset.parse_zfs_r_output(stdout,stdout2)
			self._dirty = False
		return self._poolset
	pools = property(_get_poolset)

	def create_dataset(self,name):
		run_command(self.command+["create","-o","mountpoint=none",name])
		self._dirty = True
		return self.pools.lookup(name)

	def destroy(self,name):
		run_command(self.command+["destroy",'-r',name])
		self._dirty = True

	def snapshot_recursively(self,name,snapshotname):
		run_command(self.command+["snapshot","-r","%s@%s"%(name,snapshotname)])
		self._dirty = True

	def send(self,name,opts=None,bufsize=-1,compression=False):
		if not opts: opts = []
		cmd = list(self.command)
                if compression and cmd[0] == 'ssh': cmd.insert(1,"-C")
		cmd = cmd + ["send"] + opts + [name]
		p = subprocess.Popen(cmd,stdin=file(os.devnull),stdout=subprocess.PIPE,bufsize=bufsize)
		return p

	def receive(self,name,pipe,opts=None,bufsize=-1,compression=False):
		if not opts: opts = []
                cmd = list(self.command)
                if compression and cmd[0] == 'ssh': cmd.insert(1,"-C")
		cmd = cmd + ["receive"] + opts + [name]
		p = subprocess.Popen(cmd,stdin=pipe,bufsize=bufsize)
		return p

	def transfer(src_conn,dst_conn,s,d,fromsnapshot=None,showprogress=False,bufsize=-1,send_opts=None,receive_opts=None,ratelimit=-1,compression=False):
		if send_opts is None: send_opts = []
		if receive_opts is None: receive_opts = []
		
		if fromsnapshot: fromsnapshot=["-i",fromsnapshot]
		else: fromsnapshot = []
		sndprg = src_conn.send(s,opts=[]+fromsnapshot+send_opts,bufsize=bufsize,compression=compression)
		
		if showprogress:
		    try:
                        barprg = progressbar(pipe=sndprg.stdout,bufsize=bufsize,ratelimit=ratelimit)
                        sndprg.stdout.close()
		    except OSError, e:
                        os.kill(sndprg.pid,15)
                        raise
		else:
			barprg = sndprg

		try:
                        rcvprg = dst_conn.receive(d,pipe=barprg.stdout,opts=["-Fu"]+receive_opts,bufsize=bufsize,compression=compression)
                        barprg.stdout.close()
		except OSError:
			os.kill(sndprg.pid,15)
			if sndprg.pid != barprg.pid: os.kill(barprg.pid,15)
			raise

                dst_conn._dirty = True
                if showprogress:
                        sendret, barret, rcvret = sndprg.wait(), barprg.wait(), rcvprg.wait()
                else:
                        sendret, barret, rcvret = sndprg.wait(), 0, rcvprg.wait()
                if sendret:
                        raise CalledProcessError(sendret,["zfs","send"])
                if barret:
                        raise CalledProcessError(barret,["clpbar"])
                if rcvret:
                        raise CalledProcessError(rcvret,["zfs","recv"])

def stderr(text):
	"""print out something to standard error, followed by an ENTER"""
	sys.stderr.write(text)
	sys.stderr.write("\n")

# it is time to determine which datasets need to be synced
# we walk the entire dataset structure, and sync snapshots recursively
def recursive_replicate(s,d):
    sched = []

    # we first collect all snapshot names, to later see if they are on both sides, one side, or what
    all_snapshots = []
    if s: all_snapshots.extend(s.get_snapshots())
    if d: all_snapshots.extend(d.get_snapshots())
    all_snapshots = [ y[1] for y in sorted([ (x.get_creation(),x.name) for x in all_snapshots ]) ]
    snapshot_pairs = []
    for snap in all_snapshots:
        try: ssnap = s.get_snapshot(snap)
        except (KeyError,AttributeError): ssnap = None
        try: dsnap = d.get_snapshot(snap)
        except (KeyError,AttributeError): dsnap = None
        # if the source snapshot exists and is not already in the table of snapshots
        # then pair it up with its destination snapshot (if it exists) or None
        # and add it to the table of snapshots
        if ssnap and not snap in [ x[0].name for x in snapshot_pairs ]:
            snapshot_pairs.append((ssnap,dsnap))

    # now we have a list of all snapshots, paired up by name, and in chronological order
    # (it's quadratic complexity, but who cares)
    # now we need to find the snapshot pair that happens to be the the most recent common pair
    found_common_pair = False
    for idx,(m,n) in enumerate(snapshot_pairs):
        if m and n and m.name == n.name:
            found_common_pair = idx

    # we have combed through the snapshot pairs
    # time to check what the latest common pair is
    if not s.get_snapshots():
        # well, no snapshots in source, do nothing
        pass
    elif found_common_pair is False:
        # no snapshot is in common, problem!
        # theoretically destroying destination dataset and resyncing it recursively would work
        # but this requires work in the optimizer that comes later
        if d is not None and d.get_snapshots():
            warnings.warn("Asked to replicate %s into %s but %s has snapshots and both have no snapshots in common!"%(s,d,d))
        sched.append(("full",s,d,None,snapshot_pairs[-1][0]))
    elif found_common_pair == len(snapshot_pairs) - 1:
        # the latest snapshot of both datasets that is common to both, is the latest snapshot in the source
        # we have nothing to do here because the datasets are "in sync"
        pass
    else:
        # the source dataset has more recent snapshots, not present in the destination dataset
        # we need to transfer those
        snapshots_to_transfer = [ x[0] for x in snapshot_pairs[found_common_pair:] ]
        for n,x in enumerate(snapshots_to_transfer):
            if n == 0: continue
            sched.append(("incremental",s,d,snapshots_to_transfer[n-1],x))

    # now let's apply the same argument to the children
    children_sched = []
    for c in [ x for x in s.children if not isinstance(x,Snapshot) ]:
        try: cd = d.get_child(c.name)
        except (KeyError,AttributeError): cd = None
        children_sched.extend(recursive_replicate(c,cd))

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
    for source, opgroup in [ (x,list(y)) for x,y in operations_grouped_by_source ]:
        if not opgroup: # empty opgroup
            continue
        if opgroup[0][0] == 'full': # full operations
            new.extend(opgroup)
        elif opgroup[0][0] == 'incremental': # incremental
            # 1->2->3->4 => 1->4
            new_ops = [ (srcs,dsts) for op,src,dst,srcs,dsts in opgroup ]
            new_ops = simplify(new_ops)
            for srcs, dsts in new_ops:
                new.append(tuple(opgroup[0][:3] + (srcs, dsts)))
        else:
            assert 0, "not reached: unknown operation type in %s" % opgroup
    return new

def optimize_recursivize(operation_schedule):
    def recurse(dataset, func):
        results = []
        results.append((dataset,func(dataset)))
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
    operations_grouped_by_source = [ (x,list(y)) for x,y in operations_grouped_by_source ]

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
        assert len(ops_schedules), "operations schedules cannot be empty: %r"%ops_schedules

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
                    len(set([o[0] for o in ops])) == 1,
                    any([o[3] is None for o in ops]) or len(set([o[3].name for o in ops])) == 1,
                    len(set([o[4].name for o in ops])) == 1,
                ])
                for ops
                in zip(*ops_schedules)
        ]
        return all(comparisons)

    for root in roots:
        for dataset, _ in recurse(root, lambda d: d):
            if compare(*[y for x,y in recurse(dataset, lambda d: d._ops_schedule)]):
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

def optimize(operation_schedule):
    operation_schedule = optimize_coalesce(operation_schedule)
    operation_schedule = optimize_recursivize(operation_schedule)
    return operation_schedule
