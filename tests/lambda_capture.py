#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import unittest

sys.path.append(".")
sys.path.append("..")


class TestLambdaCapture(unittest.TestCase):
    def testLambda1(self):
        x = 5

        def foo():
            return x

        x = 6
        self.assertEqual(foo(), 6, "Function capture does not behave as expected")


if __name__ == '__main__':
    unittest.main(verbosity=0)
