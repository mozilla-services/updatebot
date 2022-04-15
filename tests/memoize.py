#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import unittest

sys.path.append(".")
sys.path.append("..")

from components.utilities import MemoizeImpl, Memoize


class Thing:
    def __init__(self):
        self.inner_thing1 = {2: 6}
        self.inner_thing2 = [set([8])]


@Memoize
def func(a, b, c):
    return c + 3


class TestMemoize(unittest.TestCase):
    def test(self):
        a = {4: 90}
        b = [Thing(), Thing()]

        MemoizeImpl.hits = 0
        MemoizeImpl.misses = 0
        func(a, b, 7)
        func(a, b, 8)
        self.assertEqual(MemoizeImpl.misses, 2, "Memoize did not have the expected misses")
        self.assertEqual(MemoizeImpl.hits, 0, "Memoize did not have the expected hits")
        func(a, b, 7)
        func(a, b, 8)
        self.assertEqual(MemoizeImpl.misses, 2, "Memoize did not have the expected misses")
        self.assertEqual(MemoizeImpl.hits, 2, "Memoize did not have the expected hits")


if __name__ == '__main__':
    unittest.main(verbosity=0)
