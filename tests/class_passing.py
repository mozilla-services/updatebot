#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import unittest

sys.path.append(".")
sys.path.append("..")

from components.dbmodels import TryRun


class TestClassPassing(unittest.TestCase):
    def testLambda1(self):
        x = TryRun({
            'id': 1,
            'revision': 2,
            'job_id': 3,
            'purpose': 4
        })

        def foo(t):
            t.job_id = 6

        self.assertEqual(x.job_id, 3, "Starting value is not correct")
        foo(x)
        self.assertEqual(x.job_id, 6, "Resulting value is not correct")


if __name__ == '__main__':
    unittest.main(verbosity=0)
