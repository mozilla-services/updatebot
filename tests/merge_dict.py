#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import unittest

sys.path.append(".")
sys.path.append("..")
from components.utilities import merge_dictionaries


class TestMergeDictionaries(unittest.TestCase):
    def testMerge1(self):
        a = {}
        b = {}

        expected = {}

        c = merge_dictionaries(a, b)
        self.assertEqual(expected, c)

        c = merge_dictionaries(b, a)
        self.assertEqual(expected, c)

    def testMerge2(self):
        a = {'a': 2}
        b = {'b': 3}

        expected = {'a': 2, 'b': 3}

        c = merge_dictionaries(a, b)
        self.assertEqual(expected, c)

        c = merge_dictionaries(b, a)
        self.assertEqual(expected, c)

    def testMerge3(self):
        a = {'a': 2, 'foo': {'1': 'g', '2': 'h'}}
        b = {'b': 3, 'foo': {'3': 'i', '4': 'j'}}

        expected = {'a': 2, 'b': 3, 'foo': {'1': 'g', '2': 'h', '3': 'i', '4': 'j'}}

        c = merge_dictionaries(a, b)
        self.assertEqual(expected, c)

        c = merge_dictionaries(b, a)
        self.assertEqual(expected, c)

    def testMerge4(self):
        a = {'a': 2, 'foo': {'1': 'g', '2': 'h', 'l': [1, 2, 3]}}
        b = {'b': 3, 'foo': {'3': 'i', '4': 'j', 'l': [3, 4, 5]}}

        expected = {'a': 2, 'b': 3, 'foo': {'1': 'g', '2': 'h', '3': 'i', '4': 'j', 'l': [1, 2, 3, 3, 4, 5]}}

        c = merge_dictionaries(a, b)
        self.assertEqual(expected, c)

        c = merge_dictionaries(b, a)
        self.assertEqual(expected, c)

    def testMerge5(self):
        a = {'a': 2}
        b = {'a': 3}

        try:
            merge_dictionaries(a, b)
            self.assertTrue(False, "Should have thrown an exception.")
        except Exception:
            pass

        try:
            merge_dictionaries(b, a)
            self.assertTrue(False, "Should have thrown an exception.")
        except Exception:
            pass

    def testMerge6(self):
        a = {'a': 2}
        b = {'b': [3, 4]}

        try:
            merge_dictionaries(a, b)
            self.assertTrue(False, "Should have thrown an exception.")
        except Exception:
            pass

        try:
            merge_dictionaries(b, a)
            self.assertTrue(False, "Should have thrown an exception.")
        except Exception:
            pass

    def testMerge7(self):
        a = {'a': 2}
        b = {'b': 3}

        expected = {'a': 2, 'b': 3}

        c = merge_dictionaries(a, b)
        self.assertEqual(expected, c)


if __name__ == '__main__':
    unittest.main(verbosity=0)
