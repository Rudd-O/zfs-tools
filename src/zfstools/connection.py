'''
ZFS connection classes
'''

import subprocess
import os
from zfstools.models import PoolSet
from zfstools.util import progressbar, SpecialPopen
from Queue import Queue
from threading import Thread


# Work-around for check_output not existing on Python 2.6, as per
# http://stackoverflow.com/questions/4814970/subprocess-check-output-doesnt-seem-to-exist-python-2-6-5
# The implementation is lifted from
# http://hg.python.org/cpython/file/d37f963394aa/Lib/subprocess.py#l544
if "check_output" not in dir( subprocess ): # duck punch it in!
    def f(*popenargs, **kwargs):
        if 'stdout' in kwargs:
            raise ValueError('stdout argument not allowed, it will be overridden.')
        process = subprocess.Popen(stdout=subprocess.PIPE, *popenargs, **kwargs)
        output, unused_err = process.communicate()
        retcode = process.poll()
        if retcode:
            cmd = kwargs.get("args")
            if cmd is None:
                cmd = popenargs[0]
            raise subprocess.CalledProcessError(retcode, cmd) # , output=output)
        return output
    subprocess.check_output = f

class ZFSConnection:
    host = None
    _poolset = None
    _dirty = True
    _trust = False
    _properties = None
    def __init__(self,host="localhost", trust=False, sshcipher=None, properties=None):
        self.host = host
        self._trust = trust
        self._properties = properties if properties else []
        self._poolset= PoolSet()
        if host in ['localhost','127.0.0.1']:
            self.command = ["zfs"]
        else:
            self.command = ["ssh","-o","BatchMode yes","-a","-x"]
            if self._trust:
                self.command.extend(["-o","CheckHostIP no"])
                self.command.extend(["-o","StrictHostKeyChecking no"])
            if sshcipher != None:
                self.command.extend(["-c",sshcipher])
            self.command.extend([self.host,"zfs"])

    def _get_poolset(self):
        if self._dirty:
            properties = [ 'creation' ] + self._properties
            stdout2 = subprocess.check_output(self.command + ["list", "-Hpr", "-o", ",".join( ['name'] + properties ), "-s", "creation", "-t", "all"])
            self._poolset.parse_zfs_r_output(stdout2,properties)
            self._dirty = False
        return self._poolset
    pools = property(_get_poolset)

    def create_dataset(self,name):
        subprocess.check_call(self.command + ["create", name])
        self._dirty = True
        return self.pools.lookup(name)

    def destroy_dataset(self, name):
        subprocess.check_call(self.command + ["destroy", name])
        self._dirty = True

    def destroy_recursively(self, name):
        subprocess.check_call(self.command + ["destroy", '-r', name])
        self._dirty = True

    def snapshot_recursively(self,name,snapshotname,properties={}):
        plist = sum( map( lambda x: ['-o', '%s=%s' % x ], properties.items() ), [] )
        subprocess.check_call(self.command + ["snapshot", "-r" ] + plist + [ "%s@%s" % (name, snapshotname)])
        self._dirty = True
    
    def send(self,name,opts=None,bufsize=-1,compression=False):
        if not opts: opts = []
        cmd = list(self.command)
        if compression and cmd[0] == 'ssh': cmd.insert(1,"-C")
        cmd = cmd + ["send"] + opts + [name]
        p = SpecialPopen(cmd,stdin=file(os.devnull),stdout=subprocess.PIPE,bufsize=bufsize)
        return p

    def receive(self,name,pipe,opts=None,bufsize=-1,compression=False):
        if not opts: opts = []
        cmd = list(self.command)
        if compression and cmd[0] == 'ssh': cmd.insert(1,"-C")
        cmd = cmd + ["receive"] + opts + [name]
        p = SpecialPopen(cmd,stdin=pipe,bufsize=bufsize)
        return p

    def transfer(self, dst_conn, s, d, fromsnapshot=None, showprogress=False, bufsize=-1, send_opts=None, receive_opts=None, ratelimit=-1, compression=False):
        if send_opts is None: send_opts = []
        if receive_opts is None: receive_opts = []
        
        queue_of_killables = Queue()

        if fromsnapshot: fromsnapshot=["-i",fromsnapshot]
        else: fromsnapshot = []
        sndprg = self.send(s, opts=[] + fromsnapshot + send_opts, bufsize=bufsize, compression=compression)
        sndprg_supervisor = Thread(target=lambda: queue_of_killables.put((sndprg, sndprg.wait())))
        sndprg_supervisor.start()

        if showprogress:
            try:
                        barprg = progressbar(pipe=sndprg.stdout,bufsize=bufsize,ratelimit=ratelimit)
                        barprg_supervisor = Thread(target=lambda: queue_of_killables.put((barprg, barprg.wait())))
                        barprg_supervisor.start()
                        sndprg.stdout.close()
            except OSError:
                        os.kill(sndprg.pid,15)
                        raise
        else:
            barprg = sndprg

        try:
                        rcvprg = dst_conn.receive(d,pipe=barprg.stdout,opts=["-Fu"]+receive_opts,bufsize=bufsize,compression=compression)
                        rcvprg_supervisor = Thread(target=lambda: queue_of_killables.put((rcvprg, rcvprg.wait())))
                        rcvprg_supervisor.start()
                        barprg.stdout.close()
        except OSError:
                os.kill(sndprg.pid, 15)
                if sndprg.pid != barprg.pid: os.kill(barprg.pid, 15)
                raise

        dst_conn._dirty = True
        allprocesses = set([rcvprg, sndprg]) | ( set([barprg]) if showprogress else set() )
        while allprocesses:
            diedprocess, retcode = queue_of_killables.get()
            allprocesses = allprocesses - set([diedprocess])
            if retcode != 0:
                [ p.kill() for p in allprocesses ]
                raise subprocess.CalledProcessError(retcode, diedprocess._saved_args)
