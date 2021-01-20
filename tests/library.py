#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import unittest
import os

sys.path.append(".")
sys.path.append("..")
from components.libraryprovider import LibraryProvider
from tests.mock_commandprovider import TestCommandProvider
from components.utilities import Struct
from components.logging import SimpleLoggerConfig

LIBRARIES = [
    Struct(**{
        "bugzilla": {"product": "Core", "component": "Audio/Video: Playback"},
        "origin": {
            "name": "dav1d",
            "revision": "0243c3ffb644e61848b82f24f5e4a7324669d76e"
        },
        "updatebot": {
            "enabled": True,
            "maintainer-bz": "nobody@mozilla.com",
            "maintainer-phab": "nobody"
        },
        "yaml_path": ".circleci/gecko-test/libdav1d/moz.yaml"
    })
]

LIBRARY_FIND_OUTPUT = """
{0}/.circleci/gecko-test/libcubeb/moz.yaml
{0}/.circleci/gecko-test/libaom/moz.yaml
{0}/.circleci/gecko-test/libdav1d/moz.yaml
""".format(os.getcwd())


class TestLibraryProvider(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # We will need a CommandProvider, so instatiate that directly
        cls.commandProvider = TestCommandProvider({
            'test_mappings': {
                "find": LIBRARY_FIND_OUTPUT
            }
        })
        # And provide it with a logger
        cls.commandProvider.update_config(SimpleLoggerConfig)
        # Now instatiate a LibraryProvider (it doesn't need any config)
        cls.libraryprovider = LibraryProvider({})
        # Provide it with a logger and an instatiation of the CommandProvider
        additional_config = SimpleLoggerConfig
        additional_config.update({
            'CommandProvider': cls.commandProvider
        })
        cls.libraryprovider.update_config(additional_config)

    def testLibraryFindAndImport(self):
        libs = self.libraryprovider.get_libraries(os.getcwd())

        def check_list(list_a, list_b, list_name):
            for a in list_a:
                try:
                    b = next(x for x in list_b if x.origin["name"] == a.origin["name"])
                    for prop in dir(a):
                        if not prop.startswith("__") and prop != "id":
                            try:
                                self.assertEqual(
                                    getattr(b, prop), getattr(a, prop))
                            except AttributeError:
                                self.assertTrue(
                                    False, "The attribute {0} was not found on the {1} list's object".format(prop, list_name))
                except StopIteration:
                    self.assertTrue(False, "{0} was not found in the {1} list of libraries".format(
                        a.origin.name, list_name))

        check_list(libs, LIBRARIES, "original")
        check_list(LIBRARIES, libs, "disk's")


if __name__ == "__main__":
    unittest.main(verbosity=0)
