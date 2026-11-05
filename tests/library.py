#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import unittest
import os
import tempfile

sys.path.append(".")
sys.path.append("..")

from components.libraryprovider import LibraryProvider, Library
from components.utilities import Struct
from tests.mock_commandprovider import TestCommandProvider
from components.logging import SimpleLoggerConfig

LIBRARIES = [
    Library({
        "name": "cubeb-query",
        "revision": "a7e83aa2b1571b842a555158e8f25aeb1419ebd1",
        "repo_url": "https://github.com/mozilla/cubeb",
        "has_patches": False,
        "flavor": 'regular',

        "bugzilla_product": "Core",
        "bugzilla_component": "Audio/Video: cubeb",
        "maintainer_bz": "nobody@mozilla.com",
        "maintainer_phab": "nobody",
        "fuzzy_query": "media",
        "tasks": [
                    LibraryProvider.validate_task({
                        'type': "vendoring",
                        'enabled': True
                    }, "n/a")
        ],
        "yaml_path": ".github/gecko-test/libcubeb-query/moz.yaml"
    }),
    Library({
        "name": "cubeb-preset",
        "revision": "a7e83aa2b1571b842a555158e8f25aeb1419ebd1",
        "repo_url": "https://github.com/mozilla/cubeb",
        "has_patches": False,
        "flavor": 'regular',

        "bugzilla_product": "Core",
        "bugzilla_component": "Audio/Video: cubeb",
        "maintainer_bz": "nobody@mozilla.com",
        "maintainer_phab": "nobody",
        "try_preset": "sm-shell",
        "artifact_build": True,
        "tasks": [
                    LibraryProvider.validate_task({
                        'type': "vendoring",
                        'enabled': True
                    }, "n/a")
        ],
        "yaml_path": ".github/gecko-test/libcubeb-preset/moz.yaml"
    }),
    Library({
        "name": "cubeb-path",
        "revision": "a7e83aa2b1571b842a555158e8f25aeb1419ebd1",
        "repo_url": "https://github.com/mozilla/cubeb",
        "has_patches": False,
        "flavor": 'regular',

        "bugzilla_product": "Core",
        "bugzilla_component": "Audio/Video: cubeb",
        "maintainer_bz": "nobody@mozilla.com",
        "maintainer_phab": "nobody",
        "fuzzy_paths": ["media/"],
        "tasks": [
                    LibraryProvider.validate_task({
                        'type': "vendoring",
                        'enabled': True,
                        'blocking': '1234',
                        'options': ['one', 'two']
                    }, "n/a")
        ],
        "yaml_path": ".github/gecko-test/libcubeb-path/moz.yaml"
    }),
    Library({
        "name": "dav1d",
        "revision": "0243c3ffb644e61848b82f24f5e4a7324669d76e",
        "repo_url": "https://code.videolan.org/videolan/dav1d.git",
        "has_patches": False,
        "flavor": 'regular',

        "bugzilla_product": "Core",
        "bugzilla_component": "Audio/Video: Playback",
        "maintainer_bz": "nobody@mozilla.com",
        "maintainer_phab": "nobody",
        "tasks": [
                    LibraryProvider.validate_task({
                        'type': "vendoring",
                        'enabled': True,
                    }, "n/a")
        ],
        "yaml_path": ".github/gecko-test/libdav1d/moz.yaml",
        "vendor_directory": "third_party/dav1d"
    }),
    Library({
        'name': 'libpng',
        'revision': 'v1.6.37',
        'repo_url': 'https://github.com/glennrp/libpng',
        "has_patches": True,
        "flavor": 'regular',

        'bugzilla_product': 'Core',
        'bugzilla_component': 'ImageLib',
        'maintainer_bz': 'aosmond@mozilla.com',
        'maintainer_phab': 'aosmond',
        'tasks': [
            LibraryProvider.validate_task({
                'type': 'vendoring',
                'enabled': True,
            }, "n/a")
        ],
        'yaml_path': '.github/gecko-test/libpng/moz.yaml'
    })
]

LIBRARY_FIND_OUTPUT = "\n".join([
    "{0}/.github/gecko-test/libcubeb-query/moz.yaml",
    "{0}/.github/gecko-test/libcubeb-preset/moz.yaml",
    "{0}/.github/gecko-test/libcubeb-path/moz.yaml",
    "{0}/.github/gecko-test/libaom/moz.yaml",
    "{0}/.github/gecko-test/libdav1d/moz.yaml",
    "{0}/.github/gecko-test/libnope/moz.yaml",
    "{0}/.github/gecko-test/libpng/moz.yaml"
]).format(os.getcwd())


class TestLibraryProvider(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # We will need a CommandProvider, so instatiate that directly
        cls.commandProvider = TestCommandProvider({
            'test_mappings': {
                "find": lambda x: LIBRARY_FIND_OUTPUT,
                "dir": lambda x: LIBRARY_FIND_OUTPUT
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

    def testLibraryHasPatches(self):
        def has_patches(contents):
            with tempfile.TemporaryDirectory() as gecko:
                if contents is not None:
                    with open(os.path.join(gecko, "moz.yaml"), "w") as f:
                        f.write(contents)
                return self.libraryprovider.library_has_patches(gecko, Struct(yaml_path='moz.yaml'))

        self.assertTrue(has_patches("vendoring:\n  url: https://example.invalid\n  patches:\n    - mozilla.patch\n"))
        self.assertFalse(has_patches("vendoring:\n  url: https://example.invalid\n  patches: []\n"))
        self.assertFalse(has_patches("vendoring:\n  url: https://example.invalid\n"))
        # A broken moz.yaml is an error, not a library without patches.
        for broken in ["origin:\n  name: foo\n", "", "vendoring: [unclosed\n", None]:
            with self.assertRaises(Exception, msg=repr(broken)):
                has_patches(broken)

    def testLibraryFindAndImport(self):
        libs = self.libraryprovider.get_libraries(os.getcwd())
        self.maxDiff = 999999
        self.assertEqual(libs, LIBRARIES)

    def testVendorDirectoryAndGeneratedPaths(self):
        # These checkout-relative paths decide which changes the spurious-update check
        # ignores, so test them from real moz.yaml contents.
        def manifest(vendoring_extra):
            return """
schema: 1
bugzilla:
  product: Core
  component: "Audio/Video: Playback"
origin:
  name: libfoo
  description: a library
  url: https://example.com/foo
  revision: 0243c3ffb644e61848b82f24f5e4a7324669d76e
vendoring:
  url: https://example.com/foo.git
%s
updatebot:
  maintainer-bz: foo
  maintainer-phab: bar
  tasks:
    - type: vendoring
""" % vendoring_extra

        yaml_path = os.path.join("media", "libfoo", "moz.yaml")

        # An explicit vendor-directory, different from the moz.yaml's directory
        lib = LibraryProvider.validate_library(manifest("""  vendor-directory: third_party/foo
  generated:
    - config.h
    - include/version.h"""), yaml_path)
        self.assertEqual(lib.vendor_directory, "third_party/foo")
        self.assertEqual(lib.generated, [os.path.join("third_party/foo", "config.h"), os.path.join("third_party/foo", "include/version.h")])

        # No vendor-directory: it's the moz.yaml's directory
        lib = LibraryProvider.validate_library(manifest("""  generated:
    - config.h"""), yaml_path)
        self.assertEqual(lib.vendor_directory, os.path.join("media", "libfoo"))
        self.assertEqual(lib.generated, [os.path.join("media", "libfoo", "config.h")])

        # No generated files
        lib = LibraryProvider.validate_library(manifest("""  vendor-directory: third_party/foo"""), yaml_path)
        self.assertEqual(lib.vendor_directory, "third_party/foo")
        self.assertEqual(lib.generated, [])

    def testArtifactBuild(self):
        def artifact_build(updatebot_extra):
            return LibraryProvider.validate_library("""
schema: 1
bugzilla:
  product: Core
  component: "Audio/Video: Playback"
origin:
  name: libfoo
updatebot:
  maintainer-bz: foo
  maintainer-phab: bar
  try-preset: sm-shell
%s""" % updatebot_extra, "fake/path").artifact_build

        self.assertIs(artifact_build("  artifact-build: true"), True)
        self.assertIs(artifact_build("  artifact-build: True"), True)
        self.assertIs(artifact_build("  artifact-build: false"), False)
        self.assertIs(artifact_build(""), False)

    def testOnlyLinuxTasksRun(self):
        def task_types(tasks):
            return [t.type for t in LibraryProvider.validate_library("""
schema: 1
bugzilla:
  product: Core
  component: "Audio/Video: Playback"
origin:
  name: libfoo
  revision: 0123456789abcdef
vendoring:
  url: https://example.com/libfoo
updatebot:
  maintainer-bz: foo
  maintainer-phab: bar
  tasks:
%s""" % tasks, "fake/path").tasks]

        self.assertEqual(task_types("    - type: vendoring"), ["vendoring"])
        self.assertEqual(task_types("    - type: vendoring\n      platform: linux"), ["vendoring"])
        # Updatebot only runs on Linux, so a task for Windows is valid but never runs
        self.assertEqual(task_types("    - type: vendoring\n      platform: windows\n    - type: commit-alert"), ["commit-alert"])

    def testLibraryExceptions(self):
        test_vectors = [
            ("Blank", ""),
            ("No name",
             """
schema: 1
bugzilla:
  product: Core
  component: "Audio/Video: Playback"
origin:
  description: dav1d, a fast AV1 decoder
  url: https://code.videolan.org/videolan/dav1d
  revision: 0243c3ffb644e61848b82f24f5e4a7324669d76e
"""),
            ("No product",
             """
schema: 1
bugzilla:
  component: "Audio/Video: Playback"
origin:
  name: libdav1d
  description: dav1d, a fast AV1 decoder
  url: https://code.videolan.org/videolan/dav1d
  revision: 0243c3ffb644e61848b82f24f5e4a7324669d76e
"""),
            ("No revision",
             """
schema: 1
bugzilla:
  component: "Audio/Video: Playback"
origin:
  name: libdav1d
  description: dav1d, a fast AV1 decoder
  url: https://code.videolan.org/videolan/dav1d
vendoring:
  url: https://code.videolan.org/videolan/dav1d.git
updatebot:
  maintainer-phab: bar
  maintainer-bz: bar
  tasks:
    - type: commit-alert
"""),
            ("No repo url",
             """
schema: 1
bugzilla:
  component: "Audio/Video: Playback"
origin:
  name: libdav1d
  description: dav1d, a fast AV1 decoder
  url: https://code.videolan.org/videolan/dav1d
updatebot:
  maintainer-phab: bar
  maintainer-bz: bar
  tasks:
    - type: commit-alert
"""),
            ("No component",
             """
schema: 1
bugzilla:
  product: Core
origin:
  name: libdav1d
  description: dav1d, a fast AV1 decoder
  url: https://code.videolan.org/videolan/dav1d
  revision: 0243c3ffb644e61848b82f24f5e4a7324669d76e
"""),
            ("No maintainer bz",
             """
schema: 1
bugzilla:
  product: Core
  component: "Audio/Video: Playback"
origin:
  name: libdav1d
  description: dav1d, a fast AV1 decoder
  url: https://code.videolan.org/videolan/dav1d
  revision: 0243c3ffb644e61848b82f24f5e4a7324669d76e
vendoring:
  url: https://code.videolan.org/videolan/dav1d.git
updatebot:
  maintainer-phab: bar
  tasks:
    - type: vendoring
    - type: commit-alert
"""),
            ("No maintainer phab",
             """
schema: 1
bugzilla:
  product: Core
  component: "Audio/Video: Playback"
origin:
  name: libdav1d
  description: dav1d, a fast AV1 decoder
  url: https://code.videolan.org/videolan/dav1d
  revision: 0243c3ffb644e61848b82f24f5e4a7324669d76e
vendoring:
  url: https://code.videolan.org/videolan/dav1d.git
updatebot:
  maintainer-bz: foo
  tasks:
    - type: vendoring
    - type: commit-alert
"""),
            ("Bad platform",
             """
schema: 1
bugzilla:
  product: Core
  component: "Audio/Video: Playback"
origin:
  name: libdav1d
  description: dav1d, a fast AV1 decoder
  url: https://code.videolan.org/videolan/dav1d
  revision: 0243c3ffb644e61848b82f24f5e4a7324669d76e
vendoring:
  url: https://code.videolan.org/videolan/dav1d.git
updatebot:
  maintainer-bz: foo
  maintainer-phab: foo
  tasks:
    - type: vendoring
      platform: mac
    - type: commit-alert
"""),
            ("Bad vendoring task",
             """
schema: 1
bugzilla:
  product: Core
  component: "Audio/Video: Playback"
origin:
  name: libdav1d
  description: dav1d, a fast AV1 decoder
  url: https://code.videolan.org/videolan/dav1d
  revision: 0243c3ffb644e61848b82f24f5e4a7324669d76e
vendoring:
  url: https://code.videolan.org/videolan/dav1d.git
updatebot:
  maintainer-bz: foo
  maintainer-phab: bar
  tasks:
    - type: vendoring
      filter: none
    - type: commit-alert
"""),
            ("Invalid task type",
             """
schema: 1
bugzilla:
  product: Core
  component: "Audio/Video: Playback"
origin:
  name: libdav1d
  description: dav1d, a fast AV1 decoder
  url: https://code.videolan.org/videolan/dav1d
  revision: 0243c3ffb644e61848b82f24f5e4a7324669d76e
vendoring:
  url: https://code.videolan.org/videolan/dav1d.git
updatebot:
  maintainer-bz: foo
  maintainer-phab: bar
  tasks:
    - type: vendoring
    - type: bob
"""),
        ]
        for vector in test_vectors:
            try:
                self.libraryprovider.validate_library(vector[1], "fake/path")
            except Exception:
                continue
            self.assertFalse(vector, "The test vector '%s' did not raise an expected exception." % vector[0])


if __name__ == "__main__":
    unittest.main(verbosity=0)
