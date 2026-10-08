#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import unittest

sys.path.append(".")
sys.path.append("..")

from components.logging import SimpleLoggerConfig
from components.mach_vendor import VendorProvider
from components.utilities import Struct
from tests.mock_commandprovider import TestCommandProvider

LIBRARY = Struct(**{'yaml_path': 'media/libyuv/moz.yaml'})
REVISION = "3f3735e3f39c68d33104add994bfe5d055b32e17"


class TestVendorProvider(unittest.TestCase):
    def _check_for_update(self, mach_output):
        """Run check_for_update against a mocked `./mach vendor` stdout."""
        commandProvider = TestCommandProvider({
            'test_mappings': {
                "./mach vendor --check-for-update": lambda: mach_output
            }
        })
        commandProvider.update_config(SimpleLoggerConfig)

        vendorProvider = VendorProvider({})
        vendorProvider.update_config(dict(SimpleLoggerConfig, CommandProvider=commandProvider))
        return vendorProvider.check_for_update(LIBRARY)

    def testGooglesourceTimestamp(self):
        # googlesource reports commit dates in git's default format, so the
        # timestamp field contains spaces and must not be split on them.
        self.assertEqual(
            self._check_for_update(REVISION + " Wed Sep 09 17:56:48 2026"),
            (REVISION, "2026-09-09 17:56:48"))

    def testISO8601Timestamp(self):
        self.assertEqual(
            self._check_for_update(REVISION + " 2026-09-09T17:56:48Z"),
            (REVISION, "2026-09-09 17:56:48"))

    def testOffsetTimestampIsConvertedToUTC(self):
        # gitlab and codeberg report the committer's local time with an offset;
        # the uniform date must be UTC, not the committer's wall-clock time.
        self.assertEqual(
            self._check_for_update(REVISION + " 2026-09-25T12:59:00.000+10:00"),
            (REVISION, "2026-09-25 02:59:00"))

    def testNegativeOffsetCrossesMidnight(self):
        self.assertEqual(
            self._check_for_update(REVISION + " 2026-09-17T22:36:18.000-04:00"),
            (REVISION, "2026-09-18 02:36:18"))

    def testNoUpdateAvailable(self):
        self.assertEqual(self._check_for_update(""), (None, None))


if __name__ == "__main__":
    unittest.main(verbosity=0)
