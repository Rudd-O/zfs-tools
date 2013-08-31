'''
Tests for the zfstools.util module
'''
import unittest
from zfstools import util as zfsutils


class TestSimplify(unittest.TestCase):

    def test_simple(self):
        m = [
        (1,2,"one"),
        (2,3,"two"),
        ]
        r1 = zfsutils.simplify(m)
        r2 = [[1, 3, 'one']]
        self.assertEquals(r1, r2)        

    def test_complex(self):
        m = [
        (1,2,"one"),
        (2,3,"two"),
        (3,4,"three"),
        (8,9,"three"),
        (4,5,"four"),
        (6,8,"blah"),
        ]
        r1 = zfsutils.simplify(m)
        r2 = [[1, 5, 'one'], [6, 9, 'blah']]
        self.assertEquals(r1, r2)        

    def test_discrete(self):
        m = [
        (1,2,"one"),
        (2,4,"two"),
        (6,9,"three"),
        ]
        # note last element is a tuple
        r1 = zfsutils.simplify(m)
        r2 = [[1, 4, 'one'], (6, 9, 'three')]
        self.assertEquals(r1, r2)        

    def test_with_strings(self):
        m = [
        "abM",
        "bcN",
        "cdO",
        ]
        # note last element is a tuple
        r1 = zfsutils.simplify(m)
        r2 = [list("adM")]
        self.assertEquals(r1, r2)        

class TestUniq(unittest.TestCase):
    
    def test_identity(self):
        s = "abc"
        r1 = zfsutils.uniq(s)
        r2 = list(s)
        self.assertEquals(r1,r2)

    def test_similarelement(self):
        s = "abcb"
        r1 = zfsutils.uniq(s)
        r2 = list("abc")
        self.assertEquals(r1,r2)

    def test_repeatedsequences(self):
        s = "abcabc"
        r1 = zfsutils.uniq(s)
        r2 = list("abc")
        self.assertEquals(r1,r2)

    def test_idfun(self):
        s = "abc"
        idfun = lambda _: "a"
        r1 = zfsutils.uniq(s, idfun)
        r2 = list("a")
        self.assertEquals(r1,r2)

if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testName']
    unittest.main()
