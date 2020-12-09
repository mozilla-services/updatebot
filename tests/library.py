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
        "schema": 1,
        "bugzilla": {"product": "Core", "component": "Audio/Video: cubeb"},
        "origin": {
            "name": "cubeb",
            "description": "Cross platform audio library",
            "url": "https://github.com/kinetiknz/cubeb",
            "license": "ISC",
            "release": "a7e83aa2b1571b842a555158e8f25aeb1419ebd1 (2020-10-13 12:05:17 +0100)"
        },
        "updatebot": {
            "enabled": False,
            "maintainer-needinfo": "nobody@mozilla.com",
            "maintainer-phab": "nobody"
        },
        "yaml_path": "{0}/.circleci/gecko-test/libcubeb/moz.yaml".format(os.getcwd())
    }),
    Struct(**{
        "schema": 1,
        "bugzilla": {"product": "Core", "component": "Audio/Video: Playback"},
        "origin": {
            "name": "aom",
            "description": "av1 decoder",
            "url": "https://aomedia.googlesource.com/aom/",
            "release": "commit 1e227d41f0616de9548a673a83a21ef990b62591 (Tue Sep 18 17:30:35 2018 +0000).",
            "revision": "1e227d41f0616de9548a673a83a21ef990b62591",
            "license": "BSD-2-Clause"
        },
        "vendoring": {
            "url": "https://aomedia.googlesource.com/aom",
            "source-hosting": "googlesource",
            "vendor-directory": "third_party/aom",
            "exclude": ["build/.gitattributes", "build/.gitignore"],
            "update-actions": [
                {"action": "delete-path", "path": "{yaml_dir}/config"},
                {
                    "action": "run-script",
                    "script": "{cwd}/generate_sources_mozbuild.sh",
                    "cwd": "{yaml_dir}"
                }
            ]
        },
        "yaml_path": "{0}/.circleci/gecko-test/libaom/moz.yaml".format(os.getcwd())
    }),
    Struct(**{
        "schema": 1,
        "bugzilla": {"product": "Core", "component": "Audio/Video: Playback"},
        "origin": {
            "name": "dav1d",
            "description": "dav1d, a fast AV1 decoder",
            "url": "https://code.videolan.org/videolan/dav1d",
            "release": "commit 0243c3ffb644e61848b82f24f5e4a7324669d76e (2020-09-27T15:38:45.000+02:00).",
            "revision": "0243c3ffb644e61848b82f24f5e4a7324669d76e",
            "license": "BSD-2-Clause",
            "license-file": "COPYING"
        },
        "updatebot": {
            "enabled": True,
            "maintainer-phab": "nobody",
            "maintainer-bz": "nobody@mozilla.com"
        },
        "vendoring": {
            "url": "https://code.videolan.org/videolan/dav1d.git",
            "source-hosting": "gitlab",
            "vendor-directory": "third_party/dav1d",
            "exclude": ["build/.gitattributes", "build/.gitignore"],
            "update-actions": [
                {
                    "action": "copy-file",
                    "from": "include/vcs_version.h.in",
                    "to": "{yaml_dir}/vcs_version.h"
                },
                {
                    "action": "replace-in-file",
                    "pattern": "@VCS_TAG@",
                    "with": "{revision}",
                    "file": "{yaml_dir}/vcs_version.h"
                }
            ]
        },
        "yaml_path": "{0}/.circleci/gecko-test/libdav1d/moz.yaml".format(os.getcwd())
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
        libs = self.libraryprovider.get_libraries("./")

        def check_list(list_a, list_b, list_name):
            for a in list_a:
                try:
                    b = next(x for x in list_b if x.origin["name"] == a.origin["name"])
                    for prop in dir(a):
                        if not prop.startswith("__") and prop != "id":
                            try:
                                self.assertTrue(
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
    unittest.main()
