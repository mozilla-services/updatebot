#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import unittest

sys.path.append(".")
sys.path.append("..")
from components.bugzilla import CommentTemplates
from components.logging import SimpleLogger
from components.utilities import Struct
from tasktypes.vendoring import VendorTaskRunner


class TestChangedLicenseFiles(unittest.TestCase):
    def _changed_license_files(self, changed, license_file=None):
        runner = VendorTaskRunner.__new__(VendorTaskRunner)
        runner.logger = SimpleLogger()
        runner.mercurialProvider = Struct(changed_files_in=lambda directory: changed)
        return runner._changed_license_files(Struct(vendor_directory="third_party/foo", license_file=license_file))

    def testConventionalNames(self):
        changed = [
            "third_party/foo/src/foo.c",
            "third_party/foo/LICENSE",
            "third_party/foo/COPYING.LIB",
            "third_party/foo/fonts/LICENSE_FOXIT",
            "third_party/foo/third_party/nalloc/license.txt",
            "third_party/foo/NOTICE",
            "third_party/foo/COPYRIGHT",
            "third_party/foo/docs/licensing.md",
        ]
        self.assertEqual(self._changed_license_files(changed), changed[1:7])

    def testMozYamlLicenseFile(self):
        changed = ["third_party/foo/docs/FTL.TXT", "third_party/foo/docs/other.txt"]
        self.assertEqual(self._changed_license_files(changed, license_file="docs/FTL.TXT"), ["third_party/foo/docs/FTL.TXT"])

    def testNoLicenseChanges(self):
        self.assertEqual(self._changed_license_files(["third_party/foo/src/foo.c"]), [])

    def testNote(self):
        note = CommentTemplates.LICENSE_FILES_CHANGED(["third_party/foo/LICENSE", "third_party/foo/COPYING"])
        self.assertIn("check that the license in moz.yaml is still correct", note)
        self.assertIn("- third_party/foo/LICENSE\n- third_party/foo/COPYING", note)


if __name__ == '__main__':
    unittest.main(verbosity=0)
