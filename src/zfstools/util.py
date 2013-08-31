'''
Created on Mar 19, 2013

@author: rudd-o
'''

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

