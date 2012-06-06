#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import subprocess
import os
import time
import optparse
import threading
import signal

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


def children_first(pathlist): return sorted(pathlist,key=lambda x:-x.count("/"))
def parents_first(pathlist): return sorted(pathlist,key=lambda x:x.count("/"))
chronosorted = sorted

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
            [cmdname,"-ptrab"] + barargs,
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

		#print "***Parsing ZFS output***"

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
					#print "	Adding pool %s"%fs
			poolname, pathcomponents = dset.split("/")[0],dset.split("/")[1:]
			fs = self.pools[poolname]
			for pcomp in pathcomponents:
				# traverse the child hierarchy or create if that fails
				try: fs = fs.get_child(pcomp)
				except KeyError:
					fs = Dataset(pcomp,fs)
					#print "	Adding dataset %s"%fs

			if snapshot:
				if snapshot not in [ x.name for x in fs.children ]:
					fs = Snapshot(snapshot,fs)
					#print "	Adding snapshot %s"%fs

			fs._creation = creations[fs.get_path()]

		for dset in old_dsets:
			if dset not in new_dsets:
				#print "	Removing %s"%dset
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
	def __init__(self,host="localhost"):
		self.host = host
		self._poolset= PoolSet()
		if host in ['localhost','127.0.0.1']:
			self.command = ["zfs"]
		else:
			self.command = ["ssh","-o","BatchMode yes","-a","-x","-c","arcfour",self.host,"zfs"]

	def _get_poolset(self):
		if self._dirty:
			stdout,stderr = run_command(self.command+["list","-r","-t","all","-H"])
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
		cmd = self.command
                if cmd[0] == 'ssh': cmd.insert(1,"-C")
		cmd = cmd + ["send"] + opts + [name]
		# print "Executing command",cmd
		p = subprocess.Popen(cmd,stdin=file(os.devnull,"r"),stdout=subprocess.PIPE,bufsize=bufsize)
		return p

	def receive(self,name,pipe,opts=None,bufsize=-1,compression=False):
		if not opts: opts = []
                cmd = self.command
                if cmd[0] == 'ssh': cmd.insert(1,"-C")
		cmd = cmd + ["receive"] + opts + [name]
		# print "Executing command",cmd
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
		    except OSError, e:
                        os.kill(sndprg.pid,15)
                        raise
		else:
			barprg = sndprg

		try: rcvprg = dst_conn.receive(d,pipe=barprg.stdout,opts=["-Fu"]+receive_opts,bufsize=bufsize,compression=compression)
		except OSError:
			os.kill(sndprg.pid,15)
			if sndprg.pid != barprg.pid: os.kill(barprg.pid,15)
			raise

                dst_conn._dirty = True
		ret = sndprg.wait()
		if ret:
			os.kill(rcvprg.pid,15)
			if sndprg.pid != barprg.pid: os.kill(barprg.pid,15)
			raise CalledProcessError(ret,["zfs","send"])

		ret2 = rcvprg.wait()
		if ret2:
                        if sndprg.pid != barprg.pid: os.kill(barprg.pid,15)
                        raise CalledProcessError(ret2,["zfs","receive"])

                if sndprg.pid != barprg.pid:
                        ret3 = barprg.wait()
                        if ret3:
                                raise CalledProcessError(ret3,["clpbar"])

def stderr(text):
	"""print out something to standard error, followed by an ENTER"""
	sys.stderr.write(text)
	sys.stderr.write("\n")
