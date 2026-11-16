#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import unittest
import subprocess

sys.path.append(".")
sys.path.append("..")

from components.logging import SimpleLoggerConfig
from components.mach_vendor import VendorProvider, VendorResult
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

    def _library(self, stages, uses_stages=True):
        return Struct(yaml_path='media/libyuv/moz.yaml', uses_stages=uses_stages,
                      has_patches=any(s['patches'] for s in stages), stages=stages)

    def testStageCommands(self):
        vendorProvider = VendorProvider({})
        fetch = {'name': 'fetch', 'patches': [], 'title': None}
        patches = {'name': 'patches', 'patches': ['a.patch'], 'title': None}

        one = self._library([fetch])
        self.assertEqual(vendorProvider.stage_command(one, 0, REVISION),
                         ["./mach", "vendor", "media/libyuv/moz.yaml", "--revision", REVISION])
        # Only the first stage takes the revision; later ones use what it recorded.
        two = self._library([fetch, patches])
        self.assertEqual(vendorProvider.stage_command(two, 0, REVISION),
                         ["./mach", "vendor", "media/libyuv/moz.yaml", "--revision", REVISION, "--stage", "1"])
        self.assertEqual(vendorProvider.stage_command(two, 1, REVISION),
                         ["./mach", "vendor", "media/libyuv/moz.yaml", "--stage", "2"])

        old = self._library([fetch, patches], uses_stages=False)
        self.assertEqual(vendorProvider.stage_command(old, 0, REVISION),
                         ["./mach", "vendor", "media/libyuv/moz.yaml", "--revision", REVISION, "--patch-mode", "none"])
        self.assertEqual(vendorProvider.stage_command(old, 1, REVISION),
                         ["./mach", "vendor", "--patch-mode", "only", "media/libyuv/moz.yaml"])
        self.assertEqual(vendorProvider.stage_command(self._library([fetch], uses_stages=False), 0, REVISION),
                         ["./mach", "vendor", "media/libyuv/moz.yaml", "--revision", REVISION])

    def _vendor_stage(self, returncode, uses_stages=True, output="Error running mach"):
        calls = []

        def run(cmd, clean_return=True, **run_kwargs):
            calls.append(clean_return)
            return subprocess.CompletedProcess(cmd, returncode, stdout=output, stderr="")

        vendorProvider = VendorProvider({})
        vendorProvider.update_config(dict(SimpleLoggerConfig, CommandProvider=Struct(run=run)))
        stages = [{'name': 'fetch', 'patches': [], 'title': None}, {'name': 'patches', 'patches': ['foo.patch'], 'title': None}]
        result = vendorProvider.vendor_stage(self._library(stages, uses_stages), 1, REVISION)
        # A failure is reported, not logged as an error by the CommandProvider
        self.assertEqual(calls, [False])
        return result

    def testVendorStageResults(self):
        self.assertEqual(self._vendor_stage(0), (VendorResult.SUCCESS, ""))
        self.assertEqual(self._vendor_stage(1), (VendorResult.GENERAL_ERROR, "Error running mach"))
        self.assertEqual(self._vendor_stage(1, output="Could not apply foo.patch"), (VendorResult.PATCH_CONFLICT, "Could not apply foo.patch"))
        self.assertEqual(self._vendor_stage(255), (VendorResult.MOZBUILD_ERROR, "Error running mach"))
        # 254 was the old spurious-update check's exit status; mach vendor with
        # stages has none.
        self.assertEqual(self._vendor_stage(254, uses_stages=False)[0], VendorResult.SPURIOUS_UPDATE)
        self.assertEqual(self._vendor_stage(254)[0], VendorResult.GENERAL_ERROR)


if __name__ == "__main__":
    unittest.main(verbosity=0)
