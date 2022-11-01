'''
Tree models for the ZFS tools
'''
import sys
from collections import OrderedDict
from datetime import datetime

is_py2=(sys.version_info[0] == 2)

class Dataset(object):
    name = None
    children = None
    _properties = None
    parent = None
    invalidated = False
    def __init__(self, name, parent=None):
        self.name = name
        self.children = []
        self._properties = {}
        if parent:
            self.parent = parent
            self.parent.add_child(self)

    def add_child(self, child):
        self.children.append(child)
        return child

    def get_child(self, name):
        child = [ c for c in self.children if c.name == name and isinstance(c, Dataset) ]
        assert len(child) < 2
        if not child: raise KeyError(name)
        return child[0]

    def get_snapshots(self, flt=True):
        if flt is True: flt = lambda _:True
        children = [ c for c in self.children if isinstance(c, Snapshot) and flt(c) ]
        return children

    def get_snapshot(self, name):
        children = [ c for c in self.get_snapshots() if c.name == name ]
        assert len(children) < 2
        if not children: raise KeyError(name)
        return children[0]

    def lookup(self, name):  # FINISH THIS
        if "@" in name:
            path, snapshot = name.split("@")
        else:
            path = name
            snapshot = None

        if "/" not in path:
            try: dset = self.get_child(path)
            except KeyError: raise KeyError("No such dataset %s at %s" % (path, self.get_path()))
            if snapshot:
                try: dset = dset.get_snapshot(snapshot)
                except KeyError: raise KeyError("No such snapshot %s at %s" % (snapshot, dset.get_path()))
        else:
            head, tail = path.split("/", 1)
            try: child = self.get_child(head)
            except KeyError: raise KeyError("No such dataset %s at %s" % (head, self.get_path()))
            if snapshot: tail = tail + "@" + snapshot
            dset = child.lookup(tail)

        return dset

    def remove(self, child):
        if child not in self.children: raise KeyError(child.name)
        child.invalidated = True
        child.parent = None
        self.children.remove(child)
        for c in child.children:
            child.remove(c)

    def get_path(self):
        if not self.parent: return self.name
        return "%s/%s" % (self.parent.get_path(), self.name)

    def get_relative_name(self):
        if not self.parent: return self.name
        return self.get_path()[len(self.parent.get_path()) + 1:]

    def walk(self):
        assert not self.invalidated, "%s invalidated" % self
        yield self
        for c in self.children:
            for element in c.walk():
                yield element

    def __iter__(self):
        return self.walk()

    def __str__(self):
        return "<Dataset:  %s>" % self.get_path()
    __repr__ = __str__

    def get_property(self,name):
        return self._properties[ name ]
    
    def get_creation(self):
        return datetime.fromtimestamp(int(self._properties["creation"]))


class Pool(Dataset):
    def __str__(self):
        return "<Pool:     %s>" % self.get_path()
    __repr__ = __str__


class Snapshot(Dataset):
    # def __init__(self,name):
        # Dataset.__init__(self,name)
    def get_path(self):
        if not self.parent: return self.name
        return "%s@%s" % (self.parent.get_path(), self.name)

    def __str__(self):
        return "<Snapshot: %s>" % self.get_path()
    __repr__ = __str__


class PoolSet:  # maybe rewrite this as a dataset or something?
    pools = None

    def __init__(self):
        self.pools = {}

    def lookup(self, name):
        if "@" in name:
            path, snapshot = name.split("@")
        else:
            path = name
            snapshot = None

        if "/" not in path:
            try: dset = self.pools[path]
            except KeyError: raise KeyError("No such pool %s" % (name))
            if snapshot:
                try: dset = dset.get_snapshot(snapshot)
                except KeyError: raise KeyError("No such snapshot %s at %s" % (snapshot, dset.get_path()))
        else:
            head, tail = path.split("/", 1)
            try: pool = self.pools[head]
            except KeyError: raise KeyError("No such pool %s" % (head))
            if snapshot: tail = tail + "@" + snapshot
            dset = pool.lookup(tail)

        return dset

    def parse_zfs_r_output(self, zfs_r_output, properties = None):
        global is_py2
        """Parse the output of tab-separated zfs list.

        properties must be a list of property names expected to be found as
        tab-separated entries on each line of zfs_r_output after the
        dataset name and a tab.
        E.g. if properties passed here was ['creation'], we would expect
        each zfs_r_output line to look like 'dataset	3249872348'
        """
        try:
            properties = ['name', 'creation'] if properties == None else ['name'] + properties
        except TypeError:
            assert 0, repr(properties)

        def extract_properties(s):
            if not is_py2 and isinstance(s, bytes): s = s.decode('utf-8')
            items = s.strip().split( '\t' )
            assert len( items ) == len( properties ), (properties, items)
            propvalues = map( lambda x: None if x == '-' else x, items[ 1: ] )
            return [ items[ 0 ], zip( properties[ 1: ], propvalues ) ]

        # make into array
        creations = OrderedDict([ extract_properties( s ) for s in zfs_r_output.splitlines() if s.strip() ])

        # names of pools
        old_dsets = [ x.get_path() for x in self.walk() ]
        old_dsets.reverse()
        new_dsets = creations.keys()

        for dset in new_dsets:
            if "@" in dset:
                dset, snapshot = dset.split("@")
            else:
                snapshot = None
            poolname, pathcomponents = dset.split("/")[0], dset.split("/")[1:]
            if poolname not in self.pools:
                self.pools[poolname] = Pool(poolname)
            fs = self.pools[poolname]
            for pcomp in pathcomponents:
                # traverse the child hierarchy or create if that fails
                try: fs = fs.get_child(pcomp)
                except KeyError:
                    fs = Dataset(pcomp, fs)

            if snapshot:
                if snapshot not in [ x.name for x in fs.children ]:
                    fs = Snapshot(snapshot, fs)

            fs._properties.update( creations[fs.get_path()] )

        for dset in old_dsets:
            if dset not in new_dsets:
                if "/" not in dset and "@" not in dset:  # a pool
                    self.remove(dset)
                else:
                    d = self.lookup(dset)
                    d.parent.remove(d)

    def remove(self, name):  # takes a NAME, unlike the child that is taken in the remove of the dataset method
        for c in self.pools[name].children:
            self.pools[name].remove(c)
        self.pools[name].invalidated = True
        del self.pools[name]

    def __getitem__(self, name):
        return self.pools[name]

    def __str__(self):
        return "<PoolSet at %s>" % id(self)
    __repr__ = __str__

    def walk(self):
        for item in self.pools.values():
            for dset in item.walk():
                yield dset

    def __iter__(self):
        return self.walk()
