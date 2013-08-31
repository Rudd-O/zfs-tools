'''
Miscellaneous utility functions
'''

import sys
import os
import subprocess

def simplify(x):
    '''Take a list of tuples where each tuple is in form [v1,v2,...vn]
    and then coalesce all tuples tx and ty where tx[v1] equals ty[v2],
    preserving v3...vn of tx and discarding v3...vn of ty.

    m = [
    (1,2,"one"),
    (2,3,"two"),
    (3,4,"three"),
    (8,9,"three"),
    (4,5,"four"),
    (6,8,"blah"),
    ]
    simplify(x) -> [[1, 5, 'one'], [6, 9, 'blah']]
    '''
    y = list(x)
    if len(x) < 2: return y
    for idx,o in enumerate(list(y)):
        for idx2,p in enumerate(list(y)):
            if idx == idx2: continue
            if o and p and o[0] == p[1]:
                y[idx] = None
                y[idx2] = list(p)
                y[idx2][0] = p[0]
                y[idx2][1] = o[1]
    return [ n for n in y if n is not None ]

def uniq(seq, idfun=None):
    '''Makes a sequence 'unique' in the style of UNIX command uniq'''
    # order preserving
    if idfun is None:
        def idfun(x): return x
    seen = {}
    result = []
    for item in seq:
        marker = idfun(item)
        # in old Python versions:
        # if seen.has_key(marker)
        # but in new ones:
        if marker in seen: continue
        seen[marker] = 1
        result.append(item)
    return result

def progressbar(pipe, bufsize=-1, ratelimit=-1):

    def clpbar(cmdname):
        barargs = []
        if bufsize != -1:
            barargs = ["-bs", str(bufsize)]
        if ratelimit != -1:
            barargs = barargs + ['-th', str(ratelimit)]
        barprg = subprocess.Popen(
            [cmdname, "-dan"] + barargs,
            stdin=pipe, stdout=subprocess.PIPE, bufsize=bufsize)
        return barprg

    def pv(cmdname):
        barargs = []
        if bufsize != -1:
            barargs = ["-B", str(bufsize)]
        if ratelimit != -1:
            barargs = barargs + ['-L', str(ratelimit)]
        barprg = subprocess.Popen(
            [cmdname, "-ptrb"] + barargs,
            stdin=pipe, stdout=subprocess.PIPE, bufsize=bufsize)
        return barprg

    barprograms = [
        ("bar", clpbar),
        ("clpbar", clpbar),
        ("pv", pv),
    ]

    for name, func in barprograms:
        try:
            subprocess.call([name, '-h'], stdout=file(os.devnull, "w"), stderr=file(os.devnull, "w"), stdin=file(os.devnull, "r"))
        except OSError, e:
            if e.errno == 2: continue
            assert 0, "not reached while searching for clpbar or pv"
        return func(name)
    raise OSError(2, "no such file or directory searching for clpbar or pv")

def stderr(text):
    """print out something to standard error, followed by an ENTER"""
    sys.stderr.write(text)
    sys.stderr.write("\n")

__verbose = False
def verbose_stderr(*args, **kwargs):
    global __verbose
    if __verbose: stderr(*args, **kwargs)

def set_verbose(boolean):
    global __verbose
    __verbose = boolean
